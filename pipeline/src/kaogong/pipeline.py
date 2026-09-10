# -*- coding: utf-8 -*-
"""内容管道编排：抓取 → 组装 → 写 content/ JSON。

这是「抓取逻辑 A」的顶层：把所有源跑一遍，只保留目标日期，按槽位截断，
交给 build_digest 组装，最后写成前端消费的 content/{date}/digest.json。
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

import httpx
from .build import build_digest
from .deepseek import load_config
from .models import Candidate
from .practice import generate_practice, practice_set_json
from .quality import artifact_semantic_errors, classify_artifact, load_artifact, schema_errors, volume_errors
from .review_agent import judge_item
from .summary import generate_summary
from .config import load_site_config
from .sources import Source, fetch_source, is_noise_title, load_noise_title, load_sources

# 每槽位最多收录条数（与原项目 _CAP 一致）
CAPS = {
    "pol": 25, "gov": 10, "shi": 18, "qst": 12, "xh": 18, "rm": 12,
    "byt": 8, "gd": 18, "sc": 20, "js": 20, "gdp": 15, "nf": 12,
}
MAX_AI_FAILURES = 50


def _pick_top(cands: list[Candidate], cap: int, ai_cfg: dict[str, str]) -> list[Candidate]:
    """当天候选超过槽位上限时，用审核 Agent 的 judge_item 评分取 top cap（score 降序）。

    无 DeepSeek key 或评分失败时 score=0，稳定排序退化为列表顺序。
    """
    if len(cands) <= cap:
        return cands

    def _score_one(c: Candidate) -> tuple[Candidate, float]:
        result = judge_item(
            {"title": c.title, "summary": c.summary or "", "sourceUrl": c.url},
            None, ai_cfg,
        )
        return c, float(result.get("score", 0) or 0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(cands))) as pool:
        scored = list(pool.map(_score_one, cands))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _ in scored[:cap]]


def fetch_candidates(
    target: dt.date, *, client: httpx.Client | None = None, report: dict | None = None,
    config: dict | None = None, cfg: dict[str, str] | None = None,
) -> list[Candidate]:
    """跑全部源（来源可后台配置），只保留 target 当日的候选，按槽位截断。单源失败不影响其余。"""
    config = config if config is not None else load_site_config()
    ai_cfg = cfg if cfg is not None else load_config()
    sources = load_sources(config)
    noise = load_noise_title(config)
    out: list[Candidate] = []

    def _fetch_source(src: Source) -> tuple[list[Candidate], Exception | None]:
        try:
            return fetch_source(src, client=client), None
        except Exception as exc:
            return [], exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(sources))) as pool:
        results = list(pool.map(_fetch_source, sources))
    for src, (items, exc) in zip(sources, results):
        if exc is None:
            out.extend(items)
            if report is not None:
                report["sourcesOk"] = report.get("sourcesOk", 0) + 1
        elif report is not None:
            report.setdefault("sourceErrors", []).append({
                "source": src.name,
                "error": f"source_fetch:{type(exc).__name__}",
            })
    out = [
        c for c in out
        if c.date == target and not is_noise_title(c.title, noise)
    ]
    # 按槽位分组；当天候选超过槽位上限时用 AI 评分挑重点（无 key 时退化为列表顺序）
    capped: list[Candidate] = []
    by_slot: dict[str, list[Candidate]] = {}
    for c in out:
        by_slot.setdefault(c.slot, []).append(c)
    for slot, cands in by_slot.items():
        capped.extend(_pick_top(cands, CAPS.get(slot, 20), ai_cfg))
    return capped


def build_content(target: dt.date, content_dir: Path, *, client: httpx.Client | None = None) -> Path:
    """抓取 → 组装 → 写 content/{date}/digest.json，返回产物路径。"""
    report: dict = {"date": target.isoformat(), "sourcesOk": 0, "sourceErrors": []}
    candidates = fetch_candidates(target, client=client, report=report)
    report["candidates"] = len(candidates)
    digest = build_digest(candidates, target)
    out_dir = content_dir / target.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "digest.json"
    path.write_text(
        json.dumps(digest.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_dir = content_dir / "_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{target.isoformat()}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def clip_content(
    target: dt.date, content_dir: Path, *, client: httpx.Client | None = None,
    cfg: dict[str, str] | None = None,
) -> int:
    """为某天日报的条目剪藏原文，写 content/{date}/article-{id}.json。返回剪藏成功数。

    并发剪藏 + AI 分析（默认 4 线程，可用环境变量 KAOGONG_CLIP_CONCURRENCY 调整），
    大幅缩短整批耗时；httpx.Client 线程安全，可跨线程共享。
    """
    from .clip import clip_article
    from .article_ai import analyze_article

    digest_path = content_dir / target.isoformat() / "digest.json"
    if not digest_path.exists():
        return 0
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    ai_cfg = cfg if cfg is not None else load_config()
    items = [
        (it.get("sourceUrl", ""), it.get("title", ""))
        for sec in digest.get("sections", [])
        for it in sec.get("items", [])
        if it.get("sourceUrl")
    ]
    concurrency = max(1, min(int(os.environ.get("KAOGONG_CLIP_CONCURRENCY", "4")), 8))

    def _clip_and_analyze(item: tuple[str, str]) -> tuple[str, dict]:
        url, title = item
        clip = clip_article(url, title, target.isoformat(), client=client)
        if clip.get("status") != "ok":
            return ("clip_error", clip)
        return ("analyzed", analyze_article(clip, ai_cfg))

    finished: list[dict] = []
    clip_failures: list[dict] = []
    if items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            for kind, data in pool.map(_clip_and_analyze, items):
                if kind == "clip_error":
                    clip_failures.append(data)
                else:
                    finished.append(data)

    out_dir = content_dir / target.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    report_path = content_dir / "_reports" / f"{target.isoformat()}.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"date": target.isoformat()}
    report.update({
        "articles": 0, "aiOk": 0, "aiError": 0,
        "aiFailures": [], "clipDetails": [], "locationErrors": 0,
    })
    for clip in finished:
        out = out_dir / f"article-{clip['id']}.json"
        out.write_text(json.dumps(clip, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
        report["articles"] += 1
        status = "ok" if clip.get("aiStatus") == "ok" else "error"
        reason = ""
        if status == "ok":
            report["aiOk"] += 1
            report["locationErrors"] += clip.get("aiQuality", {}).get("locationErrors", 0)
        else:
            report["aiError"] += 1
            reason = str(clip.get("aiError", "ai_unknown:failure")).split(maxsplit=1)[0]
            if not re.fullmatch(r"[a-z_]+:[a-zA-Z0-9_]+", reason):
                reason = "ai_unknown:failure"
            if len(report["aiFailures"]) < MAX_AI_FAILURES:
                report["aiFailures"].append({"articleId": str(clip["id"]), "reason": reason})
        report["clipDetails"].append({
            "id": str(clip["id"]),
            "title": str(clip.get("title", "")),
            "status": status,
            "reason": reason,
        })
    # 剪藏失败显性化：不再静默丢弃，写进 clipDetails 供日志排查
    for cf in clip_failures:
        report["clipDetails"].append({
            "id": str(cf.get("id", "")),
            "title": str(cf.get("title", "")),
            "status": "clip_error",
            "reason": str(cf.get("error", "正文提取失败"))[:120],
        })
    report_dir = content_dir / "_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{target.isoformat()}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return n


def _load_article(content_dir: Path, date: str, url: str) -> dict | None:
    """按 sourceUrl 读取剪藏原文（含 AI 概括/金句/标注），供出题喂富材料。"""
    if not url:
        return None
    aid = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    p = content_dir / date / f"article-{aid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _digest_text(digest: dict, content_dir: Path) -> str:
    """把 digest.json + 剪藏原文拍平成出题材料：标题/摘要/金句/AI 概括/关键标注。"""
    parts: list[str] = []
    date = str(digest.get("date", ""))
    for sec in digest.get("sections", []):
        sec_title = sec.get("title", "")
        if sec_title:
            parts.append(f"## {sec_title}")
        for it in sec.get("items", []):
            title = it.get("title", "")
            if title:
                parts.append(f"- {title}")
            summary = it.get("summary", "")
            if summary:
                parts.append(f"  摘要：{summary}")
            for q in it.get("quotes", []) or []:
                parts.append(f"  金句：{q}")
            article = _load_article(content_dir, date, str(it.get("sourceUrl", "")))
            if article:
                ai_summary = str(article.get("aiSummary", "") or "").strip()
                if ai_summary:
                    parts.append(f"  概括：{ai_summary}")
                for ks in article.get("keySentences", []) or []:
                    parts.append(f"  金句：{ks}")
                for ann in article.get("aiAnnotations", []) or []:
                    text = str(ann.get("text", "") or "").strip()
                    if text:
                        parts.append(f"  要点：{text}")
    return "\n".join(parts)


def backfill_summaries(target: dt.date, content_dir: Path) -> int:
    """把 AI 概括回填到 digest 的空摘要字段，供审核编辑与首页展示。返回回填条数。"""
    digest_path = content_dir / target.isoformat() / "digest.json"
    if not digest_path.exists():
        return 0
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    date = str(digest.get("date", target.isoformat()))
    n = 0
    for sec in digest.get("sections", []):
        for it in sec.get("items", []):
            if (it.get("summary") or "").strip():
                continue
            article = _load_article(content_dir, date, str(it.get("sourceUrl", "")))
            if not article:
                continue
            s = (str(article.get("aiSummary") or "").strip()
                 or (article.get("keySentences") or [""])[0].strip())
            if s:
                it["summary"] = s
                n += 1
    if n:
        digest_path.write_text(json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8")
    return n


def practice_content(
    target: dt.date,
    content_dir: Path,
    *,
    cfg: dict | None = None,
    client: httpx.Client | None = None,
) -> Path | None:
    """为某天日报生成每日一练题集，写 content/{date}/practice.json。返回产物路径或 None。

    无 DeepSeek key / AI 输出不合格时返回 None，不抛错（保证日报与剪藏仍能产出）。
    """
    digest_path = content_dir / target.isoformat() / "digest.json"
    if not digest_path.exists():
        return None
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    text = _digest_text(digest, content_dir)
    if not text.strip():
        return None
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("deepseek_api_key"):
        print("未配置 DEEPSEEK_API_KEY，跳过每日一练生成")
        return None
    questions = generate_practice(text, target.isoformat(), cfg)
    if not questions:
        print("每日一练生成失败（AI 输出不合格）")
        return None
    out_dir = content_dir / target.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "practice.json"
    payload = practice_set_json(target.isoformat(), questions, source=f"{target.isoformat()}.md")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def summary_content(
    target: dt.date,
    content_dir: Path,
    *,
    cfg: dict | None = None,
    client: httpx.Client | None = None,
) -> Path | None:
    """为某天日报生成今日速览（一句话 + 关键词），写 content/{date}/summary.json。"""
    digest_path = content_dir / target.isoformat() / "digest.json"
    if not digest_path.exists():
        return None
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    text = _digest_text(digest, content_dir)
    if not text.strip():
        return None
    cfg = cfg if cfg is not None else load_config()
    if not cfg.get("deepseek_api_key"):
        return None
    summary = generate_summary(text, cfg)
    if not summary:
        return None
    out_dir = content_dir / target.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.json"
    path.write_text(
        json.dumps({"date": target.isoformat(), **summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def quality_gate(target: dt.date, content_dir: Path) -> dict:
    """校验本次产物并写质量状态；failed 阻止自动发布，degraded 明确报告降级。"""
    report_path = content_dir / "_reports" / f"{target.isoformat()}.json"
    existing = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    report = {
        "date": target.isoformat(), "sourcesOk": 0, "sourceErrors": [],
        "candidates": 0, "articles": 0, "aiOk": 0, "aiError": 0,
        "aiFailures": [], "locationErrors": 0,
    } | existing
    schema_dir = content_dir / "schema"
    if not schema_dir.exists():
        schema_dir = Path(__file__).resolve().parents[3] / "content" / "schema"
    schemas = {
        "digest": json.loads((schema_dir / "digest.schema.json").read_text(encoding="utf-8")),
        "article": json.loads((schema_dir / "article.schema.json").read_text(encoding="utf-8")),
        "practice": json.loads((schema_dir / "practice.schema.json").read_text(encoding="utf-8")),
        "summary": json.loads((schema_dir / "summary.schema.json").read_text(encoding="utf-8")),
        "picks": json.loads((schema_dir / "picks.schema.json").read_text(encoding="utf-8")),
    }
    schema_error_list: list[dict[str, str]] = []
    semantic_error_list: list[dict[str, str]] = []
    out_dir = content_dir / target.isoformat()
    for path in sorted(out_dir.glob("*.json")) if out_dir.exists() else []:
        if classify_artifact(path) is None:
            continue
        try:
            artifact = load_artifact(path)
        except json.JSONDecodeError:
            schema_error_list.append({"file": path.name, "error": "invalid_json"})
            continue
        artifact_schema_errors = schema_errors(artifact, schemas[artifact.kind])
        schema_error_list.extend(artifact_schema_errors)
        if not artifact_schema_errors:
            semantic_error_list.extend(artifact_semantic_errors(artifact))
    volume_error_list = volume_errors(target, report_path.parent, report)
    report["schemaErrors"] = schema_error_list[:50]
    report["semanticErrors"] = semantic_error_list[:50]
    # 0018：人工标注已知原因（notes 非空）后，数量类错误降级为 degraded 而非 failed，保留记录供追溯
    if report.get("notes") and volume_error_list:
        report["volumeErrorsAcknowledged"] = volume_error_list[:50]
        report["volumeErrors"] = []
    else:
        report["volumeErrors"] = volume_error_list[:50]
    # 0022 选材口径：picks 缺失/为空 → 选材失败（degraded，不阻止原文发布）；
    # 卡片/关系提炼失败同理只降级（内容可读，只是少了记忆辅助）。
    picks_path = out_dir / "picks.json"
    curation_errors: list[str] = []
    if not picks_path.exists():
        # 只有当天确有文章产物时才要求选材（空跑/历史文件缺失不误判）
        if report.get("articles", 0) > 0:
            curation_errors.append("picks_missing")
    else:
        try:
            picks_data = json.loads(picks_path.read_text(encoding="utf-8"))
            if not picks_data.get("picked"):
                curation_errors.append("picks_empty")
        except json.JSONDecodeError:
            curation_errors.append("picks_invalid_json")
    if report.get("curation", {}).get("cardErrors") or report.get("curation", {}).get("relationErrors"):
        curation_errors.append("ai_refinement_errors")
    report["curationErrors"] = curation_errors[:10]
    if schema_error_list or semantic_error_list or volume_error_list or report.get("sourcesOk", 0) == 0 or report.get("candidates", 0) == 0:
        report["qualityStatus"] = "failed"
    elif report.get("sourceErrors") or report.get("aiError", 0) or report.get("locationErrors", 0) or curation_errors:
        report["qualityStatus"] = "degraded"
    else:
        report["qualityStatus"] = "ok"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
