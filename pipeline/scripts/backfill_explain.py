# -*- coding: utf-8 -*-
"""为已有卡片补 explain（逐项解析）。

## 为什么不直接重跑 --curate-only
重跑会**重新选材**：被选中的文章可能换掉，用户已复习的卡片会变成孤儿
（复习进度存在端上，按卡片 id 记）。这里只对**已写入 picks.json 的文章**
重新提炼卡片，picks 与文章其他字段一律不动。

## 只补文章提炼的卡片，不动人工卡组
文章提炼的卡有 `anchor`（原文出处），explain 有据可依；
`content/cards/*.json` 的人工卡组没有出处，**硬编解析等于编造**——
端上对这类卡用「考点归属」的基础解析兜底，是更诚实的做法。

用法：
    python scripts/backfill_explain.py                # 全部有 picks 的日期
    python scripts/backfill_explain.py 2026-08-21     # 指定日期
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.card_ai import refine_cards  # noqa: E402
from kaogong.deepseek import load_config  # noqa: E402


def find_article(content_dir: Path, article_id: str) -> Path | None:
    """文章可能被写回它自己的来源日期目录，所以按 id 全局找。"""
    for day in sorted(content_dir.iterdir()):
        if not day.is_dir():
            continue
        candidate = day / f"article-{article_id}.json"
        if candidate.exists():
            return candidate
    return None


def backfill_day(content_dir: Path, day: Path, cfg: dict[str, str]) -> dict:
    picks_path = day / "picks.json"
    if not picks_path.exists():
        return {"day": day.name, "skipped": "no_picks"}
    picks = json.loads(picks_path.read_text(encoding="utf-8"))
    picked = [str(a) for a in picks.get("picked", [])]
    if not picked:
        return {"day": day.name, "skipped": "empty_picks"}

    replaced = 0
    with_explain = 0
    errors = 0
    for article_id in picked:
        path = find_article(content_dir, article_id)
        if path is None:
            errors += 1
            continue
        article = json.loads(path.read_text(encoding="utf-8"))
        old = article.get("aiCards") or []
        if old and all(c.get("explain") for c in old):
            continue  # 已有解析，不重复花钱
        result = refine_cards(article, cfg)
        if "error" in result:
            errors += 1
            continue
        cards = result.get("cards") or []
        if not cards:
            continue
        article["aiCards"] = cards
        path.write_text(json.dumps(article, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        replaced += 1
        with_explain += sum(1 for c in cards if c.get("explain"))
    return {
        "day": day.name,
        "articles": len(picked),
        "replaced": replaced,
        "withExplain": with_explain,
        "errors": errors,
    }


def main() -> int:
    content_dir = ROOT / "content"
    cfg = load_config()
    if not cfg:
        print("✗ 未找到 DEEPSEEK_API_KEY（应放在仓库根 .env.local）")
        return 1
    targets = sys.argv[1:]
    days = [
        d for d in sorted(content_dir.iterdir())
        if d.is_dir() and d.name[:4].isdigit() and (not targets or d.name in targets)
    ]
    total = 0
    for day in days:
        report = backfill_day(content_dir, day, cfg)
        print(f"  {report}")
        total += report.get("withExplain", 0)
    print(f"\n✓ 共补出 {total} 条解析")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
