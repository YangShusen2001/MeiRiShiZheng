# -*- coding: utf-8 -*-
import json

import pytest

from kaogong.article_ai import _locate, analyze_article, source_text_hash, validate_article_ai


def _article():
    return {
        "id": "a1", "date": "2026-08-14", "title": "发展文章", "source": "测试",
        "url": "https://example.com", "pubDate": "", "fetchedAt": "2026-08-14T00:00:00+00:00",
        "status": "ok", "paragraphs": [
            "高质量发展是全面建设社会主义现代化国家的首要任务。",
            "新质生产力以科技创新为主导，能够推动产业结构优化升级。",
        ], "keySentences": [],
    }


SUMMARY = "文章围绕高质量发展和新质生产力展开，阐明科技创新对产业结构优化升级的重要作用，强调以创新驱动增强发展动能，为申论积累发展理念、创新路径和政策表达提供了清晰可靠的时政材料。"


def test_analyze_article_locates_annotations_and_hash():
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "高质量发展", "type": "viewpoint"},
        {"paragraphIndex": 1, "text": "新质生产力", "type": "term", "explanation": "以科技创新为主导并符合高质量发展要求的先进生产力形态，体现新的发展动能。"},
    ]}
    result = analyze_article(_article(), {"deepseek_api_key": "k"}, call=lambda *a, **k: json.dumps(payload, ensure_ascii=False))
    assert result["aiStatus"] == "ok"
    assert result["aiAnnotations"][0]["start"] == 0
    assert result["aiAnnotations"][1]["explanation"]
    assert result["sourceTextHash"] == source_text_hash(result["paragraphs"])
    assert validate_article_ai(result) == []


def test_analyze_article_discards_unlocatable_annotation():
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "原文中不存在", "type": "exam_point"},
    ]}
    result = analyze_article(_article(), {"deepseek_api_key": "k"}, call=lambda *a, **k: json.dumps(payload, ensure_ascii=False))
    assert result["aiStatus"] == "ok"
    assert result["aiAnnotations"] == []
    assert result["aiQuality"]["locationErrors"] == 1


def test_analyze_article_failure_preserves_original():
    article = _article()
    result = analyze_article(article, {}, call=lambda *a, **k: "")
    assert result["aiStatus"] == "error"
    assert result["paragraphs"] == article["paragraphs"]
    assert result["aiAnnotations"] == []
    assert result["aiError"] == "ai_config:missing_api_key"


def test_summary_outside_target_retries():
    calls = iter([
        json.dumps({"summary": "太短", "annotations": []}, ensure_ascii=False),
        json.dumps({"summary": SUMMARY, "annotations": []}, ensure_ascii=False),
    ])
    result = analyze_article(_article(), {"deepseek_api_key": "k"}, call=lambda *a, **k: next(calls))
    assert result["aiStatus"] == "ok"
    assert result["aiSummary"] == SUMMARY


def test_offsets_use_browser_utf16_units():
    article = _article()
    article["paragraphs"] = ["😀前缀后的高质量发展值得关注。"]
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "高质量发展", "type": "viewpoint"},
    ]}
    result = analyze_article(article, {"deepseek_api_key": "k"}, call=lambda *a, **k: json.dumps(payload, ensure_ascii=False))
    assert result["aiAnnotations"][0]["start"] == 6
    assert validate_article_ai(result) == []


def test_offsets_count_each_astral_character_as_two_utf16_units():
    # Given: two astral characters precede a model-selected snippet.
    article = _article()
    article["paragraphs"] = ["😀𠮷前缀高质量发展值得关注。"]
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "高质量发展", "type": "viewpoint"},
    ]}

    # When: the model result is converted to browser offsets.
    result = analyze_article(
        article,
        {"deepseek_api_key": "test-key"},
        call=lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False),
    )

    # Then: both astral characters contribute two UTF-16 code units.
    assert result["aiAnnotations"][0]["start"] == 6
    assert result["aiAnnotations"][0]["end"] == 11
    assert validate_article_ai(result) == []


def test_semantic_validation_rejects_duplicate_annotation_ids():
    # Given: two otherwise valid annotations share an ID.
    article = _article()
    article.update({
        "sourceTextHash": source_text_hash(article["paragraphs"]),
        "aiAnnotations": [
            {"id": "duplicate", "paragraphIndex": 0, "start": 0, "end": 5,
             "text": "高质量发展", "type": "viewpoint"},
            {"id": "duplicate", "paragraphIndex": 1, "start": 0, "end": 5,
             "text": "新质生产力", "type": "term"},
        ],
    })

    # When: semantic validation runs.
    errors = validate_article_ai(article)

    # Then: the duplicate ID is machine distinguishable.
    assert errors == ["annotation_id_duplicate"]


@pytest.mark.parametrize(("kind", "count"), [("viewpoint", 6), ("exam_point", 9), ("term", 6)])
def test_semantic_validation_rejects_annotation_type_above_maximum(kind, count):
    # Given: otherwise valid annotations exceed the publication maximum for one type.
    article = _article()
    article["paragraphs"] = ["高质量发展"]
    article.update({
        "sourceTextHash": source_text_hash(article["paragraphs"]),
        "aiAnnotations": [
            {
                "id": f"{kind}-{index}", "paragraphIndex": 0,
                "start": 0, "end": 5, "text": "高质量发展", "type": kind,
            }
            for index in range(count)
        ],
    })

    # When: semantic validation checks annotation volume.
    errors = validate_article_ai(article)

    # Then: the excessive type is rejected without imposing a nonzero minimum.
    assert errors == [f"annotation_count_{kind}"]


def test_semantic_validation_accepts_legacy_density_from_before_tightening():
    # Given: an article generated under the pre-tightening limits (viewpoint 5,
    # exam_point 8, term 5) — content/ holds 189 such files across 6 dates.
    article = _article()
    article["paragraphs"] = ["高质量发展"]
    article.update({
        "sourceTextHash": source_text_hash(article["paragraphs"]),
        "aiAnnotations": [
            {"id": f"{kind}-{index}", "paragraphIndex": 0, "start": 0, "end": 5,
             "text": "高质量发展", "type": kind}
            for kind, count in (("viewpoint", 5), ("exam_point", 8), ("term", 5))
            for index in range(count)
        ],
    })

    # When: semantic validation runs.
    errors = validate_article_ai(article)

    # Then: legacy density stays valid. The validation bound must not be lowered
    # with the generation caps — quality_gate fails a date when semanticErrors is
    # non-empty (pipeline.py), which would retroactively fail those 6 dates.
    assert errors == []


def test_generation_maxima_stay_within_validation_bound():
    # Given: the two density constants answer different questions (what to produce
    # vs. what to accept on disk), so they must never be collapsed into one.
    from kaogong.article_ai import (
        ANNOTATION_GENERATION_MAXIMA,
        ANNOTATION_MAXIMA,
        ANNOTATION_PER_PARAGRAPH_MAX,
        ANNOTATION_TOTAL_MAX,
    )

    # Then: generation caps are stricter per type, and the whole-article cap is
    # tighter than the sum of per-type caps (otherwise it would never bind).
    assert set(ANNOTATION_GENERATION_MAXIMA) == set(ANNOTATION_MAXIMA)
    for kind, generation_max in ANNOTATION_GENERATION_MAXIMA.items():
        assert 0 < generation_max <= ANNOTATION_MAXIMA[kind], kind
    assert ANNOTATION_TOTAL_MAX <= sum(ANNOTATION_GENERATION_MAXIMA.values())
    assert ANNOTATION_PER_PARAGRAPH_MAX >= 1


def test_semantic_validation_allows_zero_annotations():
    # Given: a successful AI article has no locatable annotations.
    article = _article()
    article.update({
        "sourceTextHash": source_text_hash(article["paragraphs"]),
        "aiAnnotations": [],
    })

    # When: semantic validation runs.
    errors = validate_article_ai(article)

    # Then: zero is allowed because publication defines maxima, not arbitrary minima.
    assert errors == []


def test_semantic_validation_rejects_offsets_inside_astral_surrogate_pair():
    # Given: browser offsets split the two UTF-16 units of an astral character.
    article = _article()
    article["paragraphs"] = ["😀高质量发展"]
    article.update({
        "sourceTextHash": source_text_hash(article["paragraphs"]),
        "aiAnnotations": [
            {"id": "split-surrogate", "paragraphIndex": 0, "start": 1, "end": 2,
             "text": "😀", "type": "term"},
        ],
    })

    # When: semantic validation checks the browser range.
    errors = validate_article_ai(article)

    # Then: malformed UTF-16 boundaries are diagnostic, not an uncaught decoder error.
    assert errors == ["offset_invalid"]


def test_analyze_article_uses_first_occurrence_of_non_unique_snippet():
    # Given: the requested snippet occurs twice in its paragraph.
    article = _article()
    article["paragraphs"] = ["高质量发展需要统筹，高质量发展也需要创新。"]
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "高质量发展", "type": "viewpoint"},
    ]}

    # When: the annotation is located.
    result = analyze_article(
        article,
        {"deepseek_api_key": "test-key"},
        call=lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False),
    )

    # Then: 非唯一片段取首个，不再整条丢弃（减少定位失败）。
    assert result["aiStatus"] == "ok"
    assert [a["text"] for a in result["aiAnnotations"]] == ["高质量发展"]
    assert result["aiAnnotations"][0]["start"] == 0
    assert result["aiAnnotations"][0]["end"] == 5
    assert result["aiQuality"] == {"locationErrors": 0}


def test_locate_folds_whitespace():
    paragraph = "高质量发展 是首要任务。"
    start, end, matched = _locate(paragraph, "高质量发展   是")
    assert matched == "高质量发展 是"
    assert paragraph[start:start + len(matched)] == matched
    assert end - start == len(matched)  # 全 BMP，UTF-16 长度等于 code point 长度


def test_analyze_article_truncates_annotation_over_maximum():
    article = _article()
    article["paragraphs"] = ["高质量发展、新质生产力、科技创新、改革开放、乡村振兴、共同富裕、生态文明、数字经济、法治建设、基层治理。"]
    keywords = ["高质量发展", "新质生产力", "科技创新", "改革开放", "乡村振兴", "共同富裕", "生态文明", "数字经济", "法治建设", "基层治理"]
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": k, "type": "exam_point"} for k in keywords
    ]}

    result = analyze_article(article, {"deepseek_api_key": "k"}, call=lambda *a, **k: json.dumps(payload, ensure_ascii=False))

    # Then: 三层截断 —— 每类上限(exam_point=5) + 每段上限(2)：同段的 10 个考点只保留前 2 个。
    assert result["aiStatus"] == "ok"
    assert len(result["aiAnnotations"]) == 2
    assert [a["text"] for a in result["aiAnnotations"]] == keywords[:2]


def test_summary_length_correction_retry():
    calls = iter([
        json.dumps({"summary": "太短", "annotations": []}, ensure_ascii=False),
        json.dumps({"summary": "也很短", "annotations": []}, ensure_ascii=False),
        json.dumps({"summary": SUMMARY, "annotations": []}, ensure_ascii=False),
    ])

    result = analyze_article(_article(), {"deepseek_api_key": "k"}, call=lambda *a, **k: next(calls))

    # Then: 前两次都超范围时，带具体长度错误纠错重试一次。
    assert result["aiStatus"] == "ok"
    assert result["aiSummary"] == SUMMARY


def test_analyze_article_rejects_invalid_model_shape_without_leaking_payload():
    # Given: malformed model JSON containing article-like sensitive text.
    sensitive = "SECRET-ARTICLE-BODY"
    raw = json.dumps({"summary": SUMMARY, "annotations": sensitive}, ensure_ascii=False)
    article = _article()

    # When: the model response is parsed.
    result = analyze_article(
        article,
        {"deepseek_api_key": "test-key"},
        call=lambda *args, **kwargs: raw,
    )

    # Then: original content survives and the diagnostic is bounded and structural.
    assert result["aiStatus"] == "error"
    assert result["paragraphs"] == article["paragraphs"]
    assert result["aiAnnotations"] == []
    assert result["aiError"] == "ai_schema:annotations_not_array"
    assert sensitive not in result["aiError"]


def test_analyze_article_classifies_invalid_json_as_parse_failure():
    # Given: a provider response that is not JSON.
    article = _article()

    # When: analysis consumes the response.
    result = analyze_article(
        article,
        {"deepseek_api_key": "test-key"},
        call=lambda *args, **kwargs: "not-json SECRET-ARTICLE-BODY",
    )

    # Then: no response content is copied into the published failure field.
    assert result["aiStatus"] == "error"
    assert result["aiError"] == "ai_parse:json_object_missing"


def test_analyze_article_fails_when_annotation_schema_fields_are_missing():
    # Given: an annotation omits a required machine-consumed field.
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "高质量发展"},
    ]}

    # When: analysis parses the model boundary.
    result = analyze_article(
        _article(),
        {"deepseek_api_key": "test-key"},
        call=lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False),
    )

    # Then: schema failure degrades the article rather than silently dropping data.
    assert result["aiStatus"] == "error"
    assert result["aiError"] == "ai_schema:annotation_field_not_string"



def test_analyze_article_upgrade_clears_stale_ai_error():
    # 从 error 补跑到 ok 时，旧失败原因不能残留（否则违反 schema 的 not: required aiError）
    article = _article() | {"aiStatus": "error", "aiError": "ai_config:missing_api_key"}
    payload = {"summary": SUMMARY, "annotations": []}
    result = analyze_article(article, {"deepseek_api_key": "k"}, call=lambda *a, **k: json.dumps(payload, ensure_ascii=False))
    assert result["aiStatus"] == "ok"
    assert "aiError" not in result


def test_normalize_article_decodes_entities_and_relocates_offsets():
    from kaogong.article_ai import normalize_article

    raw_para = "&emsp;&emsp;今天进行二十届中央政治局第二十五次集体学习。"
    article = _article() | {
        "aiStatus": "ok",
        "paragraphs": [raw_para],
        "aiSummary": "摘要",
        "aiAnnotations": [{
            "id": "ai-0", "paragraphIndex": 0, "start": 13, "end": 17,
            "text": "今天进行", "type": "viewpoint",
        }],
        "aiModel": "deepseek-chat", "aiPromptVersion": "article-analysis-v1",
        "aiGeneratedAt": "2026-08-14T00:00:00+00:00",
        "sourceTextHash": "a" * 64, "aiQuality": {"locationErrors": 0},
        "aiError": "ai_config:missing_api_key",
    }
    out = normalize_article(article)
    assert out["paragraphs"][0] == "今天进行二十届中央政治局第二十五次集体学习。"
    assert out["aiAnnotations"][0]["start"] == 0
    assert out["aiAnnotations"][0]["end"] == 4
    assert "aiError" not in out
    assert out["aiQuality"]["locationErrors"] == 0
    assert out["sourceTextHash"] != "a" * 64
    assert validate_article_ai(out) == []


def test_normalize_article_drops_unlocatable_annotation_after_clean():
    from kaogong.article_ai import normalize_article

    article = _article() | {
        "paragraphs": ["&nbsp;高质量发展是首要任务。"],
        "aiStatus": "ok",
        "aiAnnotations": [{
            "id": "ai-0", "paragraphIndex": 0, "start": 6, "end": 12,
            "text": "不存在的内容", "type": "term",
        }],
        "aiQuality": {"locationErrors": 0},
    }
    out = normalize_article(article)
    assert out["aiAnnotations"] == []
    assert out["aiQuality"]["locationErrors"] == 1
    assert out["paragraphs"][0] == "高质量发展是首要任务。"

def test_analyze_article_fails_when_annotation_type_is_unknown():
    # Given: a structurally complete annotation uses an unsupported type.
    payload = {"summary": SUMMARY, "annotations": [
        {"paragraphIndex": 0, "text": "高质量发展", "type": "unknown"},
    ]}

    # When: analysis parses the model boundary.
    result = analyze_article(
        _article(),
        {"deepseek_api_key": "test-key"},
        call=lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False),
    )

    # Then: an enum violation is reported as schema failure, not location failure.
    assert result["aiStatus"] == "error"
    assert result["aiError"] == "ai_schema:annotation_type_invalid"
