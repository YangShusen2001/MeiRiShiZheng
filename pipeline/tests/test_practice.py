# -*- coding: utf-8 -*-
"""每日一练出题逻辑单测：target_count + parse_questions + generate_practice（注入 mock chat）。"""
import json
from pathlib import Path

from kaogong.practice import (
    HINT_MAX_LENGTH,
    HINT_MIN_LENGTH,
    generate_practice,
    parse_questions,
    target_count,
)


def _q(i, **over):
    q = {"q": f"题干{i}", "options": ["A", "B", "C", "D"], "answer": 0, "analysis": "解析", "topic": "主题"}
    q.update(over)
    return q


def _content(items):
    return json.dumps({"questions": items}, ensure_ascii=False)


def test_target_count():
    assert target_count("") == 3
    assert target_count("x" * 240) == 3      # 240//120=2，抬到下限 3
    assert target_count("x" * 1200) == 10    # 1200//120=10
    assert target_count("x" * 2400) == 20    # 2400//120=20
    assert target_count("x" * 10000) == 20   # 封顶 20（服务考生，不硬凑更多）


def test_parse_questions_valid():
    items = [_q(1), _q(2), _q(3)]
    qs = parse_questions(_content(items))
    assert len(qs) == 3
    assert qs[0]["id"] == "q1"
    assert qs[0]["answer"] == 0


def test_parse_questions_requires_at_least_3():
    assert parse_questions(_content([_q(1), _q(2)])) == []


def test_parse_questions_skips_invalid_answer():
    items = [_q(1), _q(2), _q(3, answer=5), _q(4)]  # 第 3 题 answer 非法，跳过，仍剩 3 题
    qs = parse_questions(_content(items))
    assert len(qs) == 3
    assert all(q["answer"] == 0 for q in qs)


def test_parse_questions_skips_boolean_answer():
    items = [_q(1), _q(2), _q(3, answer=True), _q(4)]
    qs = parse_questions(_content(items))
    assert len(qs) == 3


def test_parse_questions_skips_bad_options():
    items = [_q(1), _q(2), _q(3, options=["A", "B", "C"]), _q(4)]  # 第 3 题只有 3 选项
    qs = parse_questions(_content(items))
    assert len(qs) == 3


def test_generate_practice_retries_then_succeeds():
    calls = []

    def chat_fn(messages, cfg, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return "这不是 JSON"
        return _content([_q(1), _q(2), _q(3)])

    qs = generate_practice("x" * 1200, "2026-08-12", {"deepseek_api_key": "k"}, chat_fn=chat_fn)
    assert len(qs) == 3
    assert len(calls) == 2  # 第一次不合格，重试成功


def test_generate_practice_gives_up_after_two():
    qs = generate_practice(
        "x" * 1200, "2026-08-12", {"deepseek_api_key": "k"},
        chat_fn=lambda messages, cfg, **kw: "还是不是 JSON",
    )
    assert qs == []


def test_parse_questions_keeps_hint():
    # Given: 模型给了 hint（画布 3:608「查看提示」展开的内容）。
    items = [_q(1, hint="注意材料中社会救助供给方式的那句"), _q(2, hint="区分慈善资金与政府救助"), _q(3)]

    qs = parse_questions(_content(items))

    # Then: hint 原样保留；没给的题不补空串，字段直接缺席。
    assert qs[0]["hint"] == "注意材料中社会救助供给方式的那句"
    assert qs[1]["hint"] == "区分慈善资金与政府救助"
    assert "hint" not in qs[2]


def test_parse_questions_drops_too_short_hint():
    # Given: hint 短于下限（等于模型没给），但题目本身合法。
    items = [_q(1, hint="嗯"), _q(2, hint="  "), _q(3)]

    qs = parse_questions(_content(items))

    # Then: 只丢 hint，不丢题——端上会退回 topic，而不是显示一条残缺提示。
    assert len(qs) == 3
    assert all("hint" not in q for q in qs)


def test_parse_questions_truncates_overlong_hint():
    # Given: hint 超出上限。
    items = [_q(1, hint="提" * 200), _q(2), _q(3)]

    qs = parse_questions(_content(items))

    # Then: 截断到上限，仍可用（schema maxLength 才不会判非法）。
    assert len(qs[0]["hint"]) == HINT_MAX_LENGTH


def test_practice_hint_bounds_match_schema():
    # Given: 提示长度是「管道截断」与「schema 校验」双实现。
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "content" / "schema" / "practice.schema.json")
        .read_text(encoding="utf-8")
    )
    hint = schema["$defs"]["question"]["properties"]["hint"]

    # Then: 两边必须一致，否则管道会写出自己 schema 不认的内容。
    assert hint["minLength"] == HINT_MIN_LENGTH
    assert hint["maxLength"] == HINT_MAX_LENGTH
    # 且 hint 必须可选：存量 practice.json 没有该字段，不能变成必填。
    assert "hint" not in schema["$defs"]["question"]["required"]
