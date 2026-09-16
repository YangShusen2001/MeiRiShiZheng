# -*- coding: utf-8 -*-
"""关系标注（箭头）AI 生成：中心句 → 支撑点，AI 出意图、程序校验引用与上限。

规则见提案 0022 §5：引用已校验标注 id，不新增第二套文本定位；每段中心 ≤1、支撑 ≤5；
人工修正（editedAt 晚于文章 aiGeneratedAt）后重跑不得覆盖（locked）。
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import TypedDict

from .deepseek import Cfg, DEFAULT_MODEL, chat

PROMPT_VERSION = "relation-analysis-v1"

RELATION_KINDS = ("support", "explain", "example", "contrast")
ANCHOR_TYPES = ("viewpoint", "exam_point")  # 中心句：观点/政策句
MAX_CENTERS_PER_PARAGRAPH = 1
MAX_POINTS = 5


class RawRelation(TypedDict, total=False):
    paragraphIndex: int
    anchor: str
    points: list[dict]
    kind: str


def _json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    import json

    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _messages(title: str, paragraphs: list[str], annotations: list[dict]) -> list[dict[str, str]]:
    ann_lines = "\n".join(
        f"- id={a.get('id')} 段{a.get('paragraphIndex')} [{a.get('type')}] {a.get('text')}"
        for a in annotations
    )
    return [
        {"role": "system", "content": (
            "你是公务员考试时政内容编辑。只返回 JSON，不得返回 Markdown/HTML。"
            "任务：找出段落内的「总-分/观点-论据/政策-措施」结构，输出关系标注（箭头）。"
            "只返回 JSON，不得输出其他内容。关系 kind 只能是 support/explain/example/contrast。"
            "anchor 必须在给出的标注 id 中选；若该段没有中心句（观点/政策句），不要强行输出该段。"
        )},
        {"role": "user", "content": (
            "输出形状：{\"relations\":[{\"paragraphIndex\":0,\"anchor\":\"ai-0-..-..-viewpoint\","
            "\"points\":[{\"annotationId\":\"ai-0-..-..-exam_point\",\"kind\":\"support\"}],\"kind\":\"support\"}]}\n"
            f"标题：{title}\n"
            f"标注清单（只能引用这里的 id）：\n{ann_lines}\n"
            f"原文：\n" + "\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs))
        )},
    ]


def validate_relations(
    relations: list[dict],
    annotations: list[dict],
    paragraphs: list[str],
) -> tuple[list[dict], int]:
    """校验并规范化关系标注：引用存在、中心类型、中心段上限、支撑 ≤5。

    支撑点允许跨段（真实总分结构常跨段；箭头 overlay 跨段绘制），
    中心句以 anchor 所属段为关系主段。
    """
    by_id = {a.get("id"): a for a in annotations}
    valid: list[dict] = []
    dropped = 0
    centers_per_para: dict[int, int] = {}
    for raw in relations:
        try:
            paragraph_index = int(raw.get("paragraphIndex", -1))
            anchor_id = str(raw.get("anchor", ""))
            points = raw.get("points") or []
            kind = str(raw.get("kind", ""))
            anchor = by_id.get(anchor_id)
            if not 0 <= paragraph_index < len(paragraphs):
                raise ValueError("paragraph_out_of_range")
            if anchor is None or str(anchor.get("type")) not in ANCHOR_TYPES:
                raise ValueError("anchor_invalid")
            if anchor.get("paragraphIndex") != paragraph_index:
                raise ValueError("anchor_cross_paragraph")
            if kind not in RELATION_KINDS:
                raise ValueError("kind_invalid")
            if centers_per_para.get(paragraph_index, 0) >= MAX_CENTERS_PER_PARAGRAPH:
                raise ValueError("center_limit_exceeded")
            if not 1 <= len(points) <= MAX_POINTS:
                raise ValueError("points_count")
            norm_points = []
            for point in points:
                pid = str(point.get("annotationId", ""))
                pk = str(point.get("kind", ""))
                p_ann = by_id.get(pid)
                if p_ann is None:
                    raise ValueError("point_invalid")
                if pid == anchor_id:
                    raise ValueError("point_duplicates_anchor")
                if pk not in RELATION_KINDS:
                    raise ValueError("point_kind_invalid")
                norm_points.append({"annotationId": pid, "kind": pk})
            centers_per_para[paragraph_index] = centers_per_para.get(paragraph_index, 0) + 1
            valid.append({
                "id": f"rel-{paragraph_index}-{anchor_id}",
                "paragraphIndex": paragraph_index,
                "anchor": anchor_id,
                "points": norm_points,
                "kind": kind,
            })
        except (KeyError, TypeError, ValueError):
            dropped += 1
    return valid, dropped


def enforce_locks(existing: list[dict], generated: list[dict], article_generated_at: str) -> list[dict]:
    """重跑防覆盖：existing 中人工修正过（editedAt > 文章 aiGeneratedAt）的关系保留锁定。

    generated 按 id 对齐合并；非锁定的旧关系被新生成替换；锁定关系不受新生成影响。
    """
    try:
        generated_at = dt.datetime.fromisoformat(article_generated_at)
    except (TypeError, ValueError):
        generated_at = None
    locked = {}
    for rel in existing:
        edited_at = rel.get("editedAt")
        if not edited_at:
            continue
        try:
            edited = dt.datetime.fromisoformat(str(edited_at))
        except (TypeError, ValueError):
            edited = None
        if generated_at is not None and edited is not None and edited > generated_at:
            rel = dict(rel)
            rel["aiGenerated"] = rel.get("aiGenerated", True)
            locked[str(rel.get("id"))] = rel
    merged = []
    for g in generated:
        cur = locked.get(str(g.get("id")))
        if cur is not None:
            merged.append(cur)
        else:
            g = dict(g)
            g["aiGenerated"] = True
            merged.append(g)
    # 锁定但新生成未覆盖的旧关系（模型本次没输出它但仍应保留）
    for rel_id, rel in locked.items():
        if rel_id not in {str(g.get("id")) for g in merged}:
            merged.append(rel)
    return merged


def generate_relations(
    article: dict,
    cfg: Cfg,
    *,
    call: Callable[..., str] = chat,
    attempts: int = 2,
) -> dict:
    """为一篇文章生成关系标注；失败返回 {error}；重跑时保留人工锁定。"""
    if not cfg.get("deepseek_api_key"):
        return {"error": "ai_config:missing_api_key"}
    paragraphs = list(article.get("paragraphs") or [])
    annotations = list(article.get("aiAnnotations") or [])
    if not annotations:
        return {"error": "ai_relations:no_annotations"}
    model = cfg.get("deepseek_model") or DEFAULT_MODEL
    payload: dict | None = None
    raw_list: list | None = None
    for _ in range(attempts):
        payload = _json_object(call(
            _messages(str(article.get("title", "")), paragraphs, annotations),
            cfg, max_tokens=1200, temperature=0.2,
        ))
        raw_list = payload.get("relations")
        if isinstance(raw_list, list):
            break
    if raw_list is None:
        return {"error": "ai_provider:no_output"}
    valid, _dropped = validate_relations(raw_list, annotations, paragraphs)
    generated = enforce_locks(
        list(article.get("aiRelations") or []), valid,
        str(article.get("aiGeneratedAt") or ""),
    )
    return {"relations": generated, "model": model, "aiPromptVersion": PROMPT_VERSION}
