# -*- coding: utf-8 -*-
"""档案源：按月抓取权威政策文件（中国政府网政策文件库）。

背景（2026-09-12 用户拍板）：时政信息用户不会回头翻，产品需要的不是每日流水，
而是「每月重要政策台账」——即档案源。数据源 = 中国政府网政务搜索接口
（sousuo.www.gov.cn/search-gov/data），两个权威库：
  - zhengcelibrary_gw  国务院文件（2026 年约 6215 条）
  - zhengcelibrary_bm  部门文件（约 12785 条，含各类"十五五"专项规划）

接口按发布时间倒序返回，本脚本翻页回溯到目标月份下限为止，再按月归档。

用法：
  python scripts/fetch-archive.py --months 2026-07,2026-08 [--clip]
  python scripts/fetch-archive.py --months 2026-07 --clip --limit 60

输出：content/archive/<YYYY-MM>/policy-list.json
      --clip 时同时抓正文，存 content/archive/<YYYY-MM>/article-<id>.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.clip import clip_article  # noqa: E402

SEARCH = "https://sousuo.www.gov.cn/search-gov/data"
LIBS = {"gw": "国务院文件", "bm": "部门文件"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
PAGE_SIZE = 100


def _fetch_page(lib: str, page: int, client: httpx.Client) -> list[dict]:
    r = client.get(SEARCH, params={
        "t": f"zhengcelibrary_{lib}", "q": "", "p": page, "n": PAGE_SIZE,
        "sort": "pubtime", "searchfield": "title",
    }, timeout=30)
    r.raise_for_status()
    return ((r.json().get("searchVO") or {}).get("listVO")) or []


def collect(months: list[str], client: httpx.Client) -> list[dict]:
    """翻页采集，直到早于最早目标月为止。"""
    floor = min(months) + "-01"
    out: dict[str, dict] = {}
    for lib in LIBS:
        for page in range(1, 41):  # 上限 4000 条，防失控
            try:
                items = _fetch_page(lib, page, client)
            except Exception as exc:
                print(f"  [{lib}] p{page} 失败 {type(exc).__name__}，停止该库")
                break
            if not items:
                break
            page_dates: list[str] = []
            for it in items:
                url = str(it.get("url") or "")
                if not url:
                    continue
                day = str(it.get("pubtimeStr") or "")[:10].replace(".", "-")
                if not day:
                    continue
                page_dates.append(day)
                out[url] = {
                    "url": url,
                    "title": str(it.get("title") or "").strip(),
                    "date": day,
                    "month": day[:7],
                    "lib": lib,
                    "libName": LIBS[lib],
                    "summary": str(it.get("summary") or "").strip(),
                    "topic": str(it.get("childtype") or "").strip(),
                    "index": str(it.get("index") or "").strip(),
                }
            days = [v["date"] for v in out.values() if v["date"]]
            print(f"  [{lib}] p{page} +{len(items)} 累计 {len(out)} 本页 {min(page_dates)}~{max(page_dates)}")
            # 只有「整页都早于目标下限」才停——单条异常老日期（库内混排）不应终止翻页
            if page_dates and max(page_dates) < floor:
                break
            time.sleep(0.3)
    return [v for v in out.values() if v["month"] in months]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", required=True, help="逗号分隔，如 2026-07,2026-08")
    ap.add_argument("--clip", action="store_true", help="抓正文")
    ap.add_argument("--limit", type=int, default=0, help="每库最多抓正文篇数（0=不限）")
    args = ap.parse_args()

    months = [m.strip() for m in args.months.split(",") if m.strip()]
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        rows = collect(months, client)
        print(f"\n采集 {len(rows)} 条（{len(months)} 个月）")
        by_month: dict[str, list[dict]] = {}
        for r in rows:
            by_month.setdefault(r["month"], []).append(r)

        for month, items in sorted(by_month.items()):
            day_dir = ROOT / "content" / "archive" / month
            day_dir.mkdir(parents=True, exist_ok=True)
            items.sort(key=lambda x: x["date"], reverse=True)
            (day_dir / "policy-list.json").write_text(
                json.dumps({"month": month, "count": len(items), "items": items},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            gw = sum(1 for x in items if x["lib"] == "gw")
            print(f"{month}: {len(items)} 条（国务院 {gw} / 部门 {len(items)-gw}）→ {day_dir/'policy-list.json'}")

        if not args.clip:
            return 0

        for month, items in sorted(by_month.items()):
            day_dir = ROOT / "content" / "archive" / month
            todo = items
            if args.limit:
                todo = items[:args.limit]
            ok = fail = 0
            for i, it in enumerate(todo, 1):
                cid = hashlib.md5(it["url"].encode("utf-8")).hexdigest()[:10]
                out = day_dir / f"article-{cid}.json"
                if out.exists():
                    ok += 1
                    continue
                try:
                    art = clip_article(it["url"], it["title"], it["date"], client=client)
                except Exception as exc:
                    art = {"status": "error", "error": f"{type(exc).__name__}"}
                if art.get("status") == "ok":
                    art["archiveMonth"] = month
                    art["archiveLib"] = it["lib"]
                    art["topic"] = it["topic"]
                    art["officialSummary"] = it["summary"]
                    out.write_text(json.dumps(art, ensure_ascii=False, indent=2), encoding="utf-8")
                    ok += 1
                else:
                    fail += 1
                if i % 10 == 0:
                    print(f"  {month} 剪藏 {i}/{len(todo)}（成功 {ok} 失败 {fail}）")
            print(f"{month}: 正文 {ok} 篇成功 / {fail} 篇失败")
    return 0


if __name__ == "__main__":
    sys.exit(main())
