# -*- coding: utf-8 -*-
"""关系标注（箭头）：校验/上限/锁定防覆盖。"""
import json

from kaogong.relation_ai import enforce_locks, generate_relations, validate_relations

PARAGRAPHS = [
    "商家是第一责任主体，骑手与消费者均享有双向拒收权。",
    "配送员有权拒绝配送，消费者有权拒收。",
]
ANNOTATIONS = [
    {"id": "ai-0-0-13-viewpoint", "paragraphIndex": 0, "start": 0, "end": 13, "text": "商家是第一责任主体，骑手与消费者均享有双向拒收权", "type": "viewpoint"},
    {"id": "ai-1-0-15-exam_point", "paragraphIndex": 1, "start": 0, "end": 15, "text": "配送员有权拒绝配送，消费者有权拒收", "type": "exam_point"},
    {"id": "ai-1-15-20-term", "paragraphIndex": 1, "start": 15, "end": 20, "text": "双向拒收权", "type": "term"},
]


def _rel(anchor="ai-0-0-13-viewpoint", para=0, points=None, kind="support"):
    return {
        "paragraphIndex": para,
        "anchor": anchor,
        "points": points or [{"annotationId": "ai-1-0-15-exam_point", "kind": "support"}],
        "kind": kind,
    }


def test_validate_relations_accepts_cross_paragraph_points():
    # 支撑点允许跨段（真实总分结构常跨段）：中心句段 0，论据段 1 → 接受
    valid, dropped = validate_relations([_rel()], ANNOTATIONS, PARAGRAPHS)
    assert dropped == 0
    assert valid[0]["id"] == "rel-0-ai-0-0-13-viewpoint"


def test_validate_relations_rejects_anchor_mismatch_paragraph():
    bad = _rel(para=1)  # anchor 在段 0 却声明关系主段 1 → 拒绝
    valid, dropped = validate_relations([bad], ANNOTATIONS, PARAGRAPHS)
    assert (valid, dropped) == ([], 1)


def test_validate_relations_rejects_unknown_anchor_and_center_limit():
    valid, dropped = validate_relations([_rel(anchor="nope")], ANNOTATIONS, PARAGRAPHS)
    assert (valid, dropped) == ([], 1)
    # 同一段两个中心 → 第二个丢
    second = _rel(points=[{"annotationId": "ai-1-0-15-exam_point", "kind": "support"}], para=0, anchor="ai-0-0-13-viewpoint")
    valid, dropped = validate_relations([_rel(), second], ANNOTATIONS, PARAGRAPHS)
    assert len(valid) == 1 and dropped == 1


def test_validate_relations_rejects_term_as_anchor():
    bad = _rel(anchor="ai-1-15-20-term", para=1)
    valid, dropped = validate_relations([bad], ANNOTATIONS, PARAGRAPHS)
    assert (valid, dropped) == ([], 1)


def test_enforce_locks_keeps_edited_across_rerun():
    generated_at = "2026-08-22T08:00:00+00:00"
    edited = {
        "id": "rel-0-ai-0-0-13-viewpoint", "paragraphIndex": 0,
        "anchor": "ai-0-0-13-viewpoint",
        "points": [{"annotationId": "ai-1-0-15-exam_point", "kind": "explain"}],
        "kind": "explain", "aiGenerated": True,
        "editedAt": "2026-08-22T09:00:00+00:00", "editedBy": "owner",
    }
    generated = [{"id": "rel-0-ai-0-0-13-viewpoint", "paragraphIndex": 0, "anchor": "ai-0-0-13-viewpoint",
                  "points": [{"annotationId": "ai-1-0-15-exam_point", "kind": "support"}], "kind": "support"}]
    merged = enforce_locks([edited], generated, generated_at)
    assert merged[0]["kind"] == "explain"  # 人工版保留，不被重跑覆盖
    assert merged[0]["editedBy"] == "owner"


def test_enforce_locks_replaces_non_edited():
    generated_at = "2026-08-22T08:00:00+00:00"
    existing = [{"id": "rel-0-ai-0-0-13-viewpoint", "paragraphIndex": 0, "anchor": "ai-0-0-13-viewpoint",
                 "points": [], "kind": "support", "aiGenerated": True}]
    merged = enforce_locks(existing, generated_at and [
        {"id": "rel-0-ai-0-0-13-viewpoint", "paragraphIndex": 0, "anchor": "ai-0-0-13-viewpoint",
         "points": [{"annotationId": "ai-1-0-15-exam_point", "kind": "support"}], "kind": "support"}], generated_at)
    assert len(merged) == 1 and merged[0]["aiGenerated"] is True


def _payload(relations):
    return json.dumps({"relations": relations}, ensure_ascii=False)


def test_generate_relations_end_to_end():
    article = {"id": "a1", "title": "外卖新规", "paragraphs": PARAGRAPHS, "aiAnnotations": ANNOTATIONS,
               "aiGeneratedAt": "2026-08-22T08:00:00+00:00"}
    result = generate_relations(article, {"deepseek_api_key": "k"}, call=lambda *a, **kw: _payload([
        {"paragraphIndex": 0, "anchor": "ai-0-0-13-viewpoint",
         "points": [{"annotationId": "ai-1-0-15-exam_point", "kind": "support"}], "kind": "support"},
    ]))
    assert result["relations"] and result["relations"][0]["aiGenerated"] is True


def test_generate_relations_without_key_or_annotations():
    article = {"id": "a1", "title": "t", "paragraphs": PARAGRAPHS, "aiAnnotations": [], "aiGeneratedAt": ""}
    assert generate_relations(article, {})["error"] == "ai_config:missing_api_key"
    assert generate_relations(article, {"deepseek_api_key": "k"})["error"] == "ai_relations:no_annotations"
