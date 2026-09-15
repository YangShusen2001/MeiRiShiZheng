# -*- coding: utf-8 -*-
"""每日一练题目生成（移植自原 generate_practice.py）。

纯函数（target_count / build_system_prompt / parse_questions）可离线单测；
generate_practice 通过注入 chat_fn 测编排逻辑，不真实联网。
"""
from __future__ import annotations

import json
import re
from typing import Callable

MAX_QUESTIONS = 30
MIN_QUESTIONS = 3
TARGET_QUESTIONS = 20  # 每日一练目标题量（服务考生）

# 提示长度区间，与 content/schema/practice.schema.json 的 hint.minLength/maxLength
# 一一对应（由 test_practice_hint_bounds_match_schema 守住，别只改一边）。
HINT_MIN_LENGTH = 4
HINT_MAX_LENGTH = 60

# 错因标签长度区间，对应 practice.schema.json 的 traps.items.maxLength
# （由 test_practice_trap_bounds_match_schema 守住）。2 字起 —— 「选错」这种两字标签
# 已经能说明问题，再短就没有信息量了。
TRAP_MIN_LENGTH = 2
TRAP_MAX_LENGTH = 12

ChatFn = Callable[..., str]


def target_count(text: str) -> int:
    """目标 20 题：约每 120 字 1 题，材料不足时自然缩水，不硬凑。"""
    n = len(text or "")
    if n <= 0:
        return MIN_QUESTIONS
    return max(MIN_QUESTIONS, min(TARGET_QUESTIONS, n // 120))


def build_system_prompt(n: int) -> str:
    """AI 系统提示词：题目类型参考国省考行测 / 事业单位联考 / 三支一扶。"""
    return (
        "你是资深公考辅导老师，深谙国省考行测（常识判断/言语理解/判断推理）、"
        "事业单位联考、三支一扶的命题风格。\n"
        "用户会给你某一天的每日时政材料全文，"
        f"请基于材料出 {n} 道 4 选 1 客观题。\n"
        "覆盖类型建议：政策/文件要点记忆、时政名词理解、金句含义、材料中的数字与时间。\n"
        "要求：\n"
        "1. 题干独立完整，不依赖材料也能作答；\n"
        "2. 每道题 4 个选项且只有一个正确；干扰项必须是真实理解偏差"
        "（张冠李戴、以偏概全、过度引申、数字/时间错误）；\n"
        "3. 答案必须能从材料中找到依据；材料没有的信息不要考；\n"
        "4. 解析不超过 100 字，说明材料依据；\n"
        "5. topic 给一个主题词（如 健康中国/科技/民生）；\n"
        "6. hint 给一句话提示（画布「查看提示」按钮展开它）：指向材料依据或关键区分点，"
        "帮考生自己想到答案，**不得直接给出正确选项、答案字母或选项原文**；\n"
        "7. traps 给 4 个选项各配一个「典型误因」短标签（2-12 字、口语化），"
        "写选这个选项的人通常错在哪；**正确选项那一项必须给空字符串**；"
        "三个错误选项的误因**必须互不相同** —— 要针对该选项本身的内容写，"
        "严禁三个选项复用同一个标签（如全是「张冠李戴」）——"
        "「错因」是给考生看「我错在哪」的，同质标签等于没写。"
        "可选标签示例：张冠李戴、数字记混、时间错位、对象混淆、以偏概全、过度引申、"
        "漏读题干、概念混淆、偷换主体、答非所问、因果倒置、绝对化；\n"
        "8. 题目风格贴近国省考行测与事业单位/三支一扶真题，避免生硬罗列。\n"
        f'只输出 JSON：{{"questions":[{{"q":"题干","options":["A","B","C","D"],'
        '"answer":0,"analysis":"解析","topic":"主题","hint":"一句话提示",'
        '"traps":["误因A","误因B","误因C","误因D"]}]}}'
    )


def _parse_traps(raw: object, answer: int) -> list[str]:
    """把 AI 返回的 traps 收敛成「4 项、正确项空串」的形状（画布 3:617 的错因标签）。

    不合法（不是数组 / 长度不是 4）→ 返回空列表，让端上退回「你的 X → 正确 Y」。
    单项过短视为模型没给（留空串），过长截断 —— 与 hint 同一套「宁可省略，不编造」原则。
    四项全空同样返回空列表，不留一个全是空串的字段。
    """
    if not isinstance(raw, list) or len(raw) != 4:
        return []
    out: list[str] = []
    for i, value in enumerate(raw):
        if i == answer:
            out.append("")  # 正确项没有「错因」
            continue
        text = str(value or "").strip()[:TRAP_MAX_LENGTH]
        out.append(text if len(text) >= TRAP_MIN_LENGTH else "")
    return out if any(out) else []


def duplicate_trap_count(questions: list[dict]) -> int:
    """有多少道题的「错误项误因」出现了重复标签。

    实测（2026-09-15）：不加约束时 AI 会把三个干扰项都写成同一个标签（如全是「张冠李戴」）——
    103 题里 79% 有重复、57% 三项全同。这种「错因」只是在描述干扰项设计，
    对考生「我错在哪」零信息量，等于没写。

    提示词已要求三个错误项互不相同；这个函数是那条约束的**可测形式**，
    回填脚本据它决定要不要重问（拿不到更好的就保留原结果，不倒退）。
    """
    n = 0
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        traps = [t for t in (q.get("traps") or []) if t]
        if len(set(traps)) < len(traps):
            n += 1
    return n


def parse_questions(content: str, n: int | None = None) -> list[dict]:
    """从 AI 返回文本里抽出结构化题目；不合法跳过，不足 3 题整体返回空。"""
    m = re.search(r"\{[\s\S]*\}", content or "")
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return []
    raw = obj.get("questions") if isinstance(obj, dict) else None
    if not isinstance(raw, list):
        return []
    cap = n if n and n > 0 else MAX_QUESTIONS
    out: list[dict] = []
    for i, item in enumerate(raw[:cap]):
        if not isinstance(item, dict):
            continue
        q = str(item.get("q") or item.get("question") or "").strip()
        opts = [str(s or "").strip() for s in (item.get("options") or [])[:4]]
        answer = item.get("answer")
        analysis = str(item.get("analysis") or "").strip()
        if not q or len(opts) != 4 or any(not s for s in opts):
            continue
        # bool 是 int 的子类，显式排除，避免 True 被当成下标 1
        if not isinstance(answer, int) or isinstance(answer, bool) or answer < 0 or answer > 3:
            continue
        if not analysis:
            continue
        question = {
            "id": "q" + str(i + 1),
            "q": q[:200],
            "options": [s[:80] for s in opts],
            "answer": answer,
            "analysis": analysis[:200],
            "topic": str(item.get("topic") or "").strip()[:30],
        }
        # hint 可选：过短视为模型没给（宁可省略，让端上退回 topic），过长截断。
        hint = str(item.get("hint") or "").strip()[:HINT_MAX_LENGTH]
        if len(hint) >= HINT_MIN_LENGTH:
            question["hint"] = hint
        # traps 可选：与 options 等长、正确项空串；拿不到就让端上退回「你的 X → 正确 Y」
        traps = _parse_traps(item.get("traps"), answer)
        if traps:
            question["traps"] = traps
        out.append(question)
    return out if len(out) >= MIN_QUESTIONS else []


def _build_user_prompt(digest_text: str, date: str, attempt: int, n: int) -> str:
    user = "【日期】" + date + "\n\n【每日材料】\n" + digest_text[:8000]
    if attempt > 1:
        user += (
            "\n\n【上次输出不合格】请严格按 JSON 模板输出 "
            + str(n) + " 道题，每道题字段完整：q/options(4个)/answer(0-3)/analysis/topic/hint/traps。"
        )
    return user


def generate_practice(
    digest_text: str, date: str, cfg: dict, *, chat_fn: ChatFn | None = None
) -> list[dict]:
    """为某天材料生成每日一练；AI 输出不合格时重试一次。chat_fn 可注入（测试）。"""
    from .deepseek import chat as _deepseek_chat

    chat_fn = chat_fn or _deepseek_chat
    n = target_count(digest_text)
    for attempt in (1, 2):
        try:
            content = chat_fn(
                [
                    {"role": "system", "content": build_system_prompt(n)},
                    {"role": "user", "content": _build_user_prompt(digest_text, date, attempt, n)},
                ],
                cfg,
                max_tokens=min(8000, 600 + n * 160),
                temperature=0.4,
                timeout=120,
                extra={"response_format": {"type": "json_object"}},
            )
            questions = parse_questions(content, n)
            if questions:
                return questions
        except Exception:
            continue
    return []


def practice_set_json(date: str, questions: list[dict], source: str) -> dict:
    """组题集 JSON（写入 content/{date}/practice.json）。"""
    return {
        "date": date,
        "total": len(questions),
        "source": source,
        "questions": questions,
    }
