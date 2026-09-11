# -*- coding: utf-8 -*-
"""考点卡片 AI 提炼：模板路由 / 解析校验 / 锚定定位 / 每日上限。"""
import json

from kaogong.card_ai import (
    CARD_MAXIMA,
    DAILY_NEW_CARD_LIMIT,
    _locate,
    refine_cards,
    route_card_variant,
    validate_cards,
)

PARAGRAPHS = [
    "培育新质生产力需要以科技创新为主导，加快形成先进生产力质态。",
    "「十五五」时期主要目标包括高质量发展、科技自立自强与美丽中国建设。",
    "2026 年经济增长预期目标为 4.5%—5%。",
]


def _article(**overrides):
    article = {
        "id": "a1",
        "title": "关于培育新质生产力的意见",
        "source": "中国政府网",
        "paragraphs": PARAGRAPHS,
        "policyLine": "fifteen-five-plan",
    }
    article.update(overrides)
    return article


def _card(paragraph_index=2, sentence="2026 年经济增长预期目标为 4.5%—5%。"):
    return {
        "question": "2026 年经济增长预期目标是多少？",
        "answer": "4.5%—5%，在实际工作中努力争取更好结果。",
        "tags": ["数字"],
        "anchor": {"paragraphIndex": paragraph_index, "sentence": sentence},
    }


def test_route_card_variant_rules():
    assert route_card_variant("学习时报评论：敬畏历史", "学习时报") == "essay"
    assert route_card_variant("全国统一大市场建设方案", "中国政府网") == "file"
    assert route_card_variant("南方网评：把饭碗端牢", "南方网") == "essay"  # 来源为南方网但标题含「网评」
    assert route_card_variant("南方时评：把饭碗端牢", "南方网") == "essay"
    assert route_card_variant("以旧换新政策观察", "人民日报") == "essay"  # 标题含「观察」
    assert route_card_variant("各省份加快重点项目建设", "新华网") == "standard"


def test_validate_cards_accepts_and_backfills_id():
    cards, dropped = validate_cards([_card()], PARAGRAPHS, "a1")
    assert dropped == 0
    assert cards[0]["id"] == "card-a1-1"
    assert cards[0]["anchor"]["articleId"] == "a1"


def test_validate_cards_drops_unlocatable_anchor():
    bad = _card(sentence="这句话根本不在原文里。")
    cards, dropped = validate_cards([bad], PARAGRAPHS, "a1")
    assert cards == []
    assert dropped == 1


def test_validate_cards_drops_invalid_fields():
    cases = [
        _card(),  # 用副本逐个破坏
    ]
    broken_question = _card()
    broken_question["question"] = "太短"
    broken_answer = _card()
    broken_answer["answer"] = "短"
    broken_tags = _card()
    broken_tags["tags"] = []
    broken_para = _card(paragraph_index=99)
    for bad in [broken_question, broken_answer, broken_tags, broken_para]:
        cases.append(bad)
    for note, bad, expected in [
        ("question 过短", broken_question, 1),
        ("answer 过短", broken_answer, 1),
        ("tags 为空", broken_tags, 1),
        ("段落越界", broken_para, 1),
    ]:
        cards, dropped = validate_cards([bad], PARAGRAPHS, "a1")
        assert (cards, dropped) == ([], 1), note


def test_validate_cards_caps_per_article():
    many = [_card() for _ in range(CARD_MAXIMA + 2)]
    cards, _ = validate_cards(many, PARAGRAPHS, "a1")
    assert len(cards) == CARD_MAXIMA


def _payload(cards):
    return json.dumps({"cards": cards}, ensure_ascii=False)


def _call(payload):
    def _stub(*_args, **_kwargs):
        return payload
    return _stub


def test_refine_cards_applies_daily_budget():
    result = refine_cards(_article(), {"deepseek_api_key": "k"}, call=_call(_payload([_card()] * 3)), daily_budget=2)
    assert result["cards"] and len(result["cards"]) == 2


def test_refine_cards_returns_error_when_all_dropped():
    result = refine_cards(_article(), {"deepseek_api_key": "k"}, call=_call(_payload([_card(sentence="不存在")])), daily_budget=5)
    assert "error" in result


def test_refine_cards_returns_error_without_key():
    result = refine_cards(_article(), {}, daily_budget=5)
    assert result["error"] == "ai_config:missing_api_key"


def test_refine_cards_routes_by_variant():
    captured = {}

    def _probe(messages, _cfg, **_kw):
        captured["system"] = messages[0]["content"]
        return _payload([_card()])

    refine_cards(_article(title="全国统一大市场建设方案"), {"deepseek_api_key": "k"}, call=_probe, daily_budget=5)
    assert "政策文件/规划/报告" in captured["system"]
    refine_cards(_article(title="学习时报评论：敬畏历史"), {"deepseek_api_key": "k"}, call=_probe, daily_budget=5)
    assert "可直接用于申论写作" in captured["system"]


def test_daily_new_card_limit_constant():
    assert DAILY_NEW_CARD_LIMIT == 5


def test_locate_alignment_with_annotation_offsets():
    # 锚定定位与 AI 标注共用 _locate：同一片段得到同一组偏移（左闭右开 UTF-16）。
    start, end, matched = _locate(PARAGRAPHS[2], "2026 年经济增长预期目标为 4.5%—5%。")
    assert PARAGRAPHS[2][start:end] == matched


def test_explain_is_optional_enhancement():
    """explain（逐项解析）是**增强**：合规就带上，缺了或不合规只丢这个字段，
    不作废整张卡——与管道"降级不阻断"的一贯做法一致（端上用基础解析兜底）。"""
    paragraphs = ["全面贯彻党的教育方针，落实立德树人根本任务。"]
    base = {
        "question": "《行动计划》实施要落实的根本任务是什么？",
        "answer": "落实立德树人根本任务。",
        "tags": ["任务"],
        "anchor": {"paragraphIndex": 0, "sentence": "落实立德树人根本任务"},
    }

    cards, dropped = validate_cards(
        [dict(base, explain="原文明确「落实立德树人根本任务」，这是教育领域一贯的根本任务提法。")],
        paragraphs,
        "a1",
    )
    assert dropped == 0
    assert cards[0]["explain"].startswith("原文明确")

    # 缺 explain：卡片仍有效，只是没有该字段
    cards, dropped = validate_cards([base], paragraphs, "a1")
    assert dropped == 0
    assert "explain" not in cards[0]

    # explain 过短：同样只丢字段，不作废卡片
    cards, dropped = validate_cards([dict(base, explain="太短")], paragraphs, "a1")
    assert dropped == 0
    assert "explain" not in cards[0]
