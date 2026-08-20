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
