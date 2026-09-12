# -*- coding: utf-8 -*-
"""考点卡片 AI 提炼：模板路由（A 通用 / B 文件类 / C 评论类）+ 程序校验锚定与每日上限。

规则见 docs/product/card-refinement-rules.md（2026-08-22 拍板：默认 A + 类型路由 B/C；
每日有效新卡 ≤5 张）。AI 出 JSON 意图，程序负责字段校验与原文锚定定位。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from .article_ai import _locate
from .deepseek import DEFAULT_MODEL, chat

PROMPT_VERSION = "card-refinement-v1"

# 每篇文章的卡数上限（规则文档：0-8）
CARD_MAXIMA = 8
# 每日有效新卡上限（用户 2026-08-22 拍板：沿用 0021 的每日新卡 ≤5）
DAILY_NEW_CARD_LIMIT = 5

# 模板路由：文件类 / 评论类关键词（纯规则判定，AI 不参与选模板）
FILE_HINTS = ("规划", "意见", "通知", "报告", "方案", "批复", "决定", "办法", "条例", "纲要")
ESSAY_HINTS = ("评论", "时评", "网评", "社评", "点评", "解读", "观察", "社论")
ESSAY_SOURCES = ("南方时评", "人民网评", "半月谈评论", "金台锐评", "学习时报")

VARIANT_FALLBACK = "standard"
VARIANT_FILE = "file"
VARIANT_ESSAY = "essay"

# 与 docs/product/card-refinement-rules.md 的模板文本保持一致；词句改动需同步文档。
_BASE_RULES = (
    "你是公务员考试的时政内容编辑。只返回 JSON，不得返回 Markdown/HTML。"
    "任务：从给定文章提炼「必记考点卡片」。必须满足："
    "1. 原子：一张卡只考一个考点（一问一答），禁止把多个考点揉进一个问题。"
    "2. 硬考点：官方明确定位、原则、目标、提法、结构、任务；禁止开放论述题。"
    "3. 表述忠实：问题与答案只能使用文章中的事实/数字/官方表述，不得补充文章外信息。"
    "4. 可锚定：anchor.sentence 必须是文章某自然段的原文连续子串（可跨分句，不可跨段），"
    "程序会逐字定位，定位失败整卡作废。"
    "5. 数量：3-8 张。宁缺毋滥，没有足够硬考点时可少于 3 张。"
    "6. 标签：tags 1-5 个，从「定位/原则/目标/数字/任务/术语/要求/意义」中选，可加一个自定义词（不超过 3 字）。"
    "7. 纯数字/指标（增速、总额、覆盖率、时间节点、具体数值）不出卡——它们将由 AI 标注在原文中高亮标记；"
    "卡片只出结构、任务、定位、原则类考点。结构性提法（如「两个同步」「十五五」定位）允许成卡。"
    "8. explain：用 40-120 字说明**为什么这个答案对、最容易混的说法错在哪**，"
    "依据必须能在原文里找到；写不出有依据的解释就不要硬编。"
    "黄金样本：question「十五五」时期的官方定位是什么？"
    "answer 基本实现社会主义现代化「夯实基础、全面发力」的关键时期，具有承前启后的重要地位。"
    "tags 定位,关键时期"
)

_FILE_EXTRA = (
    "本文为政策文件/规划/报告，追加硬约束："
    "1. 考点优先级：结构性与目标性提法（如「两个同步」「到 2030 年建成……体系」）> 任务清单 > 原则/要求。"
    "2. 含「新增/首次/达到/突破」等强记忆词的结构性表述优先成卡（其后的具体数值仍标注在原文，不出卡）。"
    "3. 卡数目标 3-5 张：文件类考点应当充足；文章含明确目标/结构提法且未成卡时，应先补结构/目标卡再收尾。"
)

_ESSAY_EXTRA = (
    "本文为评论/解读/时评，追加硬约束："
    "1. 重点提炼「可直接用于申论写作的规范表述」，而非新闻事实；判断标准：考生能否直接引用/化用。"
    "2. 表达卡格式：question 问「如何表述某观点/某关系」，answer 给出原文中最凝练的一句（≤2 句拼接，中间用「；」）。"
    "3. 禁止提炼「作者态度」之类主观卡。"
    "4. 文章的 keySentences 若出现在下方原文中，必须优先成卡。"
)

_VARIANT_RULES = {
    VARIANT_FILE: _BASE_RULES + _FILE_EXTRA,
    VARIANT_ESSAY: _BASE_RULES + _ESSAY_EXTRA,
    VARIANT_FALLBACK: _BASE_RULES,
}


class RawCard(TypedDict, total=False):
    question: str
    answer: str
    tags: list[str]
    anchor: dict


class RefineResult(TypedDict, total=False):
    cards: list[dict]
    error: str


def route_card_variant(title: str, source: str, *, key_sentences: list[str] | None = None) -> str:
    """按规则路由模板；esay 优先于 file（评论标题常含「解读」等字样，不误判）。"""
    del key_sentences  # 预留：未来可用金句数量参与判定
    if any(hint in title for hint in ESSAY_HINTS) or any(src in source for src in ESSAY_SOURCES):
        return VARIANT_ESSAY
    if any(hint in title for hint in FILE_HINTS):
        return VARIANT_FILE
    return VARIANT_FALLBACK


def _json_object(raw: str) -> dict:
    text = _strip_fence(raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    import json

    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _strip_fence(text: str) -> str:
    import re

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    return text


def _focus_note(article: dict, pages: list[str]) -> str:
    """T05：文章带 aiFocus（T04 段落聚焦标注）时，把出题范围收到重点段。

    aiFocus 语义（article_ai v2）：整篇价值集中在若干段（如「最后三段才是
    政策阐释」，其余是背景/导语）时标注的段落闭区间。此处收紧卡片 anchor：
    越界即抛给模型的不变量，但不硬过滤——AI 若在范围外给出可锚定的合法考点，
    仍是有价值的内容（软引导，避免误杀）。
    """
    focus = article.get("aiFocus")
    if not isinstance(focus, dict):
        return ""
    try:
        lo, hi = int(focus["from"]), int(focus["to"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not (0 <= lo <= hi < len(pages)) or hi - lo + 1 >= len(pages):
        return ""  # 非法或与全文等价（无收缩价值）→ 不注入
    return (
        f"本文重点段落在 [{lo}]-[{hi}]（其余段落为背景/导语），"
        f"卡片 anchor.paragraphIndex 必须落在此范围内。\n"
    )


def _messages(
    title: str,
    paragraphs: list[str],
    *,
    variant: str,
    policy_line: str = "",
    existing_notes: str = "",
    focus_note: str = "",
) -> list[dict[str, str]]:
    article = "\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs))
    output_shape = (
        f"输出形状：{{\"cards\":[{{\"question\":\"...\",\"answer\":\"...\",\"tags\":[\"...\"],"
        f"\"explain\":\"为什么是这个答案、其他说法错在哪（40~120 字，依据原文）\","
        f"\"anchor\":{{\"paragraphIndex\":0,\"sentence\":\"原文连续子串\"}}}}]}}"
    )
    rules = _VARIANT_RULES.get(variant, _VARIANT_RULES[VARIANT_FALLBACK])
    notes = existing_notes or ""
    return [
        {"role": "system", "content": rules},
        {"role": "user", "content": (
            f"{output_shape}\n"
            + (f"标题：{title}\n")
            + (f"所属主线：{policy_line}\n" if policy_line else "")
            + (focus_note)
            + (notes)
            + f"原文（段落已编号，[n] 为段落下标）：\n{article}"
        )},
    ]


def _card_id(article_id: str, index: int) -> str:
    return f"card-{article_id}-{index + 1}"


def validate_cards(cards: list[dict], paragraphs: list[str], article_id: str) -> tuple[list[dict], int]:
    """校验并规范化卡片：字段 + 锚定定位；返回 (有效卡列表, 丢弃数)。

    锚定失败/字段非法的单卡丢弃，不整篇作废（与 AI 标注的门禁哲学一致）。
    """
    valid: list[dict] = []
    dropped = 0
    for i, raw in enumerate(cards[:CARD_MAXIMA]):
        try:
            question = str(raw.get("question", "")).strip()
            answer = str(raw.get("answer", "")).strip()
            tags_raw = raw.get("tags")
            anchor = raw.get("anchor")
            if not 10 <= len(question) <= 40:
                raise ValueError("question_length")
            if not 6 <= len(answer) <= 200:
                raise ValueError("answer_length")
            if not isinstance(tags_raw, list) or not 1 <= len(tags_raw) <= 5:
                raise ValueError("tags_count")
            tags = [str(t).strip() for t in tags_raw]
            if not all(tags) or any(len(t) > 12 for t in tags):
                raise ValueError("tags_invalid")
            if not isinstance(anchor, dict):
                raise ValueError("anchor_missing")
            paragraph_index = anchor.get("paragraphIndex")
            sentence = str(anchor.get("sentence", "")).strip()
            if not isinstance(paragraph_index, int) or not 0 <= paragraph_index < len(paragraphs):
                raise ValueError("anchor_paragraph")
            if not sentence:
                raise ValueError("anchor_sentence")
            _locate(paragraphs[paragraph_index], sentence)  # 定位失败抛 ValueError
            card = {
                "id": _card_id(article_id, i),
                "question": question,
                "answer": answer,
                "tags": tags,
                "anchor": {
                    "articleId": article_id,
                    "paragraphIndex": paragraph_index,
                    "sentence": sentence,
                },
            }
            # explain 是**增强而非必需**：缺了或不合规只丢这个字段，不作废整张卡
            # （与管道"降级不阻断"的一贯做法一致；端上没有 explain 时用基础解析兜底）。
            explain = str(raw.get("explain", "")).strip()
            if 10 <= len(explain) <= 400:
                card["explain"] = explain
            valid.append(card)
        except (KeyError, TypeError, ValueError):
            dropped += 1
    return valid, dropped


def refine_cards(
    article: dict,
    cfg: dict[str, str],
    *,
    call: Callable[..., str] = chat,
    attempts: int = 2,
    daily_budget: int = DAILY_NEW_CARD_LIMIT,
) -> RefineResult:
    """为一篇文章提炼考点卡片；失败返回 {error}，不抛异常（与 analyze_article 降级一致）。

    daily_budget：当日剩余新卡额度，超出部分丢弃（每日上限拍板 5 张）。
    """
    pages = list(article.get("paragraphs") or [])
    if not pages:
        return {"error": "ai_cards:no_paragraphs"}
    if not cfg.get("deepseek_api_key"):
        return {"error": "ai_config:missing_api_key"}
    variant = route_card_variant(str(article.get("title", "")), str(article.get("source", "")))
    model = cfg.get("deepseek_model") or DEFAULT_MODEL
    payload: dict | None = None
    for _ in range(attempts):
        payload = _json_object(call(
            _messages(
                str(article.get("title", "")), pages,
                variant=variant, policy_line=str(article.get("policyLine", "")),
                focus_note=_focus_note(article, pages),
            ),
            cfg, max_tokens=1400, temperature=0.2,
        ))
        if isinstance(payload.get("cards"), list):
            break
    if payload is None or not isinstance(payload.get("cards"), list):
        return {"error": "ai_provider:no_output"}
    cards, _dropped = validate_cards(payload["cards"], pages, str(article.get("id", "")))
    if not cards:
        return {"error": "ai_cards:all_dropped"}
    return {"cards": cards[:max(0, daily_budget)]}
