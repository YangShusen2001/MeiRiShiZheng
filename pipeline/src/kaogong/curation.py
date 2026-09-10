# -*- coding: utf-8 -*-
"""每日选材漏斗：粗筛（减法）→ AI 评级与主线归属（只排序）→ 槽位分配 → picks 定稿。

规则见提案 0022 §4：AI 只输出等级（S/A/B/C）+ 理由 + 主线归属；程序负责排序与槽位。
头版要闻可脱离主线池；申论精读 ×2 / 考点提炼 ×1 / 多样性补充 ×1 绑主线；
picks 2-5 篇（下限 2，不足时历史文章补剧）；AI 只排序不打分。
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from typing import TypedDict

from .card_ai import route_card_variant
from .deepseek import DEFAULT_MODEL, chat

GRADES = ("S", "A", "B", "C")
AUTHORITY_HIGH = 1.0
AUTHORITY_MID = 0.7
AUTHORITY_LOW = 0.4
HIGH_AUTHORITY_SOURCES = ("人民网", "新华", "中国政府网", "求是", "半月谈", "学习时报", "人民日报")
MAX_PICKS = 5
MIN_PICKS = 2


class _Graded(TypedDict, total=False):
    article: dict
    grade: str
    reason: str
    policyLine: str | None


def authority_rank(source: str) -> float:
    if any(h in source for h in HIGH_AUTHORITY_SOURCES):
        return AUTHORITY_HIGH
    if any(h in source for h in ("人民政府", "政府门户", "南方网", "日报")):
        return AUTHORITY_MID
    return AUTHORITY_LOW


def _signature(title: str) -> str:
    """标题去重签名：只保留汉字/数字/字母，取前 12 个字符（标点全去掉，含全角！？）。"""
    cleaned = re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]", "", title)
    return cleaned[:12]


def coarse_filter(articles: list[dict], target: dt.date) -> list[dict]:
    """程序侧粗筛（减法）：只保留 AI 处理成功、有正文、时效在当日/前一日、标题去重后的文章。"""
    seen: set[str] = set()
    out = []
    for article in articles:
        if article.get("aiStatus") != "ok":
            continue
        if not article.get("paragraphs"):
            continue
        pub = str(article.get("pubDate") or "")
        if pub:
            try:
                pub_date = dt.date.fromisoformat(pub)
                if (target - pub_date).days > 1:
                    continue
            except ValueError:
                pass
        sig = _signature(str(article.get("title", "")))
        if not sig or sig in seen:
            continue
        seen.add(sig)
        out.append(article)
    return out


def graded_meta(article: dict) -> dict:
    """评级的元数据输入：标题/来源/摘要/标注密度/金句数/段落数。"""
    annotations = article.get("aiAnnotations") or []
    return {
        "title": article.get("title"),
        "source": article.get("source"),
        "summary": (article.get("aiSummary") or "")[:120],
        "annotationDensity": len(annotations),
        "keySentenceCount": len(article.get("keySentences") or []),
        "paragraphCount": len(article.get("paragraphs") or []),
    }


def _grade_messages(items: list[dict], lines: list[dict]) -> list[dict[str, str]]:
    line_list = "、".join(f"{p['id']}({p['name']})" for p in lines)
    items_text = "\n".join(
        f"<a{i}> 归属候选: {it['metadata']['title']} | 来源: {it['metadata']['source']} | "
        f"标注密度 {it['metadata']['annotationDensity']} | 金句 {it['metadata']['keySentenceCount']}"
        for i, it in enumerate(items)
    )
    return [
        {"role": "system", "content": (
            "你是公务员考试的时政编辑。只返回 JSON，不得输出其他内容。"
            "任务：对候选文章评级（S=当日必须精读 / A=值得精读 / B=有价值 / C=普通）并判断主线归属。"
            "只做排序与归属，不做价值判断之外的任何决定：不评分、不写理由之外的话。"
            "policyLine 从给出的主线 id 中选；无归属输出 null。每篇给一句话理由（≤30 字）。"
        )},
        {"role": "user", "content": (
            "输出形状：{\"items\":[{\"index\":0,\"grade\":\"A\",\"policyLine\":\"15w-plan\",\"reason\":\"权威源+标注密\"}]}\n"
            f"活跃主线：{line_list}\n候选文章（index 与下方一致）：\n{items_text}"
        )},
    ]


def _json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    import json

    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _program_fallback(article: dict) -> _Graded:
    """程序兜底排序（无 key / 模型漏评时）：权威性 × 标注密度，不依赖模型。"""
    score = authority_rank(str(article.get("source", ""))) * (1 + len(article.get("aiAnnotations") or []))
    grade = "A" if score >= 6 else "B"
    return {"article": article, "grade": grade, "reason": "程序兜底排序", "policyLine": None}


def assign_grades(
    articles: list[dict],
    lines: list[dict],
    cfg: dict[str, str],
    *,
    call: Callable[..., str] = chat,
) -> list[_Graded]:
    """AI 评级 + 主线归属（一次调用）；失败降级为程序兜底（无主线、按权威性×密度排序）。"""
    if not articles:
        return []
    if not cfg.get("deepseek_api_key"):
        return [_program_fallback(a) for a in articles]
    meta = [graded_meta(a) for a in articles]
    payload = _json_object(call(
        _grade_messages([{"metadata": m} for m in meta], lines), cfg, max_tokens=900, temperature=0.2,
    ))
    raw_items = payload.get("items")
    by_index: dict[int, dict] = {}
    if isinstance(raw_items, list):
        for item in raw_items:
            try:
                idx = int(item.get("index", -1))
                grade = str(item.get("grade", "")).upper()
                if 0 <= idx < len(articles) and grade in GRADES:
                    by_index[idx] = item
            except (KeyError, TypeError, ValueError):
                continue

    graded = []
    for i, article in enumerate(articles):
        item = by_index.get(i)
        if item is None:
            graded.append(_program_fallback(article))
            continue
        line = str(item.get("policyLine") or "").strip()
        line_id = line if any(p.get("id") == line for p in lines) else None
        graded.append({
            "article": article,
            "grade": str(item.get("grade", "B")).upper(),
            "reason": str(item.get("reason", ""))[:60],
            "policyLine": line_id,
        })
    return graded


def _sort_key(entry: _Graded) -> tuple[int, float]:
    return (GRADES.index(entry.get("grade", "B")), authority_rank(str(entry.get("article", {}).get("source", ""))))


def assign_slots(graded: list[_Graded], *, limit: int = MAX_PICKS) -> dict:
    """程序槽位分配：头版（可脱离主线）→ 申论精读 ×2 → 考点提炼 ×1 → 多样性补充 ×1。"""
    slots: dict[str, str | None] = {"headline": None, "essay": [], "exam": None, "extra": None}
    pool = sorted(graded, key=_sort_key)
    used: set[str] = set()
    taken = set()

    def pick(pred, *, skip_used: bool = True):
        for entry in pool:
            aid = str(entry["article"].get("id", ""))
            if aid in taken:
                continue
            if skip_used and aid in used:
                continue
            if pred(entry):
                taken.add(aid)
                return entry
        return None

    # 头版要闻：等级最高者，允许无主线（脱离主线池）
    headline = pick(lambda e: True, skip_used=False)
    if headline:
        slots["headline"] = str(headline["article"].get("id"))
        used.add(str(headline["article"].get("id")))


    # 申论精读：评论类（essay 路由）
    essay_pool = [e for e in pool if e["article"].get("id") not in used]
    for entry in sorted(essay_pool, key=_sort_key):
        if len(slots["essay"]) >= 2:
            break
        if route_card_variant(str(entry["article"].get("title", "")), str(entry["article"].get("source", ""))) == "essay" \
                and (entry.get("policyLine") or entry.get("article", {}).get("policyLine")):
            slots["essay"].append(str(entry["article"].get("id")))
            used.add(str(entry["article"].get("id")))


    # 考点提炼：文件类（file 路由），绑主线
    exam = pick(lambda e: route_card_variant(
        str(e["article"].get("title", "")), str(e["article"].get("source", ""))) == "file"
        and (e.get("policyLine") or e["article"].get("policyLine")))
    if exam:
        slots["exam"] = str(exam["article"].get("id"))
        used.add(slots["exam"])


    # 多样性补充：剩余最高等级，主线与已选不同
    selected_lines = {
        entry.get("policyLine") for entry in graded
        if str(entry["article"].get("id")) in used and entry.get("policyLine")
    }
    extra = pick(lambda e: (e.get("policyLine") or e["article"].get("policyLine"))
                 and (e.get("policyLine") not in selected_lines))
    if extra:
        slots["extra"] = str(extra["article"].get("id"))
        used.add(slots["extra"])


    picked_ids = [slots["headline"], *slots["essay"], slots["exam"], slots["extra"]]
    slots["picked"] = [pid for pid in picked_ids if pid]
    return slots


def build_picks(
    articles: list[dict],
    lines: list[dict],
    cfg: dict[str, str],
    *,
    target: dt.date,
    call: Callable[..., str] = chat,
    min_picks: int = MIN_PICKS,
    max_picks: int = MAX_PICKS,
    history: list[dict] | None = None,
) -> dict:
    """完整选材漏斗：粗筛 → 评级/主线 → 槽位 → picks（不足下限时历史文章补剧）。"""
    pool = coarse_filter(articles, target)
    graded = assign_grades(pool, lines, cfg, call=call)
    slots = assign_slots(graded, limit=max_picks)
    picked = slots.pop("picked")
    # 下限补剧：当日池不足 min_picks 时，用历史文章（近 7 天、AI 成功）按程序优先级补齐，
    # 不重新评级（当日池都缺料时，历史通常也非当日核心；标 slot=supplement 供人工确认）。
    if len(picked) < min_picks and history:
        history_sorted = sorted(
            history,
            key=lambda h: (authority_rank(str(h.get("source", ""))) * (1 + len(h.get("aiAnnotations") or [])), h.get("date", "")),
            reverse=True,
        )
        for article in history_sorted:
            if len(picked) >= min_picks:
                break
            aid = str(article.get("id", ""))
            if aid in picked:
                continue
            slots.setdefault("supplement", []).append(aid)
            picked.append(aid)
    return {
        "date": target.isoformat(),
        "slots": slots,
        "picked": picked[:max_picks],
        "assignments": {str(e["article"].get("id")): e.get("policyLine") for e in graded},
    }


def _load_lines(content_dir) -> list[dict]:
    from pathlib import Path

    path = Path(content_dir) / "policy-lines.json"
    if not path.exists():
        return []
    import json

    try:
        return [p for p in json.loads(path.read_text(encoding="utf-8")).get("lines", []) if p.get("status") == "active"]
    except (ValueError, OSError):
        return []


def _load_day_articles(content_dir, target: dt.date) -> list[dict]:
    import json

    from pathlib import Path

    day_dir = Path(content_dir) / target.isoformat()
    out = []
    if day_dir.exists():
        for f in sorted(day_dir.glob("article-*.json")):
            try:
                article = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            article.pop("slot", None)  # 清历史污染：槽位信息只属于 picks.json
            out.append(article)
    return out


def _load_history(content_dir, target: dt.date, days: int = 7) -> list[dict]:
    """近 N 天（不含目标日）的 AI 成功文章，供补剧；附带内部字段 _srcDay 记录来源目录。"""
    import json

    from pathlib import Path

    base = Path(content_dir)
    out = []
    for offset in range(1, days + 1):
        day = (target - dt.timedelta(days=offset)).isoformat()
        day_dir = base / day
        if not day_dir.exists():
            continue
        for f in sorted(day_dir.glob("article-*.json")):
            try:
                article = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if article.get("aiStatus") == "ok":
                article.pop("slot", None)  # 清历史污染：槽位信息只属于 picks.json
                article["_srcDay"] = day
                out.append(article)
    return out


def curate_content(
    target: dt.date,
    content_dir,
    cfg: dict[str, str] | None = None,
    *,
    call: Callable[..., str] = chat,
) -> dict:
    """每日选材 + 卡片提炼 + 关系标注：写 content/{date}/picks.json 并回写文章字段。

    与 review 工作台的分工：本函数为全自动初稿（AI 评级/抽卡/连线），
    人工确认与修正由工作台（阶段 C）承担。
    """
    import json
    from pathlib import Path

    from .card_ai import DAILY_NEW_CARD_LIMIT, refine_cards

    cfg = cfg or {}
    day_dir = Path(content_dir) / target.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    articles = _load_day_articles(content_dir, target)
    lines = _load_lines(content_dir)
    history = _load_history(content_dir, target)
    picks = build_picks(articles, lines, cfg, target=target, history=history, call=call)

    report = {
        "date": target.isoformat(),
        "curation": {
            "candidates": len(articles),
            "coarseKept": len(coarse_filter(articles, target)),
            "picked": len(picks["picked"]),
            "slots": picks["slots"],
            "cardErrors": 0,
            "relationErrors": 0,
            "cardsProduced": 0,
            "relationsProduced": 0,
        },
    }
    quota_used = 0
    by_id: dict[str, dict] = {str(a.get("id")): a for a in articles}
    for article in history:
        if article.get("id") not in by_id:
            by_id.setdefault(str(article.get("id")), article)
    for aid in picks["picked"]:
        article = by_id.get(aid)
        if article is None:
            continue
        # 主线归属回写（来自 build_picks 的评级结果，不重复调用模型）
        line_id = picks.get("assignments", {}).get(aid)
        if line_id:
            article["policyLine"] = line_id
        # 卡片提炼（每日新卡 ≤5 全局配额）
        budget = max(0, DAILY_NEW_CARD_LIMIT - quota_used)
        card_result = refine_cards(article, cfg, daily_budget=budget, call=call)
        if "error" in card_result:
            report["curation"]["cardErrors"] += 1
        else:
            article["aiCards"] = card_result["cards"]
            quota_used += len(card_result["cards"])
            report["curation"]["cardsProduced"] += len(card_result["cards"])
        # 关系标注（箭头）：2026-08-22 用户拍板——AI 自动生成关闭（看着难受），
        # 由选材工作台人工创建；relation_ai.py 保留为未来可选的辅助能力。
        report["curation"]["relationErrors"] = 0
        report["curation"]["relationsProduced"] = 0
        src_day = str(article.pop("_srcDay", target.isoformat()))
        out_dir = Path(content_dir) / src_day
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"article-{aid}.json").write_text(
            json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (day_dir / "picks.json").write_text(
        json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # curation 报告并入当日 _reports/{date}.json（quality_gate 读取）
    from pathlib import Path as _Path

    report_path = Path(content_dir) / "_reports" / f"{target.isoformat()}.json"
    if report_path.exists():
        try:
            merged = json.loads(report_path.read_text(encoding="utf-8"))
            merged["curation"] = report["curation"]
            report_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        except (ValueError, OSError):
            pass
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
