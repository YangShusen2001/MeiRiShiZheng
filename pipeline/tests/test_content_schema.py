# -*- coding: utf-8 -*-
"""契约测试：content/ 下的全部发布内容必须通过 JSON Schema 校验。

这是「管道 ↔ 前端」跨语言边界的机器校验——谁破坏了契约，这里立刻红。
"""
import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

from kaogong.quality import FORMAT_CHECKER, classify_artifact

CONTENT = Path(__file__).resolve().parents[2] / "content"
SCHEMAS = CONTENT / "schema"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_load(SCHEMAS / name), format_checker=FORMAT_CHECKER)


def test_published_content_matches_schema():
    validators = {
        "digest": _validator("digest.schema.json"),
        "article": _validator("article.schema.json"),
        "practice": _validator("practice.schema.json"),
        "summary": _validator("summary.schema.json"),
        "card": _validator("card.schema.json"),
        "picks": _validator("picks.schema.json"),
    }
    published = sorted(
        path
        for directory in CONTENT.iterdir()
        if directory.is_dir() and directory.name != "schema" and not directory.name.startswith("_")
        for path in directory.glob("*.json")
    )
    assert published, "content/ 下应至少有一个发布内容文件"
    for f in published:
        data = _load(f)
        kind = classify_artifact(f)
        assert kind is not None
        validator = validators[kind]
        try:
            validator.validate(data)
        except jsonschema.ValidationError as exc:
            raise AssertionError(f"{f.relative_to(CONTENT)} 未通过 Schema：{exc.message}") from exc


def test_policy_lines_file_matches_schema():
    # policy-lines.json 位于 content/ 根，不在日期目录里，需单独校验。
    schema = _load(SCHEMAS / "policy-lines.schema.json")
    try:
        jsonschema.validate(_load(CONTENT / "policy-lines.json"), schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"policy-lines.json 未通过 Schema：{exc.message}") from exc


def test_card_decks_match_schema():
    # content/cards/ 不在日期目录扫描范围内，单独校验（含新增 policyLine/anchor 字段）。
    schema = _load(SCHEMAS / "card.schema.json")
    for f in sorted((CONTENT / "cards").glob("*.json")):
        try:
            jsonschema.validate(_load(f), schema)
        except jsonschema.ValidationError as exc:
            raise AssertionError(f"{f.name} 未通过 Schema：{exc.message}") from exc


def _strip_defs_locations(value):
    """对比两段 def 定义时忽略描述文案差异，只比形状与约束。"""
    if isinstance(value, dict):
        return {k: _strip_defs_locations(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [_strip_defs_locations(v) for v in value]
    return value


def test_article_ai_card_def_matches_card_schema():
    # article.schema.json 的 aiCard 与 card.schema.json 的 card 必须形状一致（跨文件漂移保护）。
    article_def = _load(SCHEMAS / "article.schema.json")["$defs"]["aiCard"]
    card_def = _load(SCHEMAS / "card.schema.json")["$defs"]["card"]
    assert _strip_defs_locations(article_def) == _strip_defs_locations(card_def)


def test_ai_cards_contract_accepts_valid_and_rejects_invalid():
    schema = _load(SCHEMAS / "article.schema.json")
    article = _article_with_ai()
    article["aiCards"] = [{
        "id": "card-ai-contract-1",
        "question": "2026 年经济增长预期目标是多少？",
        "answer": "4.5%—5%，在实际工作中努力争取更好结果。",
        "tags": ["数字"],
        "anchor": {"articleId": "ai-contract", "paragraphIndex": 0, "sentence": "高质量发展是全面建设社会主义现代化国家的首要任务。"},
    }]
    jsonschema.validate(article, schema)
    bad = json.loads(json.dumps(article))
    bad["aiCards"][0]["tags"] = []
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def _relations_included(article: dict) -> dict:
    article = dict(article)
    article["aiRelations"] = [
        {
            "id": "rel-1", "paragraphIndex": 0,
            "anchor": "ann-1",
            "points": [{"annotationId": "ann-2", "kind": "support"}],
            "kind": "support", "aiGenerated": True,
        },
    ]
    return article


def test_ai_relations_contract_accepts_valid_and_edited():
    schema = _load(SCHEMAS / "article.schema.json")
    jsonschema.validate(_relations_included(_article_with_ai()), schema)
    edited = _relations_included(_article_with_ai())
    edited["aiRelations"][0]["aiGenerated"] = False
    edited["aiRelations"][0]["editedAt"] = "2026-08-14T09:00:00+00:00"
    edited["aiRelations"][0]["editedBy"] = "owner"
    jsonschema.validate(edited, schema)


@pytest.mark.parametrize(
    "relations",
    [
        [{"id": "rel-1", "paragraphIndex": 0, "anchor": "ann-1",
          "points": [{"annotationId": "ann-2", "kind": "wrong-kind"}],
          "kind": "support", "aiGenerated": True}],
        [{"id": "rel-1", "paragraphIndex": 0, "anchor": "ann-1",
          "points": [], "kind": "support", "aiGenerated": True}],
        [{"id": "rel-1", "paragraphIndex": 0, "anchor": "",
          "points": [{"annotationId": "ann-2", "kind": "support"}],
          "kind": "support", "aiGenerated": True}],
    ],
)
def test_ai_relations_contract_rejects_invalid(relations):
    schema = _load(SCHEMAS / "article.schema.json")
    article = _relations_included(_article_with_ai())
    article["aiRelations"] = relations
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(article, schema)


def _article_with_ai(**overrides) -> dict:
    article = {
        "id": "ai-contract",
        "date": "2026-08-14",
        "title": "测试文章",
        "source": "测试来源",
        "url": "https://example.com/article",
        "pubDate": "2026-08-14",
        "fetchedAt": "2026-08-14T08:00:00+00:00",
        "status": "ok",
        "paragraphs": ["高质量发展是全面建设社会主义现代化国家的首要任务。新质生产力以科技创新为主导。"],
        "keySentences": [],
        "aiStatus": "ok",
        "aiSummary": "文章围绕高质量发展与科技创新展开，说明培育新质生产力需要强化创新驱动、优化产业结构并提升治理效能，为申论积累发展理念、政策措施和规范表达提供了清晰材料。",
        "aiAnnotations": [
            {
                "id": "ann-1", "paragraphIndex": 0, "start": 0, "end": 6,
                "text": "高质量发展", "type": "viewpoint",
            },
            {
                "id": "ann-2", "paragraphIndex": 0, "start": 28, "end": 33,
                "text": "新质生产力", "type": "term",
                "explanation": "以科技创新为主导，摆脱传统增长路径并符合高质量发展要求的先进生产力形态。",
            },
        ],
        "aiModel": "deepseek-chat",
        "aiPromptVersion": "article-analysis-v1",
        "aiGeneratedAt": "2026-08-14T08:01:00+00:00",
        "sourceTextHash": "a" * 64,
        "aiQuality": {"locationErrors": 0},
    }
    article.update(overrides)
    return article


def test_ai_article_contract_accepts_success_and_error_states():
    schema = _load(SCHEMAS / "article.schema.json")
    jsonschema.validate(_article_with_ai(), schema)
    error = _article_with_ai(
        aiStatus="error",
        aiAnnotations=[],
        aiError="模型响应超时",
    )
    error.pop("aiSummary")
    error.pop("aiQuality")
    jsonschema.validate(error, schema)


@pytest.mark.parametrize(
    "change",
    [
        {"aiSummary": "过短"},
        {"aiAnnotations": [{
            "id": "bad", "paragraphIndex": 0, "start": 0, "end": 1,
            "text": "高", "type": "unknown",
        }]},
        {"aiAnnotations": [{
            "id": "bad", "paragraphIndex": 0, "start": 0, "end": 6,
            "text": "高质量发展", "type": "viewpoint", "explanation": "观点不能带解释",
        }]},
        {"sourceTextHash": "not-a-sha256"},
    ],
)
def test_ai_article_contract_rejects_invalid_output(change):
    schema = _load(SCHEMAS / "article.schema.json")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_article_with_ai(**change), schema)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"title": ""}, "title"),
        ({"date": "2026-02-30"}, "date"),
        ({"fetchedAt": "2026-08-14 08:00:00"}, "fetchedAt"),
        ({"url": "file:///etc/passwd"}, "url"),
        ({"url": "http://localhost/article"}, "url"),
    ],
)
def test_article_contract_rejects_malformed_required_fields(change, field):
    # Given: a required publication field is malformed.
    article = _article_with_ai(**change)

    # When: Draft 2020-12 validation runs with format assertions.
    errors = list(_validator("article.schema.json").iter_errors(article))

    # Then: the malformed field is rejected.
    assert any(field in error.absolute_path for error in errors)


def test_article_contract_preserves_empty_pub_date_exception():
    # Given: legacy source metadata has no publication date.
    article = _article_with_ai(pubDate="")

    # When: the article contract is evaluated.
    errors = list(_validator("article.schema.json").iter_errors(article))

    # Then: the documented empty pubDate exception remains valid.
    assert errors == []


def test_digest_contract_rejects_calendar_invalid_item_date_and_private_url():
    # Given: a digest item has an impossible calendar date and a private source URL.
    digest = {
        "date": "2026-08-14", "title": "日报", "sections": [{
            "id": "national", "title": "全国", "items": [{
                "title": "政策", "date": "02-30", "sourceUrl": "http://127.0.0.1/private",
            }],
        }],
    }

    # When: the digest contract is evaluated.
    errors = list(_validator("digest.schema.json").iter_errors(digest))

    # Then: both malformed fields fail validation.
    assert {error.validator for error in errors} >= {"format"}
    assert len(errors) == 2
