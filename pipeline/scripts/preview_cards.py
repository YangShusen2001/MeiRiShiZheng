# -*- coding: utf-8 -*-
"""卡片提炼预览：对指定文章跑 refine_cards，输出完整卡片与出处段落（不写入 content/）。

用法（Windows）：
    cd pipeline && .venv\\Scripts\\python scripts\\preview_cards.py            # 默认三类各一篇
    .venv\\Scripts\\python scripts\\preview_cards.py --date 2026-08-19 --ids 8ebcee6770,a3dfb71c06
    .venv\\Scripts\\python scripts\\preview_cards.py --out ..\\docs\\preview.json  # 落盘 JSON 便于审阅

密钥：DEEPSEEK_API_KEY 环境变量（审核台 bat 会把 .env.local 注入环境），或 --env ..\\.env.local 直接读。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaogong.deepseek import DEFAULT_MODEL  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# 默认样例：file / essay / standard 三类各一篇（仓库示例内容 2026-08-19/20）
DEFAULT_PICKS = [
    ("2026-08-19", "8ebcee6770"),
    ("2026-08-19", "a3dfb71c06"),
    ("2026-08-20", "21ab8176c1"),
]


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().rstrip("\r")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="", help="文章日期目录（有多篇时配合 --ids）")
    parser.add_argument("--ids", default="", help="文章短 id，逗号分隔")
    parser.add_argument("--env", default=str(REPO / ".env.local"), help=".env.local 路径")
    parser.add_argument("--out", default="", help="另存 JSON 到该路径")
    args = parser.parse_args()

    env = load_env(Path(args.env))
    key = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("未找到 DEEPSEEK_API_KEY（环境变量或 --env 文件）")
        return 1
    cfg = {"deepseek_api_key": key, "deepseek_model": env.get("DEEPSEEK_MODEL", DEFAULT_MODEL)}

    from kaogong.card_ai import refine_cards, route_card_variant

    picks = []
    for date, aid in DEFAULT_PICKS if not args.date else zip(args.date.split(","), args.ids.split(",")):
        picks.append((date.strip(), aid.strip()))

    report: dict = {"model": cfg["deepseek_model"], "articles": []}
    for date, aid in picks:
        path = REPO / "content" / date / f"article-{aid}.json"
        if not path.exists():
            print(f"[跳过] 找不到 {path}")
            continue
        article = json.loads(path.read_text(encoding="utf-8"))
        variant = route_card_variant(article.get("title", ""), article.get("source", ""))
        result = refine_cards(article, cfg)
        entry = {"date": date, "id": aid, "title": article.get("title"), "source": article.get("source"),
                 "variant": variant}
        if "error" in result:
            entry["error"] = result["error"]
            print(f"===== [{variant}] {article.get('title')} → ERROR {result['error']}")
        else:
            cards = []
            for card in result["cards"]:
                para = (article.get("paragraphs") or [])[card["anchor"]["paragraphIndex"]]
                cards.append({**card, "anchorParagraph": para})
                print(f"===== [{variant}] {article.get('title')}")
                print(f"  Q: {card['question']}")
                print(f"  A: {card['answer']}")
                print(f"  T: {card['tags']} | 锚定段落 {card['anchor']['paragraphIndex']}: {para[:40]}…")
            entry["cards"] = cards
        report["articles"].append(entry)

    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[已落盘] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
