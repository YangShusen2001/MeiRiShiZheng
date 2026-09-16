# -*- coding: utf-8 -*-
"""内容管道编排：抓取 → 组装 → 写 content/ JSON。

这是「抓取逻辑 A」的顶层：把所有源跑一遍，只保留目标日期，
交给 build_digest 组装，最后写成前端消费的 content/{date}/digest.json。

v2.1 §3.3（配额顺序缺陷修复）：fetch 层只做标题级判断（tier/栏目/日期/噪声）
+ MAX_PRECLIP 安全阀，不再做每源配额与槽位 CAPS——「留谁砍谁」需要正文信息
（密度/字数），配额与 CAPS 后移至 clip 层 _apply_quota_and_caps（T04），按
total_chars 降序截断。v2 的 fetch 层列表序截断在黄金样本日误杀 3 篇 IN
（政绩观 news.cn 第 5 / 塞上江南 news.cn 第 6 / 琴澳 dayoo 第 4）。
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
from .deepseek import Cfg, load_config
from .density import density_gate, total_chars
from .models import Candidate
from .practice import generate_practice, practice_set_json
from .quality import artifact_semantic_errors, classify_artifact, load_artifact, schema_errors, volume_errors
from .summary import generate_summary
from .config import load_site_config
from .sources import Source, fetch_source, is_noise_title, load_noise_title, load_sources

# 每槽位最多收录条数（v2 §3.3 取值不变：pol 25→8 严限；essay 10 承接大洋网+
# 川观理论栏目流入；gd/sc/js 随地方分节删除；gdp 15→5 降配；其余不变）。
# v2.1 §3.2-A1：执行点从 fetch 层 _pick_top 后移至 clip 层 _apply_quota_and_caps
# （T04）——fetch 层截断在无 DeepSeek key 时退化为列表序（值盲截断），后移版按
# total_chars 降序，语义从「控抓取」变「控 digest 规模」。常量保留供 T04 消费。
CAPS = {
    "pol": 8, "gov": 10, "shi": 18, "qst": 12, "xh": 18, "rm": 12,
    "byt": 8, "essay": 10, "gdp": 5, "nf": 12,
}

# v2.1 §3.7：每源配额取值不变（默认 ≤3，理论刊物/政策原文精品率高放宽到 4），
# 但执行位置、分组键与排序变——计量对象 = 密度门禁过滤后的净流量，分组键 =
# 文章 URL host（去 www 前缀；digest 契约无源名字段，且大洋网源页/文章 host
# 分裂、新华三源共享 news.cn，只有 host 在纯 digest JSON 上稳定计量），按
# total_chars 降序截断，由 clip 层 _apply_quota_and_caps（T04）消费。
# v2 的 fetch 层列表序配额（先到先得 = 发布时间倒序，与价值无关）是本返工摘除的对象。
PER_SOURCE_QUOTA = 3
QUOTA_OVERRIDES = {
    "qstheory.cn": 4, "banyuetan.org": 4, "gov.cn": 4,
}

# v2.1 §3.3/§3.4：fetch 层安全阀——防单日刷屏（源故障/目录页改版）拖垮
# pass-1 全量剪藏。正常日 ~22 条远不触发；仅作全局上限兜底，不做价值判断。
MAX_PRECLIP = 48

MAX_AI_FAILURES = 50


def _host_of(url: str) -> str:
    """从 URL 提取 host（小写），取不到返回空串。

    v2.1：source_name 缺失时的配额分组回退键，由 clip 层
    _apply_quota_and_caps（T04）消费。
    """
    m = re.search(r"https?://([^/?#]+)", url or "", re.IGNORECASE)
    return m.group(1).lower() if m else ""


def _quota_group(url: str) -> str:
    """配额分组键 = 文章 URL host（去 www 前缀）。

    v2.1 §3.7：digest 契约无源名字段，且大洋网源页（www.dayoo.com）与文章
    （news.dayoo.com）host 分裂、新华三源共享 news.cn——只有 host 在纯
    digest JSON 上稳定。新华三源共享 news.cn → 配额合并为一组（黄金样本 IN
    恰为该组 total_chars 最长两条，降序截断下安全）。
    """
    host = _host_of(url)
    return host[4:] if host.startswith("www.") else host


# 旧版分节 id（gold 日 digest 为旧管道产物）：大洋网在 guangdong、川观在 sichuan。
# v2.1 拍板⑧：保留地方栏目的文章统一进申论精读 → 两者都映射 essay 槽位。
_LEGACY_ESSAY_SECTIONS = frozenset({"guangdong", "sichuan"})


def _slot_of(url: str, section_id: str) -> str:
    """从 digest 分节 id + URL 推导 CAPS 槽位键（digest 契约无 slot 字段）。

    essay/guangdong/sichuan→essay（拍板⑧：地方栏目统一进申论精读）；
    policy→gdp；national→（配额组恰为 gov.cn 才是 gov；gd.gov.cn 是独立
    host，不得误匹配 gov.cn）。
    """
    if section_id == "policy":
        return "gdp"
    if section_id == "essay" or section_id in _LEGACY_ESSAY_SECTIONS:
        return "essay"
    return "gov" if _quota_group(url) == "gov.cn" else "pol"


def _apply_quota_and_caps(
    clipped: list[dict], section_by_url: dict[str, str],
) -> tuple[list[dict], list[dict]]:
    """密度门禁后的每源配额与槽位 CAPS（v2.1 §3.2-A1，T04 执行点）。

    排序键 = total_chars 降序（复用密度已算的正文指标，零额外启发式）；
    IN 类深度长文通常更长，v2 的列表序截断（=发布时间倒序）在黄金样本日
    误杀 3 篇 IN 的缺陷在此修正。返回 (final, cut)：final 保持原相对顺序，
    cut 为超额被拒条目（供 report["clip"]["quotaRejected"]）。
    """
    survivors = sorted(clipped, key=lambda c: -total_chars(c.get("paragraphs") or []))
    kept: list[dict] = []
    cut: list[dict] = []
    per_group: dict[str, int] = {}
    per_slot: dict[str, int] = {}
    for c in survivors:
        url = str(c.get("url", ""))
        slot = _slot_of(url, section_by_url.get(url, ""))
        cap = CAPS.get(slot)
        if cap is not None and per_slot.get(slot, 0) >= cap:
            cut.append(c)
            continue
        group = _quota_group(url)
        limit = QUOTA_OVERRIDES.get(group, PER_SOURCE_QUOTA)
        if per_group.get(group, 0) >= limit:
            cut.append(c)
            continue
        per_slot[slot] = per_slot.get(slot, 0) + 1
        per_group[group] = per_group.get(group, 0) + 1
        kept.append(c)
    order = {id(c): i for i, c in enumerate(clipped)}
    kept.sort(key=lambda c: order[id(c)])
    return kept, cut


def _preclip_ceiling(cands: list[Candidate], ceiling: int = MAX_PRECLIP) -> list[Candidate]:
    """fetch 层安全阀：候选总量超过 ceiling 时按抓取顺序截断（v2.1 §3.4）。

    正常日 ~22 条远不触发；仅防单日刷屏拖垮 clip 层 pass-1 全量剪藏。
    这是 fetch 层唯一的总量控制——每源配额与槽位 CAPS 已后移至 clip 层
    _apply_quota_and_caps（T04），fetch 层不做任何价值判断、零 AI 调用。
    """
    if len(cands) <= ceiling:
        return cands
    return cands[:ceiling]


def fetch_candidates(
    target: dt.date, *, client: httpx.Client | None = None, report: dict | None = None,
    config: dict | None = None, cfg: Cfg | None = None,
) -> list[Candidate]:
    """跑全部源（来源可后台配置），只保留 target 当日的候选，过 MAX_PRECLIP 安全阀。

    单源失败不影响其余。v2.1 §3.3：fetch 层零 AI 调用（配额/CAPS 已后移 clip 层）；
    cfg 参数保留仅为签名兼容，当前不参与 fetch 决策。
    """
    config = config if config is not None else load_site_config()
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
    # v2.1 §3.3：fetch 层只做标题级判断 + 安全阀——无每源配额、无槽位 CAPS、
    # 零 AI 调用。配额/CAPS 后移至 clip 层 _apply_quota_and_caps（T04，按
    # total_chars 降序）；v2 在此处的列表序截断曾误杀 3 篇 IN（黄金样本日）。
    out = _preclip_ceiling(out, MAX_PRECLIP)
    return out


def build_content(target: dt.date, content_dir: Path, *, client: httpx.Client | None = None) -> Path:
    """抓取 → 组装 → 写 content/{date}/digest.json，返回产物路径。"""
    report: dict = {"date": target.isoformat(), "sourcesOk": 0, "sourceErrors": []}
    candidates = fetch_candidates(target, client=client, report=report)
    digest = build_digest(candidates, target)
    # v2.1 §3.6 硬约束：candidates 必须填「最终 digest 条数」，不能填 fetch 原始量——
    # 簇去重在 build_digest 内部执行，digest 条数可能少于 fetch 出口数；
    # 密度门禁与配额在 clip_content 重写 digest 后，由其把 candidates 刷成
    # 最终存活数。fetch 原始量落 report["fetch"]["candidatesRaw"]——
    # volume_errors 的源健康下限检查（2026-09-12 校准）读它。
    report["fetch"] = {"candidatesRaw": len(candidates)}
    report["candidates"] = sum(len(sec.items) for sec in digest.sections)
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
    cfg: Cfg | None = None,
) -> int:
    """两阶段剪藏（v2.1 §3.4）：pass-1 全量剪藏 → 密度门禁 → 配额/CAPS →
    重写 digest.json → pass-2 仅对存活者做 AI 分析。返回最终落盘文章数。

    v2.1 §3.2-A1：配额与 CAPS 后移到本函数执行（fetch 层只留 MAX_PRECLIP
    安全阀），排序键 = total_chars 降序（v2 的列表序截断在黄金样本日误杀
    3 篇 IN）。密度门禁（§5）在剪藏后的正文层执行：被拒者不落盘、不做 AI
    ——AI 调用从「每 digest 条目」降到「每存活条目」（正常日 ~15 次/天）。
    并发剪藏 + AI 分析（默认 4 线程，可用环境变量 KAOGONG_CLIP_CONCURRENCY
    调整）；httpx.Client 线程安全，可跨线程共享。
    """
    from .clip import clip_article
    from .article_ai import analyze_article

    digest_path = content_dir / target.isoformat() / "digest.json"
    if not digest_path.exists():
        return 0
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    ai_cfg = cfg if cfg is not None else load_config()
    section_by_url: dict[str, str] = {}
    items: list[tuple[str, str]] = []
    for sec in digest.get("sections", []):
        for it in sec.get("items", []):
            url = str(it.get("sourceUrl", ""))
            if not url:
                continue
            section_by_url[url] = str(sec.get("id", ""))
            items.append((url, str(it.get("title", ""))))
    concurrency = max(1, min(int(os.environ.get("KAOGONG_CLIP_CONCURRENCY", "4")), 8))

    def _clip_only(item: tuple[str, str]) -> dict:
        url, title = item
        return clip_article(url, title, target.isoformat(), client=client)

    # ---- pass-1：全量剪藏（仅 HTTP，零 AI）----
    clips: list[dict] = []
    clip_failures: list[dict] = []
    if items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            for clip in pool.map(_clip_only, items):
                if clip.get("status") != "ok":
                    clip_failures.append(clip)
                else:
                    clips.append(clip)

    # ---- 密度门禁（§5，正文层）：拦截「剪藏成功、有正文，但是垃圾」的载体缺陷稿 ----
    density_rejected: list[tuple[dict, str]] = []
    passed_density: list[dict] = []
    for clip in clips:
        reason = density_gate(clip.get("paragraphs") or [])
        if reason is None:
            passed_density.append(clip)
        else:
            density_rejected.append((clip, reason))

    # ---- 配额/CAPS（§3.2-A1）：total_chars 降序截断 ----
    final, quota_cut = _apply_quota_and_caps(passed_density, section_by_url)

    # ---- 重写 digest.json：只留存活条目（§3.6 硬约束：candidates = 最终条数）----
    survivor_urls = {str(c.get("url", "")) for c in final}
    for sec in digest.get("sections", []):
        sec["items"] = [
            it for it in sec.get("items", [])
            if str(it.get("sourceUrl", "")) in survivor_urls
        ]
    digest["sections"] = [sec for sec in digest["sections"] if sec.get("items")]
    digest_path.write_text(
        json.dumps(digest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- pass-2：仅存活者做 AI 分析并落盘 ----
    def _analyze(clip: dict) -> dict:
        return analyze_article(clip, ai_cfg)

    finished: list[dict] = []
    if final:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            finished = list(pool.map(_analyze, final))

    out_dir = content_dir / target.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    report_path = content_dir / "_reports" / f"{target.isoformat()}.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"date": target.isoformat()}
    report.update({
        "candidates": len(final),
        "articles": 0, "aiOk": 0, "aiError": 0,
        "aiFailures": [], "clipDetails": [], "locationErrors": 0,
        "clip": {
            "clipped": len(clips),
            "densityRejected": [
                {"id": str(c.get("id", "")), "title": str(c.get("title", "")),
                 "reason": reason, "source": str(c.get("source", ""))}
                for c, reason in density_rejected
            ],
            "quotaRejected": [
                {"id": str(c.get("id", "")), "title": str(c.get("title", "")),
                 "source": str(c.get("source", "")),
                 "totalChars": total_chars(c.get("paragraphs") or [])}
                for c in quota_cut
            ],
        },
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
    # 密度/配额被拒显性化（v2.1 §3.6）：进 clipDetails 供审核工作台排查
    for c, reason in density_rejected:
        report["clipDetails"].append({
            "id": str(c.get("id", "")),
            "title": str(c.get("title", "")),
            "status": "density_rejected",
            "reason": f"density_low:{reason}",
        })
    for c in quota_cut:
        report["clipDetails"].append({
            "id": str(c.get("id", "")),
            "title": str(c.get("title", "")),
            "status": "quota_rejected",
            "reason": "quota_rejected",
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
    volume_error_list = volume_errors(report)
    report["schemaErrors"] = schema_error_list[:50]
    report["semanticErrors"] = semantic_error_list[:50]
    # 0018：人工标注已知原因（notes 非空）后，数量类错误降级为 degraded 而非 failed，保留记录供追溯
    if report.get("notes") and volume_error_list:
        report["volumeErrorsAcknowledged"] = volume_error_list[:50]
        report["volumeErrors"] = []
    else:
        report["volumeErrors"] = volume_error_list[:50]
    # 0022/v2.1 §7.1 选材口径：宁缺勿滥——选材跑了但当日无合格材料（picked=0
    # 不落 picks.json；1≤picked<2 落盘且 slots.sparse=true）是合法 sparse 日，
    # 不是错误。picks_empty 语义检查移除（picked=[] 违反 schema minItems:1，
    # 走 schema_errors → failed）；picks_slots_all_empty 保留——非 sparse 日
    # 三槽位全空仍是「合法但空转」降级，sparse 日豁免（量不足已由 sparse 状态
    # 显性化，不再叠加降级）。
    picks_path = out_dir / "picks.json"
    curation_errors: list[str] = []
    sparse_day = False
    curation_info = report.get("curation") or {}
    if not picks_path.exists():
        # 只有当天确有文章产物、且选材确未产出时才要求选材：curate 已跑且
        # picked=0 → sparse 合法日；curate 没跑（report 无 curation 段）→
        # picks_missing（管道不完整）
        curate_ran = bool(curation_info)
        if report.get("articles", 0) > 0 and not curate_ran:
            curation_errors.append("picks_missing")
        elif curate_ran and not curation_info.get("picked", 0):
            # curate 已跑但 picked=0 → 合法 sparse 日（宁缺勿滥）
            sparse_day = True
    else:
        try:
            picks_data = json.loads(picks_path.read_text(encoding="utf-8"))
            picks_slots = picks_data.get("slots") or {}
            sparse_day = bool(picks_slots.get("sparse"))
            # 0022 P0 门禁：picked 非空但 essay/exam/extra 三槽位同时为空——
            # 「合法但空转」的 picks（schema 只要求 minItems:1；bug 期间 4 天实测
            # 形态：essay 恒 []、exam/extra 恒 null）。判 degraded 暴露而非静默
            # 发布（AGENTS.md 第 8 条）；sparse 日豁免（v2.1 §7.1）。
            if (not sparse_day and not picks_slots.get("essay")
                    and not picks_slots.get("exam") and not picks_slots.get("extra")):
                curation_errors.append("picks_slots_all_empty")
        except json.JSONDecodeError:
            curation_errors.append("picks_invalid_json")
    if report.get("curation", {}).get("cardErrors") or report.get("curation", {}).get("relationErrors"):
        curation_errors.append("ai_refinement_errors")
    report["curationErrors"] = curation_errors[:10]
    if schema_error_list or semantic_error_list or volume_error_list or report.get("sourcesOk", 0) == 0 or report.get("candidates", 0) == 0:
        report["qualityStatus"] = "failed"
    elif report.get("sourceErrors") or report.get("aiError", 0) or report.get("locationErrors", 0) or curation_errors:
        report["qualityStatus"] = "degraded"
    elif sparse_day:
        # v2.1 §7.1 宁缺勿滥：量不足是显性合法状态（非错误），优先级
        # failed > degraded > sparse > ok
        report["qualityStatus"] = "sparse"
    else:
        report["qualityStatus"] = "ok"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
