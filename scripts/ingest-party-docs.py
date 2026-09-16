# -*- coding: utf-8 -*-
"""把党中央文件并入档案（gov.cn 政策文件库只收国务院/部门文件，党的文件需专用通道）。

用法：
  python scripts/ingest-party-docs.py --month 2025-10

做三件事：
1. 扫 content/archive/<月>/article-*.json 中 archiveLib == "党中央文件" 的正文；
2. 调 AI 生成 gist（一篇一次，含 importance/topic 由规则固定为 高/十五五规划）；
3. 合并进 policy-list.json 与 archive.json（去重、按日期重排、刷新计数）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.deepseek import Cfg, chat, load_config  # noqa: E402

PARTY_LIB = "党中央文件"
SYSTEM = (
    "你是公务员考试的时政内容主编。为一份党的文件写「核心要点」，40-90 字，"
    "供考生记忆。写「这份文件定了什么」（定位、原则、目标、关键提法），"
    "不要复述新闻、不要写「本文介绍了」。只返回 JSON：{\"gist\":\"…\"}"
)


def _ai_gist(art: dict, cfg: Cfg) -> str:
    excerpt = "".join(art.get("paragraphs") or [])[:2500]
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"标题：{art.get('title')}\n正文节选：\n{excerpt}"},
    ]
    try:
        text = chat(messages, cfg, max_tokens=400, temperature=0.2)
    except Exception as exc:
        print(f"  AI 失败：{type(exc).__name__}")
        return ""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return ""
    try:
        return str(json.loads(text[start:end + 1]).get("gist") or "").strip()[:200]
    except json.JSONDecodeError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True)
    args = ap.parse_args()
    month = args.month
    day = ROOT / "content" / "archive" / month
    cfg = load_config()

    party: list[dict] = []
    for f in sorted(day.glob("article-*.json")):
        art = json.loads(f.read_text(encoding="utf-8"))
        if art.get("archiveLib") == PARTY_LIB and art.get("status") == "ok":
            party.append(art)
    if not party:
        print(f"{month}: 未找到 {PARTY_LIB} 正文")
        return 0
    print(f"{month}: 党的文件 {len(party)} 篇")

    # 1) 并入 policy-list.json
    lp = day / "policy-list.json"
    listing = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {"month": month, "items": []}
    have = {it["url"] for it in listing["items"]}
    for art in party:
        if art["url"] in have:
            continue
        listing["items"].append({
            "url": art["url"],
            "title": art["title"],
            "date": art.get("pubDate") or art.get("date"),
            "month": month,
            "lib": "party",
            "libName": PARTY_LIB,
            "summary": (art.get("paragraphs") or [""])[0][:200],
            "topic": art.get("topic") or "",
            "index": "",
        })
    listing["items"].sort(key=lambda x: x["date"], reverse=True)
    listing["count"] = len(listing["items"])
    lp.write_text(json.dumps(listing, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) 并入 archive.json（importance 固定「高」——党的文件是最高价值）
    apath = day / "archive.json"
    if not apath.exists():
        print(f"{month}: archive.json 不存在，先跑 curate-archive.py")
        return 1
    doc = json.loads(apath.read_text(encoding="utf-8"))
    have_urls = {it["url"] for it in doc["items"]}
    for art in party:
        if art["url"] in have_urls:
            continue
        gist = _ai_gist(art, cfg) if cfg.get("deepseek_api_key") else ""
        doc["items"].append({
            "url": art["url"],
            "title": art["title"],
            "date": art.get("pubDate") or art.get("date"),
            "lib": PARTY_LIB,
            "topic_hint": art.get("topic") or "",
            "hasBody": True,
            "importance": "高",
            "topic": art.get("topic") or "十五五规划",
            "gist": gist,
        })
        print(f"  + {art['title'][:34]} | gist {len(gist)} 字")
    order = {"高": 0, "中": 1, "低": 2}
    doc["items"].sort(key=lambda x: (order.get(x["importance"], 1), x["date"]))
    doc["count"] = len(doc["items"])
    doc["high"] = sum(1 for x in doc["items"] if x["importance"] == "高")
    doc["medium"] = sum(1 for x in doc["items"] if x["importance"] == "中")
    doc["low"] = sum(1 for x in doc["items"] if x["importance"] == "低")
    apath.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{month}: 高 {doc['high']} / 中 {doc['medium']} / 低 {doc['low']}（共 {doc['count']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
