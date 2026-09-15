# -*- coding: utf-8 -*-
"""每日一练出题逻辑单测：target_count + parse_questions + generate_practice（注入 mock chat）。"""
import json
from pathlib import Path

from kaogong.practice import (
    HINT_MAX_LENGTH,
    HINT_MIN_LENGTH,
    TRAP_MAX_LENGTH,
    TRAP_MIN_LENGTH,
    build_system_prompt,
    duplicate_trap_count,
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


# ── traps（画布 3:617 错因标签）────────────────────────────────────────────


def test_parse_questions_keeps_traps():
    # Given: 模型按提示词给 4 个选项各配了误因，正确项（answer=0）给空串。
    items = [_q(1, traps=["", "张冠李戴", "以偏概全", "数字记混"]), _q(2), _q(3)]

    qs = parse_questions(_content(items))

    # Then: 原样保留（正确项空串是协议的一部分，不是缺失）；没给的题字段直接缺席。
    assert qs[0]["traps"] == ["", "张冠李戴", "以偏概全", "数字记混"]
    assert "traps" not in qs[1]


def test_parse_questions_blanks_answer_slot_in_traps():
    # Given: 模型没守规矩，把「正确」也写成了误因（提示词要求空串）。
    items = [_q(1, answer=2, traps=["张冠李戴", "以偏概全", "正确答案", "数字记混"]), _q(2), _q(3)]

    qs = parse_questions(_content(items))

    # Then: 正确项那一格强制空串——画布上只有错题才显示错因，正确项没有「错因」可言。
    assert qs[0]["traps"][2] == ""
    assert qs[0]["traps"][0] == "张冠李戴"


def test_parse_questions_drops_malformed_traps():
    # Given: 长度不是 4（与 options 对不上）、或根本不是数组。
    items = [
        _q(1, traps=["张冠李戴", "以偏概全"]),
        _q(2, traps="张冠李戴"),
        _q(3, traps=["张冠李戴", "以偏概全", "过度引申", "数字记混", "多了一项"]),
    ]

    qs = parse_questions(_content(items))

    # Then: 对不上就不给端上猜的机会——字段缺席，端上退回「你的 X → 正确 Y」。
    assert len(qs) == 3
    assert all("traps" not in q for q in qs)


def test_parse_questions_drops_all_empty_traps():
    # Given: 模型没抽出任何误因，四项全空。
    items = [_q(1, traps=["", "", "", ""]), _q(2), _q(3)]

    qs = parse_questions(_content(items))

    # Then: 不留一个全是空串的字段（端上按「有字段但取到空」渲染会出空行）。
    assert "traps" not in qs[0]


def test_parse_questions_sanitizes_short_and_overlong_trap():
    # Given: 一格过短（等于没给）、一格超长。
    items = [_q(1, traps=["", "嗯", "张" * 200, "数字记混"]), _q(2), _q(3)]

    qs = parse_questions(_content(items))

    # Then: 过短留空串、超长截断到上限，其余不动。
    assert qs[0]["traps"] == ["", "", "张" * TRAP_MAX_LENGTH, "数字记混"]


def test_practice_trap_bounds_match_schema():
    # Given: 错因标签长度是「管道截断」与「schema 校验」双实现。
    schema = json.loads(
        (Path(__file__).resolve().parents[2] / "content" / "schema" / "practice.schema.json")
        .read_text(encoding="utf-8")
    )
    traps = schema["$defs"]["question"]["properties"]["traps"]

    # Then: 两边必须一致，否则管道会写出自己 schema 不认的内容。
    assert traps["items"]["maxLength"] == TRAP_MAX_LENGTH
    # 与 options 同下标，所以固定 4 项；正确项是空串，故 items 不设 minLength。
    assert traps["minItems"] == 4
    assert traps["maxItems"] == 4
    assert "minLength" not in traps["items"]
    # 且 traps 必须可选：存量 practice.json 没有该字段，不能变成必填。
    assert "traps" not in schema["$defs"]["question"]["required"]
    # TRAP_MIN_LENGTH 是管道侧「视为没给」的门槛，不进 schema（schema 允许空串）。
    assert TRAP_MIN_LENGTH >= 1


# ── 错因标签不得同质化（2026-09-15 实测 79% 有重复，生成侧约束）────────────────
def test_duplicate_trap_count_flags_reused_label():
    # Given: 三个干扰项复用同一个标签（实测最常见的失败形态）
    questions = [{"traps": ["", "以偏概全", "以偏概全", "以偏概全"]}]

    # Then: 算作 1 道重复
    assert duplicate_trap_count(questions) == 1


def test_duplicate_trap_count_ignores_empty_answer_slot():
    # Given: 正确项空串 + 三个互不相同的标签 —— 空串不该被当成「重复」
    questions = [{"traps": ["", "张冠李戴", "数字记混", "过度引申"]}]

    assert duplicate_trap_count(questions) == 0


def test_duplicate_trap_count_counts_across_questions():
    questions = [
        {"traps": ["", "张冠李戴", "张冠李戴", "数字记混"]},  # 重复
        {"traps": ["", "张冠李戴", "数字记混", "过度引申"]},  # 不重复
        {"traps": ["", "概念混淆", "概念混淆", "概念混淆"]},  # 重复
    ]

    assert duplicate_trap_count(questions) == 2


def test_duplicate_trap_count_tolerates_missing_traps():
    # 没有 traps / 空列表 / 全空串 都不该被计成重复，也不该抛错
    assert duplicate_trap_count([{}, {"traps": []}, {"traps": ["", "", "", ""]}, None]) == 0
    assert duplicate_trap_count([]) == 0


def test_system_prompt_states_trap_distinctness():
    # Given: 提示词是这条约束的**唯一执行手段**（代码层不重排标签，只校验）
    prompt = build_system_prompt(10)

    # Then: 必须明确要求三个错误项互不相同 —— 谁删了这句话，这里就会红。
    assert "互不相同" in prompt
    assert "严禁三个选项复用同一个标签" in prompt
