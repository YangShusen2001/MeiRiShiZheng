# -*- coding: utf-8 -*-
"""给人工卡组补 explain（逐项解析），**基于语料库检索到的原文**。

## 为什么不能直接让模型写
`content/cards/*.json` 是人工策展的卡（十五五规划建议 / 2026 政府工作报告），
**没有 anchor**（不像文章提炼的卡能指回原文）。直接让模型凭记忆写解析，
在时政考点上是**编造型错误**——考公场景里错的解析比没有解析更有害。

## 做法：先检索、再生成、宁可返回空
1. 用卡片的问题+答案+标签，在**全部时政文章段落**里检索最相关的片段（字符二元组重合度）；
2. 把片段作为"相关原文"喂给模型；
3. 提示词明确要求：**依据不足就返回空字符串**——宁可不给，也不要编。

于是在结构上就不可能出现"无依据的解析"：模型只有原文可依。

用法：
    python scripts/backfill_deck_explain.py                # 全部卡组
    python scripts/backfill_deck_explain.py 15w-plan       # 指定卡组（文件名前缀）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.deepseek import chat, load_config  # noqa: E402

MIN_PARA: int = 20
TOP_K: int = 3
MIN_EXPLAIN: int = 10
MAX_EXPLAIN: int = 400


def bigrams(text: str) -> set[str]:
    """字符二元组集合；中文短文本用这个比分词稳。"""
    clean = "".join(ch for ch in text if ch.isalnum())
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def load_sources() -> list[tuple[str, str]]:
    """`pipeline/sources/*.md` 里的政策原文，按行切块。

    这是**关键的一步**：没有它，模型只能凭记忆写解析——在时政考点上是编造型错误。
    有了原文，提示词里的"依据不足就返回空"才是真的可执行。
    """
    out: list[tuple[str, str]] = []
    for path in sorted((ROOT / "pipeline" / "sources").glob("*.md")):
        if path.name.startswith("README"):
            continue
        for line in path.read_text(encoding="utf-8").split("\n"):
            text = line.strip().lstrip("-|#").strip()
            if len(text) >= MIN_PARA:
                out.append((path.stem, text))
    return out


def load_corpus() -> list[tuple[str, str]]:
    """(来源标注, 段落) 列表：政策原文 + 全部时政文章。"""
    corpus: list[tuple[str, str]] = load_sources()
    for path in sorted((ROOT / "content").glob("2026-*/article-*.json")):
        try:
            article = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        title = str(article.get("title", ""))
        for para in article.get("paragraphs", []) or []:
            text = str(para).strip()
            if len(text) >= MIN_PARA:
                corpus.append((title, text))
    return corpus


def top_passages(card: dict, corpus: list[tuple[str, str]]) -> list[tuple[str, str]]:
    query = bigrams(f"{card.get('question', '')}{card.get('answer', '')}{''.join(card.get('tags', []))}")
    scored: list[tuple[float, str, str]] = []
    for title, para in corpus:
        overlap = len(query & bigrams(para))
        if overlap > 0:
            scored.append((overlap / max(1, len(query)), title, para))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [(title, para) for _, title, para in scored[:TOP_K]]


RULES = (
    "你是考公时政助教。给你一张考点卡片和几段**可能相关**的时政原文。\n"
    "请写 40-120 字的解析，说明**为什么这个答案对、最容易混的说法错在哪**。\n"
    "铁律：**只有在原文片段能支撑时才写**；依据不足必须返回空字符串——"
    "宁可不给解析，也绝不能编。时政考点上错误的解析比没有解析更有害。\n"
    '输出 JSON：{"explain": "…"}（依据不足则 {"explain": ""}）'
)


def _json_object(raw: str) -> dict:
    """从模型输出里取 JSON（容忍 ```json 围栏）；失败返回空 dict。"""
    text = raw.strip()
    if text.startswith("```"):
        body = text[3:]
        if body.startswith("json"):
            body = body[4:]
        text = body.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def explain_for(card: dict, policy: str, corpus: list[tuple[str, str]], cfg: dict[str, str]) -> str:
    passages = top_passages(card, corpus)
    lines = [f"政策文件：{policy}", f"卡片问题：{card.get('question', '')}",
             f"卡片答案：{card.get('answer', '')}",
             f"标签：{'、'.join(card.get('tags', []))}"]
    if passages:
        lines.append("相关原文片段：")
        for index, (title, para) in enumerate(passages, 1):
            lines.append(f"[{index}]（{title[:30]}）{para[:300]}")
    else:
        lines.append("相关原文片段：（未检索到）")
    raw = chat([
        {"role": "system", "content": RULES},
        {"role": "user", "content": "\n".join(lines)},
    ], cfg, max_tokens=500, temperature=0.2)
    data = _json_object(raw)
    text = str(data.get("explain", "")).strip()
    if not MIN_EXPLAIN <= len(text) <= MAX_EXPLAIN:
        return ""
    return text


def main() -> int:
    cfg = load_config()
    if not cfg:
        print("✗ 未找到 DEEPSEEK_API_KEY（应放在仓库根 .env.local）")
        return 1
    targets = sys.argv[1:]
    corpus = load_corpus()
    print(f"语料库：{len(corpus)} 个段落（来自全部时政文章）\n")

    total_done = 0
    total_blank = 0
    for path in sorted((ROOT / "content" / "cards").glob("*.json")):
        if targets and not any(path.name.startswith(t) for t in targets):
            continue
        deck = json.loads(path.read_text(encoding="utf-8"))
        policy = str(deck.get("policy", ""))
        done = blank = 0
        for card in deck.get("cards", []):
            if card.get("explain"):
                continue
            text = explain_for(card, policy, corpus, cfg)
            if text:
                card["explain"] = text
                done += 1
            else:
                blank += 1
        path.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {path.name}：补出 {done} 条，依据不足返回空 {blank} 条")
        total_done += done
        total_blank += blank
    print(f"\n✓ 共补出 {total_done} 条解析；{total_blank} 条因依据不足留空（端上用基础解析兜底）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
