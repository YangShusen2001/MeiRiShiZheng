# -*- coding: utf-8 -*-
"""档案策展：把某月抓到的政策文件过一遍 AI，产出「月度政策档案」。

对每篇输出三件事（考公视角）：
  importance  高/中/低——对公务员考试的价值（高=申论/常识核心考点）
  topic       主题归类（十五五规划 / 民生保障 / 产业发展 / 法治建设 …）
  gist        核心要点 40-90 字（考点角度，非新闻复述）

用法：
  python scripts/curate-archive.py --month 2026-07
  python scripts/curate-archive.py --month 2026-07 --batch 12 --dry

输出：content/archive/<YYYY-MM>/archive.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.deepseek import chat, load_config  # noqa: E402

SYSTEM = (
    "你是公务员考试的时政内容主编。任务：判断一份政策文件对考公的价值，并提炼考点要点。"
    "只返回 JSON，不得返回 Markdown/HTML。"
    "对每一份文件给出："
    "1. importance：\"高\"（申论/常识判断的核心考点，如五年规划、重要法律、中央级战略部署）、"
    "\"中\"（了解即可，如部门实施方案、专项工作通知）、"
    "\"低\"（技术性细则、办事流程、名单批复、地方事务）。"
    "2. topic：从下列主题中选择一个最贴切的："
    "十五五规划、经济发展、民生保障、科技创新、绿色低碳、法治建设、乡村振兴、"
    "教育人才、医疗卫生、文化体育、对外开放、社会治理、安全生产、其他。"
    "3. gist：核心要点 40-90 字。写「这份文件定了什么」，供考生记忆；"
    "不要复述新闻，不要写「本文介绍了」，直接给结论性内容。"
    "输出形状：{\"items\":[{\"index\":0,\"importance\":\"高\",\"topic\":\"十五五规划\",\"gist\":\"…\"}]}"
)


def _load_month(month: str) -> tuple[list[dict], dict[str, dict]]:
    day = ROOT / "content" / "archive" / month
    listing = json.loads((day / "policy-list.json").read_text(encoding="utf-8"))
    bodies: dict[str, dict] = {}
    for f in sorted(day.glob("article-*.json")):
        art = json.loads(f.read_text(encoding="utf-8"))
        if art.get("status") == "ok" and art.get("paragraphs"):
            bodies[art.get("url") or art.get("id")] = art
    return listing["items"], bodies


def _excerpt(art: dict, limit: int = 700) -> str:
    text = "".join(art.get("paragraphs") or [])
    return text[:limit]


def _payload(items: list[dict]) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


def _json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def curate_month(month: str, cfg: dict[str, str], batch: int, dry: bool = False) -> dict:
    items, bodies = _load_month(month)
    rows: list[dict] = []
    for it in items:
        art = bodies.get(it["url"])
        rows.append({
            "url": it["url"], "title": it["title"], "date": it["date"],
            "lib": it["libName"], "topic_hint": it.get("topic", ""),
            "officialSummary": it.get("summary", "")[:200],
            "excerpt": _excerpt(art) if art else "",
            "hasBody": bool(art),
        })
    print(f"{month}: 清单 {len(rows)} 条，其中有正文 {sum(1 for r in rows if r['hasBody'])} 条")

    results: dict[str, dict] = {}
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        payload = [
            {
                "index": i,
                "title": r["title"],
                "issuer": r["lib"],
                "date": r["date"],
                "officialSummary": r["officialSummary"],
                "excerpt": r["excerpt"],
            }
            for i, r in enumerate(chunk)
        ]
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _payload(payload)},
        ]
        if dry:
            print(f"  [dry] 批 {start//batch+1}: {len(chunk)} 篇")
            continue
        out: dict = {}
        for attempt in range(2):
            try:
                out = _json_object(chat(messages, cfg, max_tokens=2000, temperature=0.2))
            except Exception as exc:
                print(f"  批 {start//batch+1} 第 {attempt+1} 次失败：{type(exc).__name__}")
                time.sleep(2)
                continue
            if isinstance(out.get("items"), list):
                break
        got = out.get("items") if isinstance(out.get("items"), list) else []
        for raw in got:
            try:
                idx = int(raw.get("index"))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(chunk):
                continue
            url = chunk[idx]["url"]
            importance = str(raw.get("importance") or "").strip()
            if importance not in ("高", "中", "低"):
                importance = "中"
            results[url] = {
                "importance": importance,
                "topic": str(raw.get("topic") or "其他").strip()[:12],
                "gist": str(raw.get("gist") or "").strip()[:200],
            }
        print(f"  批 {start//batch+1}: 返回 {len(got)} 条")
        time.sleep(0.5)

    if dry:
        return {}

    merged = []
    for r in rows:
        ai = results.get(r["url"]) or {}
        merged.append({
            **{k: r[k] for k in ("url", "title", "date", "lib", "topic_hint")},
            "hasBody": r["hasBody"],
            "importance": ai.get("importance", "中"),
            "topic": ai.get("topic") or "其他",
            "gist": ai.get("gist", ""),
        })
    order = {"高": 0, "中": 1, "低": 2}
    merged.sort(key=lambda x: (order.get(x["importance"], 1), x["date"]), reverse=False)
    doc = {
        "month": month,
        "count": len(merged),
        "high": sum(1 for x in merged if x["importance"] == "高"),
        "medium": sum(1 for x in merged if x["importance"] == "中"),
        "low": sum(1 for x in merged if x["importance"] == "低"),
        "items": merged,
    }
    out_path = ROOT / "content" / "archive" / month / "archive.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{month}: 高 {doc['high']} / 中 {doc['medium']} / 低 {doc['low']} → {out_path}")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    if not cfg.get("deepseek_api_key") and not args.dry:
        print("未配置 DEEPSEEK_API_KEY")
        return 2
    curate_month(args.month, cfg, args.batch, dry=args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
