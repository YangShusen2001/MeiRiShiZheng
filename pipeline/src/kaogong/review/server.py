# -*- coding: utf-8 -*-
"""本地审核服务（FastAPI）：抓取 / 读取 / 保存 / 原文预览 / 补跑 AI / 发布到 Cloudflare。

本地部署工作台：抓取 → 剪藏 → AI → 质量门禁 → 构建静态站 → wrangler 部署 Pages。
GitHub Actions 额度不可用时，这是替代每日工作流的入口（配合「启动审核.bat」）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import httpx
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ..config import load_site_config, save_site_config
from ..fonts import LOGO_TEXT, NAV_TEXT, load_config, save_config, safe_stem, subset_to_woff2
from ..pipeline import backfill_summaries, build_content, clip_content, practice_content, quality_gate, summary_content
from ..reanalyze import reanalyze_content, refresh_report_stats
from ..review_agent import apply_decisions, review_date
from ..sources import load_noise_title, load_sources, source_to_dict
from ..clip import clip_article
from ..article_ai import analyze_article
from ..deepseek import load_config as load_ai_config

ROOT = Path(__file__).resolve().parents[4]  # 仓库根（pipeline/src/kaogong/review/ 上溯 4 层）
CONTENT = ROOT / "content"
WEB = ROOT / "apps" / "web"
UI = Path(__file__).resolve().parent / "ui" / "index.html"
FONT_UPLOAD_DIR = WEB / "public" / "fonts" / "uploads"
FONT_CONFIG = WEB / "src" / "font-config.json"

def _env_clean(name: str, default: str = "") -> str:
    """读环境变量并去掉 Windows CRLF 残留的 \\r（.env.local 常为 CRLF，bat 的 for /f 会把 \\r 带进值里）。"""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.rstrip("\r") or default


# 生产 Worker 地址：默认同 wrangler.toml [vars].PUBLIC_API_URL，可用环境变量覆盖。
# 构建静态站时这个值会被烤进前端（apps/web/src/lib/api.ts 的 PUBLIC_API_BASE）。
PUBLIC_API_BASE = _env_clean("PUBLIC_API_BASE", "https://api.example.com")

# 邀请码管理：生产 Worker 的 admin 接口需要 JOB_SECRET（x-job-secret 头）鉴权。
JOB_SECRET = _env_clean("JOB_SECRET")
INVITE_ADMIN_URL = PUBLIC_API_BASE.rstrip("/") + "/api/invite/admin/invite-codes"

# Windows 无系统时区库时回退到固定 +08:00（不引入 tzdata 也能正确取北京日期）
try:
    BEIJING = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - Windows without tzdata
    BEIJING = dt.timezone(dt.timedelta(hours=8))

app = FastAPI(title="每日时政 · 本地审核")

# 兼容 CRLF 的 .env.local：启动时统一去掉环境变量尾部的 \r（bat 的 for /f 会带进来），
# 覆盖所有下游读取（DeepSeek key、Cloudflare 凭证、JOB_SECRET、PUBLIC_API_BASE 等）。
for _env_key in list(os.environ.keys()):
    _env_value = os.environ[_env_key]
    if isinstance(_env_value, str) and _env_value.endswith("\r"):
        os.environ[_env_key] = _env_value.rstrip("\r")


@app.exception_handler(Exception)
async def _unhandled_exception(request, exc: Exception):
    """统一把未捕获异常转成 JSON，避免前端收到纯文本 500。"""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"ok": False, "detail": f"服务器内部错误：{exc}"})


def beijing_today(now: dt.datetime | None = None) -> dt.date:
    """按北京时间返回「今天」；GitHub Actions 的 UTC 语义在本地不适用。"""
    return (now or dt.datetime.now(BEIJING)).astimezone(BEIJING).date()


def _has_ai_key() -> bool:
    return bool(_env_clean("DEEPSEEK_API_KEY").strip())


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(UI.read_text(encoding="utf-8"))


class FetchBody(BaseModel):
    date: str = ""  # YYYY-MM-DD，空则北京时间今天


def _parse_target(raw: str) -> dt.date:
    if not raw:
        return beijing_today()
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise HTTPException(400, f"日期格式非法：{raw}（应为 YYYY-MM-DD）")


def _report_summary(target: dt.date) -> dict:
    """读取当日质量报告并返回摘要；报告不存在时返回空。"""
    p = CONTENT / "_reports" / f"{target.isoformat()}.json"
    if not p.exists():
        return {}
    report = json.loads(p.read_text(encoding="utf-8"))
    return {
        "qualityStatus": report.get("qualityStatus"),
        "sourcesOk": report.get("sourcesOk", 0),
        "sourceErrors": report.get("sourceErrors", []),
        "candidates": report.get("candidates", 0),
        "articles": report.get("articles", 0),
        "aiOk": report.get("aiOk", 0),
        "aiError": report.get("aiError", 0),
        "aiFailures": report.get("aiFailures", []),
        "clipDetails": report.get("clipDetails", []),
        "schemaErrors": report.get("schemaErrors", []),
        "semanticErrors": report.get("semanticErrors", []),
        "volumeErrors": report.get("volumeErrors", []),
    }


# ===== 0018 审核台：条目状态 / 重试 / 排除 / 强制收录 / 报告解释 / 审计 =====

AUDIT_LOG = CONTENT / "_reports" / "audit.jsonl"

# 门禁错误的人类可读解释（Phase B）
VOLUME_ERROR_EXPLAIN = {
    "below_half_baseline": "数量不足近期基线的一半（基线=最近 5 次 ok/degraded 报告的中位数）。可能当天源产出确实少，"
                           "或某源列表页解析变化。可查看趋势图对比，或在报告里标注已知原因后放行。",
}


def _audit(target: dt.date, action: str, item_id: str = "", detail: dict | None = None) -> None:
    """操作审计（Phase C）：追加 JSONL，供条目操作历史展示。"""
    try:
        entry = {
            "ts": dt.datetime.now(BEIJING).isoformat(timespec="seconds"),
            "date": target.isoformat(),
            "action": action,
            "itemId": item_id,
            "detail": detail or {},
        }
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 审计失败不阻断操作


def _load_report(target: dt.date) -> dict:
    p = CONTENT / "_reports" / f"{target.isoformat()}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write_report(target: dt.date, report: dict) -> None:
    p = CONTENT / "_reports" / f"{target.isoformat()}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_digest(target: dt.date) -> dict:
    p = CONTENT / target.isoformat() / "digest.json"
    if not p.exists():
        raise HTTPException(404, "该日期无日报")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_digest(target: dt.date, digest: dict) -> None:
    (CONTENT / target.isoformat() / "digest.json").write_text(
        json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _find_item(digest: dict, item_id: str) -> tuple[int, int, dict] | None:
    """按条目 id（MD5(sourceUrl)[:10]）定位 digest 条目，返回 (sectionIndex, itemIndex, item)。"""
    for si, sec in enumerate(digest.get("sections", [])):
        for ii, it in enumerate(sec.get("items", [])):
            if _article_id(it.get("sourceUrl") or "") == item_id:
                return si, ii, it
    return None


def _load_article_file(day: Path, aid: str) -> dict | None:
    p = day / f"article-{aid}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _suggest_actions(clip: dict | None, article: dict | None, excluded: bool) -> list[str]:
    """错误分类 → 建议动作（Phase B）：retry / exclude / force-include / restore。"""
    if excluded:
        return ["restore"]
    if clip and clip.get("status") != "ok":
        reason = str(clip.get("reason") or clip.get("error") or "")
        if reason.startswith("fetch_failed"):
            return ["retry"]
        if reason.startswith("video_no_text"):
            return ["exclude"]
        if reason.startswith("too_short"):
            return ["force-include", "exclude"]
        return ["retry", "exclude"]
    if article and article.get("aiStatus") != "ok":
        return ["retry"]
    return []


def _retry_one(target: dt.date, item_id: str, allow_single: bool = False) -> dict:
    """重试单条：ai_error 只重分析；clip_error 重新剪藏 + AI；allow_single=强制收录。"""
    digest = _load_digest(target)
    found = _find_item(digest, item_id)
    if not found:
        raise HTTPException(404, "无该条目")
    _, _, it = found
    url = it.get("sourceUrl") or ""
    aid = _article_id(url)
    day = CONTENT / target.isoformat()
    title = it.get("title", "")
    ai_cfg = load_ai_config()
    article_path = day / f"article-{aid}.json"
    existing = _load_article_file(day, aid)

    # 已有剪藏（ai_error 场景）：只重跑 AI
    if existing and existing.get("status") == "ok" and not allow_single:
        updated = analyze_article(existing, ai_cfg)
        article_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        _update_report_clip(target, aid, "ok", "")
        _audit(target, "retry-ai", aid, {"title": title, "aiStatus": updated.get("aiStatus")})
        return {
            "id": aid, "ok": True, "clipStatus": "ok", "aiStatus": updated.get("aiStatus"),
            "actions": _suggest_actions({"status": "ok"}, updated, False),
        }

    # 重新剪藏（clip_error / 强制收录）
    client = httpx.Client(timeout=30, follow_redirects=True)
    try:
        clip = clip_article(url, title, target.isoformat(), client=client, allow_single=allow_single)
    finally:
        client.close()
    if clip.get("status") == "ok":
        article = analyze_article(clip, ai_cfg)
        article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
        _update_report_clip(target, aid, "ok", "")
        _audit(target, "force-include" if allow_single else "retry-clip", aid, {"title": title, "aiStatus": article.get("aiStatus")})
        return {"id": aid, "ok": True, "clipStatus": "ok", "aiStatus": article.get("aiStatus"), "actions": []}
    error = str(clip.get("error", "clip_error"))[:120]
    _update_report_clip(target, aid, "clip_error", error)
    _audit(target, "retry-clip", aid, {"title": title, "error": error})
    return {"id": aid, "ok": True, "clipStatus": "clip_error", "clipError": error, "actions": _suggest_actions(clip, None, False)}


def _update_report_clip(target: dt.date, aid: str, status: str, reason: str) -> None:
    """重试后刷新报告：替换 clipDetails 中该条目，AI 统计按 article 文件实际状态重算。"""
    report = _load_report(target)
    details = [d for d in report.get("clipDetails", []) if d.get("id") != aid]
    details.append({"id": aid, "title": "", "status": status, "reason": reason[:120]})
    report["clipDetails"] = details
    _write_report(target, report)
    refresh_report_stats(target, CONTENT)


@app.get("/api/items/{date}")
def api_items(date: str) -> dict:
    """统一条目视图（Phase A）：digest 条目 + 剪藏/AI 状态 + 建议动作 + 排除标记。"""
    target = _parse_target(date)
    digest = _load_digest(target)
    report = _load_report(target)
    clip_by_id = {c.get("id"): c for c in report.get("clipDetails", [])}
    excluded = {e.get("id"): e for e in report.get("excluded", [])}
    day = CONTENT / target.isoformat()
    items: list[dict] = []
    for si, sec in enumerate(digest.get("sections", [])):
        for ii, it in enumerate(sec.get("items", [])):
            aid = _article_id(it.get("sourceUrl") or "")
            clip = clip_by_id.get(aid)
            article = _load_article_file(day, aid) if aid else None
            is_excluded = aid in excluded
            clip_status = None
            clip_error = None
            if clip:
                clip_status = clip.get("status")
                clip_error = clip.get("reason") if clip_status != "ok" else None
            items.append({
                "id": aid,
                "sectionIndex": si,
                "itemIndex": ii,
                "title": it.get("title", ""),
                "sourceUrl": it.get("sourceUrl", ""),
                "clipStatus": clip_status,
                "clipError": clip_error,
                "aiStatus": (article or {}).get("aiStatus"),
                "aiError": (article or {}).get("aiError"),
                "excluded": is_excluded,
                "excludeReason": excluded.get(aid, {}).get("reason", ""),
                "actions": _suggest_actions(clip, article, is_excluded),
            })
    return {"ok": True, "date": target.isoformat(), "items": items, "quality": _report_summary(target)}


@app.post("/api/items/{date}/{id}/retry")
def api_item_retry(date: str, id: str) -> dict:
    """单条重试：clip_error 重剪藏+AI；ai_error 重分析。随后重算质量门禁。"""
    target = _parse_target(date)
    try:
        result = _retry_one(target, id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"重试失败：{exc}") from exc
    quality_gate(target, CONTENT)
    return {**result, "quality": _report_summary(target)}


@app.post("/api/items/{date}/{id}/force-include")
def api_item_force_include(date: str, id: str) -> dict:
    """强制收录：clip 门槛放行（单段正文也收录，如 gd 短讯）。"""
    target = _parse_target(date)
    try:
        result = _retry_one(target, id, allow_single=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"强制收录失败：{exc}") from exc
    quality_gate(target, CONTENT)
    return {**result, "quality": _report_summary(target)}


class ExcludeBody(BaseModel):
    reason: str = "人工排除"


@app.post("/api/items/{date}/{id}/exclude")
def api_item_exclude(date: str, id: str, body: ExcludeBody) -> dict:
    """排除条目：从 digest 移除（发布即生效），原条目备份在 report.excluded 可恢复。"""
    target = _parse_target(date)
    digest = _load_digest(target)
    found = _find_item(digest, id)
    if not found:
        raise HTTPException(404, "无该条目（可能已被排除）")
    si, ii, it = found
    report = _load_report(target)
    excluded = report.get("excluded", [])
    if not any(e.get("id") == id for e in excluded):
        excluded.append({
            "id": id,
            "title": it.get("title", ""),
            "reason": body.reason or "人工排除",
            "at": dt.datetime.now(BEIJING).isoformat(timespec="seconds"),
            "si": si,
            "ii": ii,
            "item": it,
        })
    report["excluded"] = excluded
    _write_report(target, report)
    digest["sections"][si]["items"].pop(ii)
    _write_digest(target, digest)
    _audit(target, "exclude", id, {"title": it.get("title", ""), "reason": body.reason})
    return {"ok": True, "id": id}


@app.post("/api/items/{date}/{id}/restore")
def api_item_restore(date: str, id: str) -> dict:
    """恢复被排除的条目：按原 section/index 插回 digest。"""
    target = _parse_target(date)
    report = _load_report(target)
    excluded = report.get("excluded", [])
    entry = next((e for e in excluded if e.get("id") == id), None)
    if not entry:
        raise HTTPException(404, "该条目未被排除")
    digest = _load_digest(target)
    sections = digest.get("sections", [])
    si = min(int(entry.get("si", 0)), max(0, len(sections) - 1)) if sections else 0
    items = sections[si]["items"] if sections else []
    ii = min(int(entry.get("ii", len(items))), len(items))
    items.insert(ii, entry.get("item") or {})
    report["excluded"] = [e for e in excluded if e.get("id") != id]
    _write_report(target, report)
    _write_digest(target, digest)
    _audit(target, "restore", id, {"title": entry.get("title", "")})
    return {"ok": True, "id": id}


class RetryFailedBody(BaseModel):
    date: str = ""


@app.post("/api/items/{date}/retry-failed")
def api_retry_failed(date: str) -> dict:
    """批量重试全部失败条目（GitHub Actions「rerun failed」语义）。"""
    target = _parse_target(date)
    view = api_items(target.isoformat())
    failed = [
        it for it in view["items"]
        if not it["excluded"] and (it["clipStatus"] == "clip_error" or it["aiStatus"] == "error")
    ]
    results: list[dict] = []
    for it in failed:
        try:
            results.append(_retry_one(target, it["id"]))
        except Exception as exc:  # 单条失败不阻断批量
            results.append({"id": it["id"], "ok": False, "error": str(exc)[:100]})
    quality_gate(target, CONTENT)
    _audit(target, "retry-failed", "", {"total": len(failed)})
    return {"ok": True, "total": len(failed), "results": results, "quality": _report_summary(target)}


@app.get("/api/reports/{date}")
def api_report(date: str) -> dict:
    """报告详情（Phase B）：门禁逐条错误的人类可读解释 + 建议动作 + 失败条目 + 已标注原因。"""
    target = _parse_target(date)
    report = _load_report(target)
    if not report:
        raise HTTPException(404, "该日期无质量报告")
    errors: list[dict] = []
    for e in report.get("volumeErrors", []):
        errors.append({
            "kind": "volume", "metric": e.get("metric"), "error": e.get("error"),
            "baseline": e.get("baseline"), "window": e.get("window"),
            "explain": VOLUME_ERROR_EXPLAIN.get(e.get("error", ""), ""),
            "action": "核对来源产出或标注已知原因后放行",
        })
    for e in report.get("schemaErrors", []):
        errors.append({"kind": "schema", "file": e.get("file"), "error": e.get("error"),
                       "explain": "产物不符合 JSON Schema，需重新抓取或修复数据。", "action": "重新抓取"})
    for e in report.get("semanticErrors", []):
        errors.append({"kind": "semantic", "file": e.get("file"), "error": e.get("error"),
                       "explain": "语义校验未通过（摘要长度/标注定位等），需补跑 AI。", "action": "补跑 AI"})
    for e in report.get("sourceErrors", []):
        errors.append({"kind": "source", "source": e.get("source"), "error": e.get("error"),
                       "explain": "来源抓取失败，该源当天无候选。", "action": "检查该源列表页"})
    acknowledged = report.get("volumeErrorsAcknowledged", [])
    return {
        "ok": True,
        "date": target.isoformat(),
        "quality": _report_summary(target),
        "errors": errors,
        "acknowledgedVolumeErrors": acknowledged,
        "notes": report.get("notes", []),
    }


class NoteBody(BaseModel):
    text: str


@app.post("/api/reports/{date}/note")
def api_report_note(date: str, body: NoteBody) -> dict:
    """标注已知原因（如「当天源产出少」）：标注后 volume 错误降级为 degraded，不再拦截发布。"""
    target = _parse_target(date)
    report = _load_report(target)
    if not report:
        raise HTTPException(404, "该日期无质量报告")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "标注内容不能为空")
    notes = report.get("notes", [])
    if text not in notes:
        notes.append(text)
    report["notes"] = notes
    _write_report(target, report)
    quality_gate(target, CONTENT)  # notes 存在 → volume 错误降级
    _audit(target, "note", "", {"text": text})
    return {"ok": True, "notes": notes, "quality": _report_summary(target)}


@app.get("/api/items/{date}/{id}/history")
def api_item_history(date: str, id: str) -> dict:
    """条目操作历史（Phase C）：从 audit.jsonl 过滤。"""
    target = _parse_target(date)
    rows: list[dict] = []
    if AUDIT_LOG.exists():
        for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("date") == target.isoformat() and entry.get("itemId") == id:
                rows.append(entry)
    return {"ok": True, "history": rows[-50:]}


@app.post("/api/fetch")
def api_fetch(body: FetchBody) -> dict:
    """抓取当日来源 → 组装日报 → 剪藏原文 → AI 分析 → 每日一练 → 质量门禁。

    返回 qualityStatus（ok / degraded / failed）。failed 时「发布到 CF」会被拒绝，
    必须先处理质量问题（如补跑 AI、检查来源）。
    """
    target = _parse_target(body.date)
    digest_path = build_content(target, CONTENT)
    n_clips = clip_content(target, CONTENT)
    backfill_summaries(target, CONTENT)
    practice_content(target, CONTENT)
    summary_content(target, CONTENT)
    quality_gate(target, CONTENT)
    _audit(target, "fetch", "", {"clips": n_clips})
    summary = _report_summary(target)
    return {
        "ok": True,
        "date": target.isoformat(),
        "digest": str(digest_path),
        "clips": n_clips,
        "aiKeyConfigured": _has_ai_key(),
        "quality": summary,
    }


class ReanalyzeBody(BaseModel):
    date: str = ""  # YYYY-MM-DD，空则北京时间今天
    force: bool = False  # True：已成功的文章也重新分析（基于干净正文）


@app.post("/api/reanalyze")
def api_reanalyze(body: ReanalyzeBody) -> dict:
    """对指定日期已入库的原文补跑 AI（不重新抓取），随后重算质量门禁。

    默认只清洗正文并把缺失/失败的重新分析（无 key 也能清洗已 ok 文章）；
    force=True 时连已 ok 文章也重新调用 AI（需 DEEPSEEK_API_KEY）。
    """
    target = _parse_target(body.date)
    if body.force and not _has_ai_key():
        raise HTTPException(400, "未配置 DEEPSEEK_API_KEY：force 补跑需要调用 AI")
    rewritten = reanalyze_content(target, CONTENT, force_ai=body.force)
    quality_gate(target, CONTENT)
    _audit(target, "reanalyze", "", {"rewritten": rewritten, "force": body.force})
    return {
        "ok": True,
        "date": target.isoformat(),
        "rewritten": rewritten,
        "quality": _report_summary(target),
    }


@app.get("/api/dates")
def api_dates() -> dict:
    dates = sorted(
        (d.name for d in CONTENT.iterdir() if (d / "digest.json").exists()),
        reverse=True,
    )
    return {"dates": dates}


@app.get("/api/digest/{date}")
def api_digest(date: str) -> dict:
    p = CONTENT / date / "digest.json"
    if not p.exists():
        raise HTTPException(404, "该日期无日报")
    return json.loads(p.read_text(encoding="utf-8"))


class DigestBody(BaseModel):
    date: str
    digest: dict


@app.post("/api/digest")
def api_save_digest(body: DigestBody) -> dict:
    p = CONTENT / body.date / "digest.json"
    p.write_text(json.dumps(body.digest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@app.get("/api/article/{id}")
def api_article(id: str) -> dict:
    for d in CONTENT.iterdir():
        p = d / f"article-{id}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise HTTPException(404, "无该原文")


def _article_id(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:10]


@app.get("/api/article-by-url")
def api_article_by_url(url: str) -> dict:
    """按原文 URL 解析出 article id 并返回剪藏原文，避免前端反复查 digest 找 _articleId。"""
    aid = _article_id(url)
    for d in CONTENT.iterdir():
        p = d / f"article-{aid}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    raise HTTPException(404, "无该原文")


# —— 字体管理 ——

@app.get("/api/fonts")
def api_fonts() -> dict:
    """列出已上传字体 + 当前配置。"""
    fonts: list[str] = []
    if FONT_UPLOAD_DIR.exists():
        fonts = sorted(p.name for p in FONT_UPLOAD_DIR.glob("*.woff2"))
    return {"fonts": fonts, "config": load_config(FONT_CONFIG)}


def _safe_unlink(p: Path) -> None:
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass  # Windows 下文件句柄可能短暂占用，忽略清理失败


@app.post("/api/fonts/upload")
async def api_font_upload(file: UploadFile = File(...)) -> dict:
    """上传 TTF → 子集化到 logo+导航用字 → 存 WOFF2。"""
    stem = safe_stem(file.filename or "font")
    FONT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FONT_UPLOAD_DIR / f"{stem}.ttf"
    try:
        tmp.write_bytes(await file.read())
        out = FONT_UPLOAD_DIR / f"{stem}.woff2"
        subset_to_woff2(tmp, LOGO_TEXT + NAV_TEXT, out)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"字体子集化失败：{exc}") from exc
    finally:
        _safe_unlink(tmp)
    return {"ok": True, "file": out.name}


class FontConfigBody(BaseModel):
    logo: str | None = None   # 文件名（xxx.woff2）或 "default" 恢复默认
    nav: str | None = None


@app.post("/api/fonts/config")
def api_font_config(body: FontConfigBody) -> dict:
    """设置 logo/导航字体；传 "default" 表示恢复系统默认。"""

    def resolve(value: str | None) -> str | None:
        return None if value in (None, "", "default", "null") else value

    cfg = load_config(FONT_CONFIG)
    if body.logo is not None:
        cfg["logo"] = resolve(body.logo)
    if body.nav is not None:
        cfg["nav"] = resolve(body.nav)
    save_config(FONT_CONFIG, cfg)
    return {"ok": True, "config": cfg}


@app.get("/fonts/uploads/{filename}")
def serve_uploaded_font(filename: str):
    """托管已上传的 WOFF2 字体，供审核界面里的字体预览 @font-face 加载。"""
    p = FONT_UPLOAD_DIR / filename
    if not p.exists() or not p.is_file():
        raise HTTPException(404, "字体不存在")
    return FileResponse(p, media_type="font/woff2")


# —— 站点配置（新闻源 + 内容筛选 + 显示开关）——

@app.get("/api/config")
def api_config() -> dict:
    """返回当前站点配置：新闻源（含默认序列化）、内容筛选关键词、显示开关。"""
    cfg = load_site_config()
    return {
        "sources": [source_to_dict(s) for s in load_sources(cfg)],
        "noiseTitle": list(load_noise_title(cfg)),
        "carousel": bool(cfg.get("carousel", True)),
        "aiBanner": bool(cfg.get("aiBanner", True)),
    }


class SiteConfigBody(BaseModel):
    sources: list | None = None
    noiseTitle: list | None = None
    carousel: bool | None = None
    aiBanner: bool | None = None


@app.post("/api/config")
def api_save_config(body: SiteConfigBody) -> dict:
    """保存站点配置（只更新传入的字段），写回 pipeline/config.json。"""
    cfg = load_site_config()
    if body.sources is not None:
        cfg["sources"] = body.sources
    if body.noiseTitle is not None:
        cfg["noiseTitle"] = body.noiseTitle
    if body.carousel is not None:
        cfg["carousel"] = body.carousel
    if body.aiBanner is not None:
        cfg["aiBanner"] = body.aiBanner
    save_site_config(cfg)
    # 同步一份前端构建读取的开关配置（apps/web/src/site-config.json）
    web_cfg = WEB / "src" / "site-config.json"
    web_cfg.parent.mkdir(parents=True, exist_ok=True)
    web_cfg.write_text(
        json.dumps({"carousel": bool(cfg.get("carousel", True)), "aiBanner": bool(cfg.get("aiBanner", True))}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "config": cfg}


@app.get("/api/stats")
def api_stats() -> dict:
    """数据统计：读 content/_reports/*.json 聚合每日指标。"""
    report_dir = CONTENT / "_reports"
    out: list[dict] = []
    if report_dir.exists():
        for p in sorted(report_dir.glob("*.json")):
            try:
                report = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({
                "date": p.stem,
                "candidates": report.get("candidates", 0),
                "articles": report.get("articles", 0),
                "aiOk": report.get("aiOk", 0),
                "aiError": report.get("aiError", 0),
                "qualityStatus": report.get("qualityStatus", ""),
            })
    return {"ok": True, "data": out}


def _latest_failed_report() -> dict | None:
    """最近一份 qualityStatus=failed 的报告；发布前用它拦住坏内容。"""
    report_dir = CONTENT / "_reports"
    if not report_dir.exists():
        return None
    for p in sorted(report_dir.glob("*.json"), reverse=True):
        try:
            report = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if report.get("qualityStatus") == "failed":
            return {"date": p.stem, **report}
    return None


def _run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    env = dict(os.environ)
    env["PUBLIC_API_BASE"] = PUBLIC_API_BASE
    # 强制 UTF-8 + 容错解码：pnpm/astro 输出 UTF-8，中文 Windows 默认 GBK 会解码失败导致 stdout=None
    r = subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    log = ((r.stdout or "") + (r.stderr or ""))[-3000:]
    return r.returncode == 0, log


# 发布进度（后台线程 + 前端轮询，避免构建部署期间前端卡死）
_publish_state: dict = {"running": False, "step": "", "log": "", "done": False, "ok": False}


def _publish_worker() -> None:
    pnpm = "pnpm.cmd" if os.name == "nt" else "pnpm"
    try:
        _publish_state["step"] = "构建"
        _publish_state["log"] = "正在构建静态站（astro build，约 1~3 分钟）…"
        ok, log = _run([pnpm, "build"], WEB)
        _publish_state["log"] = log
        if not ok:
            _publish_state.update({"done": True, "ok": False})
            return
        _publish_state["step"] = "部署"
        _publish_state["log"] = "正在部署到 Cloudflare Pages…"
        ok, log = _run(
            [pnpm, "exec", "wrangler", "pages", "deploy", "dist", "--project-name", "kaogong-web", "--branch", "main"],
            WEB,
        )
        _publish_state["log"] = log
        _publish_state.update({"done": True, "ok": ok})
        if ok:
            _audit(beijing_today(), "publish", "", {"project": "kaogong-web"})
    except Exception as exc:  # pragma: no cover - 兜底
        _publish_state.update({"done": True, "ok": False, "log": f"发布异常：{exc}"})
    finally:
        _publish_state["running"] = False


@app.post("/api/publish")
def api_publish() -> dict:
    """构建静态站并部署到 Cloudflare Pages（后台执行，前端轮询进度）。

    前置保护：最近一期质量门禁 failed 时拒绝发布，避免把坏内容推上线。
    """
    if _publish_state["running"]:
        return {"ok": False, "step": "运行中", "log": "发布已在进行中，请稍候。"}
    failed = _latest_failed_report()
    if failed is not None:
        return {
            "ok": False,
            "step": "质量门禁",
            "log": f"最近一期 {failed['date']} 质量门禁为 failed，已阻止发布。\n"
                   f"候选 {failed.get('candidates', 0)} / 文章 {failed.get('articles', 0)} / "
                   f"AI 失败 {failed.get('aiError', 0)}\n"
                   f"请先在审核界面「抓取」或「补跑 AI」处理，或在 content/_reports 确认该期无需发布。",
        }
    missing = [k for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID") if not _env_clean(k)]
    if missing:
        return {
            "ok": False,
            "step": "凭证检查",
            "log": "缺少 Cloudflare 凭证：" + "、".join(missing)
                   + "\n请把它们加到仓库根目录的 .env.local 后重启审核服务，再点发布。",
        }
    _publish_state.update({"running": True, "step": "准备", "log": "准备发布…", "done": False, "ok": False})
    threading.Thread(target=_publish_worker, daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/api/publish/status")
def api_publish_status() -> dict:
    """发布进度查询（前端轮询）。"""
    return _publish_state


def _port_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


@app.post("/api/preview")
def api_preview() -> dict:
    """打开本地前端（每日时政网页）；dev 服务器未启动则先拉起它。"""
    port = 4321
    if not _port_open(port):
        pnpm = "pnpm.cmd" if os.name == "nt" else "pnpm"
        env = dict(os.environ)
        env["PUBLIC_API_BASE"] = "http://127.0.0.1:8787"
        kwargs = {"cwd": str(WEB), "env": env, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([pnpm, "dev", "--host", "127.0.0.1"], **kwargs)
        for _ in range(40):
            if _port_open(port):
                break
            time.sleep(0.5)
    webbrowser.open(f"http://127.0.0.1:{port}")
    return {"ok": True, "url": f"http://127.0.0.1:{port}"}


# —— 邀请码管理（代理到生产 Worker admin API，需 JOB_SECRET）——

def _invite_admin_headers() -> dict:
    if not JOB_SECRET:
        raise HTTPException(400, "未配置 JOB_SECRET 环境变量，无法管理邀请码（请加到 .env.local 后重启审核服务）")
    return {"x-job-secret": JOB_SECRET, "content-type": "application/json"}


def _invite_admin(method: str) -> dict:
    try:
        resp = httpx.request(method, INVITE_ADMIN_URL, headers=_invite_admin_headers(), timeout=30)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"请求生产 Worker 失败：{exc}")
    if resp.status_code >= 400:
        raise HTTPException(502, f"Worker 返回 {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except Exception:
        raise HTTPException(502, f"Worker 返回非 JSON：{resp.text[:300]}")


@app.get("/api/invite-codes")
def api_invite_codes() -> dict:
    """列出全部邀请码及剩余次数（转发到生产 Worker admin API）。"""
    return _invite_admin("GET")


@app.post("/api/invite-codes")
def api_invite_codes_create() -> dict:
    """生成一个新的共享邀请码（100 次），返回明文码。"""
    return _invite_admin("POST")


# —— AI 审核（Phase 1：只判不改，后台线程 + 前端轮询）——

_review_state: dict = {"running": False, "step": "", "log": "", "done": False, "ok": False, "report": None}


def _review_worker(target: dt.date) -> None:
    try:
        _review_state["step"] = "判质量"
        _review_state["log"] = "正在逐条判定文章质量（只判不改）…"
        cfg = {"deepseek_api_key": _env_clean("DEEPSEEK_API_KEY")}
        decisions = review_date(target, CONTENT, cfg)
        counts: dict[str, int] = {}
        for decision in decisions:
            verdict = str(decision.get("verdict", "needs_human"))
            counts[verdict] = counts.get(verdict, 0) + 1
        _review_state["report"] = {
            "date": target.isoformat(),
            "agent": "review-agent-v1",
            "decisions": decisions,
            "summary": counts,
        }
        _review_state["log"] = f"判定完成：共 {len(decisions)} 条 → {counts}"
        _review_state.update({"done": True, "ok": True})
    except Exception as exc:  # pragma: no cover - 兜底
        _review_state.update({"done": True, "ok": False, "log": f"审核异常：{exc}"})
    finally:
        _review_state["running"] = False


class ReviewAgentBody(BaseModel):
    date: str = ""


@app.post("/api/review-agent")
def api_review_agent(body: ReviewAgentBody) -> dict:
    """对指定日期日报做 AI 审核（只判不改），后台执行、前端轮询状态。"""
    if _review_state["running"]:
        return {"ok": False, "step": "运行中", "log": "AI 审核已在进行中，请稍候。"}
    if not _has_ai_key():
        return {"ok": False, "step": "凭证检查", "log": "未配置 DEEPSEEK_API_KEY，无法运行 AI 审核。"}
    target = _parse_target(body.date)
    _review_state.update({"running": True, "step": "准备", "log": "准备审核…", "done": False, "ok": False, "report": None})
    threading.Thread(target=_review_worker, args=(target,), daemon=True).start()
    return {"ok": True, "started": True}


@app.get("/api/review-agent/status")
def api_review_agent_status() -> dict:
    """AI 审核进度查询（前端轮询）。"""
    return _review_state


@app.post("/api/review-agent/apply")
def api_review_agent_apply(body: ReviewAgentBody) -> dict:
    """应用最近一次 AI 审核结果：rewrite 改标题/摘要、drop 移除条目，并备份原文件供回退。"""
    report = _review_state.get("report")
    if not report or not report.get("decisions"):
        return {"ok": False, "log": "还没有 AI 审核结果，请先点「开始 AI 审核」。"}
    target = _parse_target(body.date)
    day = CONTENT / target.isoformat()
    digest_path = day / "digest.json"
    if not digest_path.exists():
        return {"ok": False, "log": "该日期无日报，无法应用。"}
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    decisions = report["decisions"]

    # 备份：digest + 标题将被改写的文章（保留原样供回退）
    digest_bak = day / "digest.json.bak"
    if not digest_bak.exists():
        shutil.copy2(digest_path, digest_bak)
    for decision in decisions:
        if decision.get("verdict") == "rewrite" and decision.get("newTitle") and decision.get("articleId"):
            article_path = day / f"article-{decision['articleId']}.json"
            if article_path.exists() and not (day / f"article-{decision['articleId']}.json.bak").exists():
                shutil.copy2(article_path, day / f"article-{decision['articleId']}.json.bak")

    new_digest, changes = apply_decisions(digest, decisions, day)
    digest_path.write_text(json.dumps(new_digest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Phase 3：rerun 补跑失败 AI + 质量门禁验证闭环
    rerun = any(d.get("verdict") == "rerun" for d in decisions)
    rerun_written = 0
    if rerun and _has_ai_key():
        rerun_written = reanalyze_content(target, CONTENT)
    quality = quality_gate(target, CONTENT)
    quality_summary = {
        "qualityStatus": quality.get("qualityStatus"),
        "schemaErrors": len(quality.get("schemaErrors", [])),
        "semanticErrors": len(quality.get("semanticErrors", [])),
        "aiError": quality.get("aiError", 0),
    }

    _review_state["diff"] = changes
    _review_state["applied"] = True
    _audit(target, "review-apply", "", {"changes": len(changes), "rerun": rerun})
    return {
        "ok": True, "changes": changes, "appliedCount": len(changes),
        "rerun": rerun, "rerunWritten": rerun_written,
        "quality": quality_summary,
    }


@app.post("/api/review-agent/rollback")
def api_review_agent_rollback(body: ReviewAgentBody) -> dict:
    """回退：用 .bak 备份恢复原 digest 与文章标题。"""
    target = _parse_target(body.date)
    day = CONTENT / target.isoformat()
    restored: list[str] = []
    if day.exists():
        for bak in sorted(day.glob("*.bak")):
            original = day / bak.name[:-4]  # 去掉 .bak 后缀
            shutil.copy2(bak, original)
            restored.append(original.name)
    _review_state["applied"] = False
    _review_state["diff"] = None
    _audit(target, "review-rollback", "", {"restored": restored})
    return {"ok": True, "restored": restored}
