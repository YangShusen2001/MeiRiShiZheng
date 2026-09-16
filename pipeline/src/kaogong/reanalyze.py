# -*- coding: utf-8 -*-
"""对已入库原文补跑 AI，不重新抓取页面。"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .article_ai import analyze_article, normalize_article
from .deepseek import Cfg, load_config

MAX_AI_FAILURES = 50


def refresh_report_stats(target: dt.date, content_dir: Path) -> None:
    """按当日文章文件实际状态重写报告里的 AI 统计（reanalyze 后报告必须准确）。

    quality_gate 保留生成时的统计语义；补跑改变了文件状态，这里单独刷新。
    """
    day = content_dir / target.isoformat()
    report_path = content_dir / "_reports" / f"{target.isoformat()}.json"
    if not report_path.exists() or not day.exists():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ai_ok = ai_error = 0
    location_errors = 0
    ai_failures: list[dict[str, str]] = []
    for path in sorted(day.glob("article-*.json")):
        try:
            article = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if article.get("aiStatus") == "ok":
            ai_ok += 1
            location_errors += int(article.get("aiQuality", {}).get("locationErrors", 0) or 0)
            continue
        ai_error += 1
        reason = str(article.get("aiError", "ai_unknown:failure")).split(maxsplit=1)[0]
        if not re.fullmatch(r"[a-z_]+:[a-zA-Z0-9_]+", reason):
            reason = "ai_unknown:failure"
        ai_failures.append({"articleId": str(article.get("id", "")), "reason": reason})
    report.update({
        "articles": ai_ok + ai_error,
        "aiOk": ai_ok,
        "aiError": ai_error,
        "aiFailures": ai_failures[:MAX_AI_FAILURES],
        "locationErrors": location_errors,
    })
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def reanalyze_content(
    target: dt.date,
    content_dir: Path,
    *,
    cfg: Cfg | None = None,
    force_ai: bool = False,
) -> int:
    """补跑当日文章：已成功的只清洗正文并重定位标注；未成功的用干净正文重新分析。

    force_ai=True 时连已成功文章也基于干净正文重新调用 AI（可把历史定位丢失归零，
    但会消耗 API 额度且重新生成标注）。
    返回实际写入篇数。清洗（normalize_article）不调用 AI，无 key 也能修复
    历史剪藏的实体噪音与失效偏移。
    """
    day = content_dir / target.isoformat()
    if not day.exists():
        return 0
    ai_cfg = cfg if cfg is not None else load_config()
    written = 0
    for path in sorted(day.glob("article-*.json")):
        article = json.loads(path.read_text(encoding="utf-8"))
        if article.get("status") != "ok":
            continue
        normalized = normalize_article(article)
        if normalized.get("aiStatus") == "ok":
            if not force_ai:
                if normalized != article:
                    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
                    written += 1
                continue
            # force：基于干净正文重新生成标注，覆盖旧 AI 字段
            updated = analyze_article(normalized, ai_cfg)
            path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
            continue
        updated = analyze_article(normalized, ai_cfg)
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
    refresh_report_stats(target, content_dir)
    return written
