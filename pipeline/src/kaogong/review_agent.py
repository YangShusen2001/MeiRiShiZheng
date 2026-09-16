# -*- coding: utf-8 -*-
"""审核 Agent（Phase 1：只判不改）。

对每日文章打分并给出 verdict（keep / rewrite / drop / rerun）+ 理由 + 建议修改，
不写回 content/。判定黄金标准见 docs/product/review-judging-rubric.md。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

from .deepseek import Cfg, chat

PROMPT_VERSION = "review-judge-v1"
VERDICTS = {"keep", "rewrite", "drop", "rerun"}
ANNOTATION_LABEL = {"viewpoint": "观点", "exam_point": "考点", "term": "术语"}

_SYSTEM = (
    "你是公务员考试时政内容的审核编辑，负责判断一篇抓取来的文章是否值得收录、标题摘要是否合格、"
    "AI 概括与标注是否可靠。只返回 JSON，不得返回 Markdown/HTML。\n"
    "评分维度（0-100）：\n"
    "1) 相关性(30)：官方时政/政策/评论/申论素材/社会治理/民生/经济/乡村振兴/科创/法治等该收；"
    "广告软文、娱乐八卦、体育、纯商业、无关生活资讯、招聘、重复转载灌水、登录跳转页等不该收。\n"
    "2) 标题质量(20)：去来源前缀、无乱码/HTML残留/截断、长度合理、准确反映主旨、不标题党。\n"
    "3) 摘要质量(20)：80-120字、概括主旨、不添加原文没有的事实、无套话。\n"
    "4) AI标注质量(20)：viewpoint=判断/立场/结论、exam_point=措施/原因/方法/对策、term=概念/术语/新提法；"
    "数量合理(观点2-5、考点3-8、术语1-5)；定位准确不张冠李戴；术语释义30-80字准确。\n"
    "5) 原文完整(10)：正文非空、段落完整；aiStatus=error 时标注缺失但原文可读属降级，不因此扣分。\n"
    "verdict 规则：keep=相关且标题摘要达标(score>=80)；rewrite=相关但标题/摘要不合格(必给newTitle或newSummary)；"
    "drop=相关性低或明显噪声(reason说明为何不该收)；rerun=aiStatus=error且原文可读(建议补跑AI)。\n"
    "不确定就不硬判：拿不准返回 keep 并在 reason 注明「低置信」，绝不猜测删除。"
)


def _article_id(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:10]


def _messages(item: dict, article: dict | None) -> list[dict[str, str]]:
    source = (article or {}).get("source") or item.get("source", "")
    annotations = (article or {}).get("aiAnnotations") or []
    ann_lines = []
    for a in annotations[:20]:
        label = ANNOTATION_LABEL.get(str(a.get("type", "")), str(a.get("type", "")))
        explanation = str(a.get("explanation") or "").strip()
        ann_lines.append(f"{label}|{a.get('text', '')}|{explanation[:40]}")
    body = "\n".join((article or {}).get("paragraphs") or [])[:800]
    user = json.dumps({
        "title": item.get("title", ""),
        "source": source,
        "summary": item.get("summary", ""),
        "aiStatus": (article or {}).get("aiStatus", ""),
        "aiSummary": (article or {}).get("aiSummary", ""),
        "annotations": ann_lines,
        "bodyExcerpt": body,
    }, ensure_ascii=False)
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": (
            '输出形状：{"score":85,"verdict":"keep","reason":"...","newTitle":"","newSummary":""}\n'
            + user
        )},
    ]


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("judge_parse:json_object_missing")
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("judge_parse:invalid_json") from exc
    if not isinstance(value, dict):
        raise ValueError("judge_parse:root_not_object")
    score = value.get("score")
    verdict = value.get("verdict")
    reason = value.get("reason")
    new_title = str(value.get("newTitle") or "").strip()
    new_summary = str(value.get("newSummary") or "").strip()
    if not isinstance(score, (int, float)) or not 0 <= score <= 100:
        raise ValueError("judge_schema:score_invalid")
    if verdict not in VERDICTS:
        raise ValueError("judge_schema:verdict_invalid")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("judge_schema:reason_missing")
    if verdict == "rewrite" and not (new_title or new_summary):
        raise ValueError("judge_schema:rewrite_missing_new")
    return {
        "score": int(round(score)),
        "verdict": verdict,
        "reason": reason.strip(),
        "newTitle": new_title,
        "newSummary": new_summary,
    }


def judge_item(
    item: dict,
    article: dict | None,
    cfg: Cfg,
    *,
    call: Callable[..., str] = chat,
    attempts: int = 2,
) -> dict:
    """判定单条文章，返回 {articleId, title, verdict, score, reason, newTitle, newSummary}。

    任何失败都降级为 verdict=needs_human（绝不猜测删除）。
    """
    base = {
        "articleId": (article or {}).get("id", ""),
        "title": item.get("title", ""),
        "verdict": "needs_human",
        "score": 0,
        "reason": "",
        "newTitle": "",
        "newSummary": "",
    }
    try:
        if not (cfg.get("deepseek_api_key") or "").strip():
            raise RuntimeError("未配置 DeepSeek API Key")
        payload: dict | None = None
        last_error = ""
        for _ in range(attempts):
            try:
                raw = call(_messages(item, article), cfg, max_tokens=600, temperature=0.2)
                payload = _parse(raw)
                break
            except Exception as exc:  # 解析/字段非法 → 重试一次
                last_error = str(exc)
        if payload is None:
            raise RuntimeError(last_error or "无输出")
        base.update(payload)
    except Exception as exc:  # pragma: no cover - 兜底
        base.update({"verdict": "needs_human", "reason": f"判定失败：{exc}"})
    return base


def review_date(target, content_dir: Path, cfg: Cfg) -> list[dict]:
    """判定某日 digest 里的全部条目，返回 decisions 列表（Phase 1：只判不改）。"""
    day = content_dir / target.isoformat()
    digest_path = day / "digest.json"
    if not digest_path.exists():
        return []
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    decisions: list[dict] = []
    for section in digest.get("sections", []):
        for item in section.get("items", []):
            url = str(item.get("sourceUrl", ""))
            article: dict | None = None
            if url:
                article_path = day / f"article-{_article_id(url)}.json"
                if article_path.exists():
                    try:
                        article = json.loads(article_path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        article = None
            decisions.append(judge_item(item, article, cfg))
    return decisions


def _sync_article_title(day: Path, url: str, new_title: str) -> None:
    """同步文章文件的标题（rewrite 时首页卡片与阅读页保持一致）。"""
    if not url or not new_title:
        return
    article_path = day / f"article-{_article_id(url)}.json"
    if not article_path.exists():
        return
    try:
        article = json.loads(article_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    article["title"] = new_title
    article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_decisions(digest: dict, decisions: list[dict], day: Path) -> tuple[dict, list[dict]]:
    """把 decisions 应用到 digest（rewrite 改标题/摘要并同步文章标题，drop 移除条目）。

    返回 (新 digest, changes 列表)。不写 digest 文件（由调用方持久化），但会同步文章标题。
    """
    import copy

    new_digest = copy.deepcopy(digest)
    changes: list[dict] = []
    index = 0
    for section in new_digest.get("sections", []):
        kept: list[dict] = []
        for item in section.get("items", []):
            decision = decisions[index] if index < len(decisions) else None
            index += 1
            if decision is None:
                kept.append(item)
                continue
            verdict = decision.get("verdict")
            if verdict == "drop":
                changes.append({
                    "articleId": decision.get("articleId", ""),
                    "title": item.get("title", ""),
                    "verdict": "drop",
                    "before": {"title": item.get("title", "")},
                    "after": None,
                    "reason": decision.get("reason", ""),
                })
                continue  # 不保留 → 移除
            if verdict == "rewrite":
                before = {"title": item.get("title", ""), "summary": item.get("summary", "")}
                after = dict(before)
                new_title = str(decision.get("newTitle", "") or "").strip()
                new_summary = str(decision.get("newSummary", "") or "").strip()
                if new_title:
                    item["title"] = new_title
                    after["title"] = new_title
                    _sync_article_title(day, str(item.get("sourceUrl", "")), new_title)
                if new_summary:
                    item["summary"] = new_summary
                    after["summary"] = new_summary
                kept.append(item)
                changes.append({
                    "articleId": decision.get("articleId", ""),
                    "title": before["title"],
                    "verdict": "rewrite",
                    "before": before,
                    "after": after,
                    "reason": decision.get("reason", ""),
                })
                continue
            kept.append(item)
        section["items"] = kept
    return new_digest, changes
