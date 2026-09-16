# -*- coding: utf-8 -*-
"""文章 AI 概括与只读标注：模型判断内容，程序负责定位和质量校验。"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from .deepseek import Cfg, DEFAULT_MODEL, chat

# v3：标注密度收紧（生成侧）。v2 产物是「段段带标注」的密集代，v3 起为稀疏点缀；
# 升版是为了让两代产物可区分（schema 只要求 aiPromptVersion 为非空字符串，不锁枚举）。
PROMPT_VERSION = "article-analysis-v3"
ALLOWED_TYPES = {"viewpoint", "exam_point", "term", "figure"}
# ⚠️ 标注密度有两个用途不同的常量，切勿合并成一个。
#
# 1) ANNOTATION_MAXIMA —— 「**校验上界**」，由 validate_article_ai 使用。
#    它回答的是「这个文件是否已损坏」，因此必须容纳按旧上限生成的历史内容。
#    实测 content/ 内有 189 篇 / 6 个日期（08-17、08-19、08-20、08-21、09-11、
#    09-12）超过下面的新生成上限、但不超本上界。一旦下调它，等于**回溯宣告存量
#    非法**：quality_gate 会把那些日期刷成 failed 并回写 _reports（违反项目纪律
#    「质量报告只收集不降级旧文章」）。要改的是生成侧，不是这里。
ANNOTATION_MAXIMA = {"viewpoint": 5, "exam_point": 8, "term": 5, "figure": 10}

# 2) ANNOTATION_GENERATION_RANGE —— 「**生成侧密度约束**」，用于提示词 + 截断。
#    画布 02/25 上标注是「短语级稀疏点缀」。旧值 viewpoint 5 / exam_point 8 /
#    term 5 / figure 10 极端合计 28 处，实测出现「9 段正文 9 段带标注、单条覆盖
#    整句」的条纹纸效果，故全面收紧。每项 (最少, 最多)：最少只进提示词，最多用于截断。
ANNOTATION_GENERATION_RANGE = {
    "viewpoint": (2, 3), "exam_point": (2, 5), "term": (1, 3), "figure": (1, 4),
}
ANNOTATION_GENERATION_MAXIMA = {
    kind: high for kind, (_, high) in ANNOTATION_GENERATION_RANGE.items()
}
ANNOTATION_LABELS = {
    "viewpoint": "观点", "exam_point": "考点", "term": "术语", "figure": "数字/指标",
}
# 全篇标注总上限：超过按「先到先得」截断（模型输出顺序 ≈ 段落顺序）。
ANNOTATION_TOTAL_MAX = 12
# 每段最多几条：防「段段带标注」。
ANNOTATION_PER_PARAGRAPH_MAX = 2
# 单条片段的 utf16 长度上限：超过视为整句而非短语，直接丢弃。
# 提示词要求 30 字（ANNOTATION_TEXT_PROMPT_MAX），此处放宽到 40 作容错——
# 宁可保留略长的合格短语，也不因模型多写两字就把整条丢掉。
ANNOTATION_TEXT_PROMPT_MAX = 30
ANNOTATION_TEXT_MAX = 40


class RawAnnotation(TypedDict, total=False):
    paragraphIndex: int
    text: str
    type: str
    explanation: str


class ArticleAiPayload(TypedDict):
    summary: str
    annotations: list[RawAnnotation]
    # v2.1 §7.3（T04）：段落聚焦——整篇并非全部值得精读、仅连续若干段有政策
    # 阐释/考点价值时的段落范围（塞上江南类）；无聚焦时为 None
    focus: dict | None


@dataclass(frozen=True, slots=True)
class ArticleAiError(Exception):
    code: str

    def __str__(self) -> str:
        return self.code


def source_text_hash(paragraphs: list[str]) -> str:
    return hashlib.sha256("\n".join(p.strip() for p in paragraphs).encode("utf-8")).hexdigest()


def normalize_text(value: str) -> str:
    r"""HTML 实体解码 + 空白折叠 + 首尾裁剪；与前端构建时 unescapeHtmlEntities 的规则对齐。

    Python re 的 s 与前端 JS 的 s 同样匹配  / /　 等 Unicode 空白，
    保证管道清洗后的正文与前端渲染文本逐字符一致（否则 AI 标注偏移会失配）。
    """
    out = re.sub(r"\s+", " ", html.unescape(value or "")).strip()
    return out or value


def normalize_article(article: dict) -> dict:
    """清洗已入库正文并在清洗后文本上重新定位 AI 标注偏移。

    历史剪藏可能带字面实体（&emsp; 等）；前端构建时也会解码，导致段落文本变化、
    旧偏移全部失配。这里在管道层一次性解码 + 重定位，保证标注与渲染文本一致。
    不重新调用 AI，不修改标题/来源等字段。
    """
    result = dict(article)
    old_paras = list(article.get("paragraphs") or [])
    new_paras = [normalize_text(p) for p in old_paras]
    result["paragraphs"] = new_paras
    if article.get("aiStatus") == "ok":
        result.pop("aiError", None)  # 成功态不允许残留失败原因
    annotations = list(article.get("aiAnnotations") or [])
    if annotations and new_paras != old_paras:
        relocated: list[dict] = []
        location_errors = 0
        for ann in annotations:
            index = ann.get("paragraphIndex", -1)
            snippet = str(ann.get("text", ""))
            if not isinstance(index, int) or not 0 <= index < len(new_paras) or not snippet:
                location_errors += 1
                continue
            try:
                start, end, matched = _locate(new_paras[index], snippet)
            except ValueError:
                location_errors += 1
                continue
            relocated.append({**ann, "start": start, "end": end, "text": matched})
        result["aiAnnotations"] = relocated
        quality = dict(article.get("aiQuality") or {})
        quality["locationErrors"] = int(quality.get("locationErrors", 0) or 0) + location_errors
        result["aiQuality"] = quality
    result["sourceTextHash"] = source_text_hash(new_paras)
    return result


def _json_object(raw: str) -> ArticleAiPayload:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ArticleAiError("ai_parse:json_object_missing")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ArticleAiError("ai_parse:invalid_json") from exc
    if not isinstance(value, dict):
        raise ArticleAiError("ai_schema:root_not_object")
    summary = value.get("summary")
    annotations = value.get("annotations")
    if not isinstance(summary, str):
        raise ArticleAiError("ai_schema:summary_not_string")
    if not isinstance(annotations, list):
        raise ArticleAiError("ai_schema:annotations_not_array")
    parsed_annotations: list[RawAnnotation] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            raise ArticleAiError("ai_schema:annotation_not_object")
        paragraph_index = annotation.get("paragraphIndex")
        snippet = annotation.get("text")
        kind = annotation.get("type")
        explanation = annotation.get("explanation")
        if not isinstance(paragraph_index, int):
            raise ArticleAiError("ai_schema:paragraph_index_not_integer")
        if not isinstance(snippet, str) or not isinstance(kind, str):
            raise ArticleAiError("ai_schema:annotation_field_not_string")
        if kind not in ALLOWED_TYPES:
            raise ArticleAiError("ai_schema:annotation_type_invalid")
        parsed: RawAnnotation = {
            "paragraphIndex": paragraph_index,
            "text": snippet,
            "type": kind,
        }
        if explanation is not None:
            if not isinstance(explanation, str):
                raise ArticleAiError("ai_schema:explanation_not_string")
            parsed["explanation"] = explanation
        parsed_annotations.append(parsed)
    # v2.1 §7.3：focus 只做形状规整（整数化），范围校验（0≤from≤to<段数）在
    # analyze_article 里做——此处拿不到段落数
    raw_focus = value.get("focus")
    focus: dict | None = None
    if isinstance(raw_focus, dict):
        try:
            frm, to = int(raw_focus.get("from")), int(raw_focus.get("to"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            frm = to = None  # type: ignore[assignment]
        if frm is not None and to is not None and frm <= to:
            focus = {"from": frm, "to": to}
    return {"summary": summary, "annotations": parsed_annotations, "focus": focus}


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _locate(paragraph: str, snippet: str) -> tuple[int, int, str]:
    """定位标注片段，返回 (utf16_start, utf16_end, 实际匹配文本)。

    先精确匹配；失败后折叠空白重试（AI 常额外加空格/换行）；片段不唯一时取首个，
    不再因重复出现而整条丢弃。
    """
    matched = snippet
    start = paragraph.find(snippet)
    if start < 0:
        folded = re.sub(r"\s+", " ", snippet).strip()
        if folded and folded != snippet:
            start = paragraph.find(folded)
            if start >= 0:
                matched = folded
    if start < 0:
        raise ValueError("标注片段无法在指定段落定位")
    utf16_start = _utf16_len(paragraph[:start])
    utf16_end = utf16_start + _utf16_len(matched)
    return utf16_start, utf16_end, matched


def _utf16_slice(text: str, start: int, end: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[start * 2:end * 2].decode("utf-16-le")


def validate_article_ai(article: dict) -> list[str]:
    """返回语义质量错误；JSON Schema 之外的跨字段规则在这里校验。"""
    errors: list[str] = []
    paragraphs = article.get("paragraphs") or []
    if article.get("sourceTextHash") != source_text_hash(paragraphs):
        errors.append("source_hash_mismatch")
    seen: set[str] = set()
    counts = {kind: 0 for kind in ALLOWED_TYPES}
    for annotation in article.get("aiAnnotations") or []:
        aid = annotation.get("id", "")
        if not aid:
            errors.append("annotation_id_invalid")
        elif aid in seen:
            errors.append("annotation_id_duplicate")
        seen.add(aid)
        index = annotation.get("paragraphIndex", -1)
        start, end = annotation.get("start", -1), annotation.get("end", -1)
        if not isinstance(index, int) or not 0 <= index < len(paragraphs):
            errors.append("paragraph_out_of_range")
            continue
        utf16_length = len(paragraphs[index].encode("utf-16-le")) // 2
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= utf16_length:
            errors.append("offset_invalid")
            continue
        try:
            selected_text = _utf16_slice(paragraphs[index], start, end)
        except UnicodeDecodeError:
            errors.append("offset_invalid")
            continue
        if selected_text != annotation.get("text"):
            errors.append("annotation_text_mismatch")
        if annotation.get("type") not in ALLOWED_TYPES:
            errors.append("annotation_type_invalid")
        else:
            counts[annotation["type"]] += 1
        explanation = annotation.get("explanation")
        if explanation and annotation.get("type") != "term":
            errors.append("explanation_type_invalid")
    for kind, maximum in ANNOTATION_MAXIMA.items():
        if counts[kind] > maximum:
            errors.append(f"annotation_count_{kind}")
    # v2.1 §7.3：aiFocus 范围校验（持久化产物守门；旧文章无该字段则跳过）
    focus = article.get("aiFocus")
    if focus is not None:
        frm = to = None
        if isinstance(focus, dict):
            try:
                frm, to = int(focus.get("from")), int(focus.get("to"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                frm = None
        if frm is None or to is None or not 0 <= frm <= to < len(paragraphs):
            errors.append("ai_focus_invalid")
    return errors


def _normalize_focus(raw: object, paragraph_count: int) -> dict | None:
    """段落聚焦范围校验（v2.1 §7.3）：0 ≤ from ≤ to < paragraph_count，非法即丢弃。

    与 curation._normalize_focus 同一校验口径（各留一份，避免 card_ai → article_ai
    依赖环）；宁缺勿滥，不带病透传。
    """
    if not isinstance(raw, dict) or paragraph_count <= 0:
        return None
    try:
        frm = int(raw.get("from"))  # type: ignore[arg-type]
        to = int(raw.get("to"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if 0 <= frm <= to < paragraph_count:
        return {"from": frm, "to": to}
    return None


def _messages(title: str, paragraphs: list[str], *, rewrite: bool = False, correction: str = "") -> list[dict[str, str]]:
    article = "\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs))
    length = "将 summary 重写为 80-120 个中文字符。" if rewrite else "summary 必须为 80-120 个中文字符。"
    if correction:
        length += " " + correction
    # 密度句由 ANNOTATION_GENERATION_RANGE 派生，避免「改了常量忘了改提示词」的漂移。
    density = "、".join(
        f"{ANNOTATION_LABELS[kind]} {low}-{high} 处"
        for kind, (low, high) in ANNOTATION_GENERATION_RANGE.items()
    )
    return [
        {"role": "system", "content": (
            "你是公务员考试时政内容编辑。只返回 JSON，不得返回 Markdown/HTML。"
            "不得补充原文没有的事实。annotations 每项只返回 paragraphIndex、text、type、explanation；"
            "text 必须是对应段落中的连续原文且在该段唯一。type 只能是 viewpoint、exam_point、term、figure；"
            "仅 term 可有 explanation，释义 30-80 个中文字符。"
            f"{density}，全部标注合计不超过 {ANNOTATION_TOTAL_MAX} 条，"
            f"且同一段落最多 {ANNOTATION_PER_PARAGRAPH_MAX} 处；"
            f"标注片段必须是短语（不超过 {ANNOTATION_TEXT_PROMPT_MAX} 个中文字符），不要选整句或长句"
            " —— 标注是稀疏点缀，宁少勿多；"
            "figure 用于标注纯数字/指标值（增速、总额、覆盖率、时间节点等），不写 explanation；"
            "数字/指标考点不生成卡片，由 figure 标注在原文中高亮记忆。"
            "focus（段落聚焦）：整篇均有精读价值或均无价值时输出 null；"
            "仅部分连续段落有政策阐释/考点价值时，输出该范围 {\"from\": 段索引, \"to\": 段索引}"
            "（闭区间，段索引从 0 起，不得跨出全文）。"
        )},
        {"role": "user", "content": (
            f"{length}\n输出形状：{{\"summary\":\"...\",\"annotations\":[{{\"paragraphIndex\":0,"
            "\"text\":\"原文片段\",\"type\":\"viewpoint\"}]},\"focus\":null}\n"
            f"标题：{title}\n原文：\n{article}"
        )},
    ]


def analyze_article(
    article: dict,
    cfg: Cfg,
    *,
    call: Callable[..., str] = chat,
    attempts: int = 2,
) -> dict:
    """返回带 AI 字段的新文章；任何失败均降级为 error，不修改原文。"""
    result = dict(article)
    paragraphs = list(article.get("paragraphs") or [])
    model = cfg.get("deepseek_model") or DEFAULT_MODEL
    generated = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    base = {
        "aiModel": model,
        "aiPromptVersion": PROMPT_VERSION,
        "aiGeneratedAt": generated,
        "sourceTextHash": source_text_hash(paragraphs),
    }
    try:
        if not cfg.get("deepseek_api_key"):
            raise ArticleAiError("ai_config:missing_api_key")
        payload: ArticleAiPayload | None = None
        for attempt in range(attempts):
            payload = _json_object(call(
                _messages(str(article.get("title", "")), paragraphs, rewrite=attempt > 0),
                cfg, max_tokens=1800, temperature=0.2,
            ))
            summary = str(payload.get("summary", "")).strip()
            if 80 <= len(summary) <= 120:
                break
        if payload is None:
            raise ArticleAiError("ai_provider:no_output")
        summary = payload["summary"].strip()
        if not 60 <= len(summary) <= 150:
            # 纠错重试：把具体长度错误反馈给模型重写一次。
            # ⚠️ 只报「长度不符合」不够 —— 实测模型会连续吐 161~181 字。
            # 2026-09-16 A/B（短新闻 799 字样本，各 6 次采样）：
            #   只说「不符合 80-120 字要求」→ 3/6 达标（162/181/161 超上限）
            #   补上「太长了 + 压到 120 字以内 + 宁短勿长 + 具体删什么」→ 6/6 达标（93~103）
            # 长文样本（4270 字）两种说法均 6/6，无回归。
            # 方向词是关键：模型擅长删减，不擅长自行判断该往哪边调。
            if len(summary) > 120:
                correction = (
                    f"你上次的摘要长度为 {len(summary)} 字，太长了。必须压到 120 字以内，宁短勿长："
                    "只保留最重要的一件事 + 一个数字，删掉次要背景与并列细节。"
                )
            else:
                correction = f"你上次的摘要长度为 {len(summary)} 字，不符合 80-120 字要求，请重写。"
            payload = _json_object(call(
                _messages(str(article.get("title", "")), paragraphs, rewrite=True, correction=correction),
                cfg, max_tokens=1800, temperature=0.2,
            ))
            summary = str(payload.get("summary", "")).strip()
        if not 60 <= len(summary) <= 150:
            raise ArticleAiError("ai_semantic:summary_length")
        annotations: list[dict] = []
        location_errors = 0
        for i, raw in enumerate(payload["annotations"]):
            try:
                index = int(raw["paragraphIndex"])
                snippet, kind = str(raw["text"]).strip(), str(raw["type"])
                if kind not in ALLOWED_TYPES or not 0 <= index < len(paragraphs) or not snippet:
                    raise ValueError("标注字段非法")
                # 片段过长 = 整句而非短语（画布要求稀疏点缀）→ 直接丢弃，不定位
                if _utf16_len(snippet) > ANNOTATION_TEXT_MAX:
                    raise ValueError("标注片段过长")
                start, end, matched = _locate(paragraphs[index], snippet)
                annotation = {
                    "id": f"ai-{index}-{start}-{end}-{kind}", "paragraphIndex": index,
                    "start": start, "end": end, "text": matched, "type": kind,
                }
                explanation = str(raw.get("explanation", "")).strip()
                if kind == "term" and 30 <= len(explanation) <= 80:
                    annotation["explanation"] = explanation
                annotations.append(annotation)
            except (KeyError, TypeError, ValueError):
                location_errors += 1
        # 超上限截断（保留前 N 个，按模型输出顺序 ≈ 段落顺序），而不是整篇标 error。
        # 三层约束：每类上限 + 全篇总上限 + 每段上限（防「段段带标注」）。
        truncated: list[dict] = []
        counts: dict[str, int] = {}
        per_paragraph: dict[int, int] = {}
        for ann in annotations:
            kind = str(ann["type"])
            para = int(ann["paragraphIndex"])
            if counts.get(kind, 0) >= ANNOTATION_GENERATION_MAXIMA[kind]:
                continue
            if per_paragraph.get(para, 0) >= ANNOTATION_PER_PARAGRAPH_MAX:
                continue
            if len(truncated) >= ANNOTATION_TOTAL_MAX:
                break
            counts[kind] = counts.get(kind, 0) + 1
            per_paragraph[para] = per_paragraph.get(para, 0) + 1
            truncated.append(ann)
        annotations = truncated
        # v2.1 §7.3：段落聚焦持久化（仅 ok 态；范围非法时静默丢弃，不标 error）
        success: dict = {
            "aiStatus": "ok", "aiSummary": summary, "aiAnnotations": annotations,
            "aiQuality": {"locationErrors": location_errors},
        }
        focus = _normalize_focus(payload.get("focus"), len(paragraphs))
        if focus is not None:
            success["aiFocus"] = focus
        result.update(base | success)
        result.pop("aiError", None)  # 从 error 升级到 ok 时清理旧失败原因残留
        errors = validate_article_ai(result)
        if errors:
            raise ArticleAiError(f"ai_semantic:{errors[0]}")
        return result
    except ArticleAiError as exc:
        reason = str(exc)
    except Exception:
        reason = "ai_provider:request_failed"
    result.update(base | {
        "aiStatus": "error", "aiAnnotations": [], "aiError": reason,
    })
    result.pop("aiSummary", None)
    result.pop("aiQuality", None)
    result.pop("aiFocus", None)
    return result
