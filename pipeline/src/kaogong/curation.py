# -*- coding: utf-8 -*-
"""每日选材漏斗：粗筛（减法）→ AI 评级与主线归属（只排序）→ 槽位分配 → picks 定稿。

规则见提案 0022 §4：AI 只输出等级（S/A/B/C）+ 理由 + 主线归属；程序负责排序与槽位。
头版要闻可脱离主线池；申论精读 ×2（essay 路由）/ 考点提炼 ×1（file 路由）/ 多样性补充 ×1：
槽位按**路由类型**分配，主线归属只作同分 tie-breaker（0022 P0 修复：原「绑主线」硬条件
在主线归属失手时让三槽位恒空，已解耦）；picks 2-5 篇（下限 2，不足时历史文章补剧）；
AI 只排序不打分。
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections.abc import Callable
from typing import Literal, TypedDict

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
    # 观测标记（0022 P0 方案 α）：policyLine 值的来源，只观测、不猜主线——
    # "model"    模型返回且（精确/归一化后）命中主线白名单；
    # "none"     无归属（模型输出 null、归一化未命中、或程序兜底路径）；
    # "fallback" 预留给未来的兜底归属机制（方案 β，需主线池带类型标签，不在 P0）。
    lineSource: Literal["model", "fallback", "none"]


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
    # 0022 P0（1a）：few-shot 示例的 policyLine 从 lines 动态注入，与清单永远同源。
    # 修复前硬编码提案设计值 `15w-plan`（不在真实主线池），模型照抄示例 → 主线归属
    # 0% 命中（实测 0/159）。主线池换代后也不会复发同一接缝 bug。
    # 无活跃主线时示例输出 null，与 system 提示「无归属输出 null」保持一致。
    import json

    sample_line = lines[0]["id"] if lines else None
    output_shape = json.dumps(
        {"items": [{"index": 0, "grade": "A", "policyLine": sample_line, "reason": "权威源+标注密"}]},
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": (
            "你是公务员考试的时政编辑。只返回 JSON，不得输出其他内容。"
            "任务：对候选文章评级（S=当日必须精读 / A=值得精读 / B=有价值 / C=普通）并判断主线归属。"
            "只做排序与归属，不做价值判断之外的任何决定：不评分、不写理由之外的话。"
            "policyLine 从给出的主线 id 中选；无归属输出 null。每篇给一句话理由（≤30 字）。"
        )},
        {"role": "user", "content": (
            f"输出形状：{output_shape}\n"
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


# 归一化时剥掉的包裹字符：半/全角引号、书名号、反引号（id 契约 ^[a-z0-9-]+$ 不会以这些开头）
_LINE_WRAP_CHARS = "\"'`“”‘’「」『』"


def _normalize_line_id(raw: object, lines: list[dict]) -> str | None:
    """把模型返回的 policyLine 归一化到主线白名单（0022 P0 §2.2，保守零误匹配）。

    支持：去首尾空白 / 去包裹引号（含全角）/ 全角转半角（NFKC：ｆ→f、－→-、（→(、＂→"）/
    大小写归一 / 裁剪「id(名称)」回显后缀（模型照抄清单形态 `id(name)` 时截掉名称部分）。
    明确不支持（会引入误匹配，架构文档 §2.2）：子串/包含匹配、对 p['name'] 的名称模糊匹配、
    短 id 别名字典（15w-plan→…，为当前池打补丁换代即失效）、LLM 二次仲裁。
    返回 None = 无归属（保持旧行为：宁可无归属，不可误归属——误归属会污染 extra 的
    「已选主线」多样性判断，产生连锁误判）。
    """
    if not lines:
        return None
    ids = [str(p.get("id") or "") for p in lines if p.get("id")]
    text = str(raw or "").strip()
    if not text:
        return None
    text = text.strip(_LINE_WRAP_CHARS).strip()
    text = unicodedata.normalize("NFKC", text)
    text = text.strip().strip(_LINE_WRAP_CHARS).strip()
    lowered = text.lower()
    for line_id in ids:  # 1) 精确命中（大小写归一后）
        if lowered == line_id.lower():
            return line_id
    trimmed = lowered.split("(", 1)[0].strip()  # 2) 裁剪「id(名称)」回显
    if trimmed and trimmed != lowered:
        for line_id in ids:
            if trimmed == line_id.lower():
                return line_id
    return None


def _program_fallback(article: dict) -> _Graded:
    """程序兜底排序（无 key / 模型漏评时）：权威性 × 标注密度，不依赖模型。

    0022 P0（1c，方案 α）：只加 lineSource 观测标记、不猜主线（policyLine 仍为 None）。
    误归属比 None 更糟——None 是「明确未知」可降级，误归属是「错误确定」。
    """
    score = authority_rank(str(article.get("source", ""))) * (1 + len(article.get("aiAnnotations") or []))
    grade = "A" if score >= 6 else "B"
    return {
        "article": article,
        "grade": grade,
        "reason": "程序兜底排序",
        "policyLine": None,
        "lineSource": "none",
    }


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
        # 0022 P0（1b）：归一化匹配——精确/大小写/引号/空白/全角/「id(名称)」回显 → 白名单 id；
        # 其余归 None。修复前是精确匹配，示例短 id 与真实 id 对不上 → 归属 100% 落空。
        line_id = _normalize_line_id(item.get("policyLine"), lines)
        graded.append({
            "article": article,
            "grade": str(item.get("grade", "B")).upper(),
            "reason": str(item.get("reason", ""))[:60],
            "policyLine": line_id,
            # 观测标记（1c）：命中（精确或归一化）=model；null/未命中=none
            "lineSource": "model" if line_id else "none",
        })
    return graded


def _sort_key(entry: _Graded) -> tuple[int, float]:
    return (GRADES.index(entry.get("grade", "B")), authority_rank(str(entry.get("article", {}).get("source", ""))))


def _entry_line(entry: _Graded) -> str | None:
    """槽位判定用的主线值：评级结果优先，其次文章自带的 policyLine（历史运行回写）。"""
    line = entry.get("policyLine") or entry.get("article", {}).get("policyLine")
    return str(line) if line else None


def assign_slots(graded: list[_Graded], *, limit: int = MAX_PICKS) -> dict:
    """程序槽位分配：头版（无条件）→ 申论精读 ×2 → 考点提炼 ×1 → 多样性补充 ×1。

    0022 P0（1d，方案 c）：槽位第一判定只看**路由类型**（essay→申论精读 / file→考点提炼），
    policyLine 仅作同分 tie-breaker（有主线者优先；extra 偏好主线不在已选集合）。
    修复前把 policyLine 非空当 essay/exam/extra 的硬准入条件——主线归属失手
    （few-shot 短 id → 0% 命中）时三槽位恒空，picks 退化为只有 headline。
    槽位填不满就让它空着（门禁 picks_slots_all_empty 负责暴露该状态），
    禁止拿不合适路由类型的文章降级补位——那会把「没选出来」伪装成「选出来了」。
    """
    del limit  # 保留签名兼容 build_picks(limit=max_picks)；槽位自然上限 1+2+1+1=MAX_PICKS
    slots: dict[str, str | None | list[str]] = {"headline": None, "essay": [], "exam": None, "extra": None}
    pool = sorted(graded, key=_sort_key)
    used: set[str] = set()

    def entry_id(entry: _Graded) -> str:
        return str(entry["article"].get("id", ""))

    def variant(entry: _Graded) -> str:
        return route_card_variant(
            str(entry["article"].get("title", "")), str(entry["article"].get("source", ""))
        )

    # 头版要闻：等级最高者，允许无主线（脱离主线池）——无条件槽位，不要求路由类型
    if pool:
        slots["headline"] = entry_id(pool[0])
        used.add(entry_id(pool[0]))

    # 申论精读 ×2：essay 路由即可入池；同分时有主线者优先（tie-breaker，非硬条件）
    essay_pool = sorted(
        (e for e in pool if entry_id(e) not in used and variant(e) == "essay"),
        key=lambda e: (_sort_key(e), _entry_line(e) is None),
    )
    for entry in essay_pool:
        if len(slots["essay"]) >= 2:
            break
        slots["essay"].append(entry_id(entry))
        used.add(entry_id(entry))

    # 考点提炼 ×1：file 路由即可入池；同分时有主线者优先（tie-breaker，非硬条件）
    exam_pool = sorted(
        (e for e in pool if entry_id(e) not in used and variant(e) == "file"),
        key=lambda e: (_sort_key(e), _entry_line(e) is None),
    )
    if exam_pool:
        slots["exam"] = entry_id(exam_pool[0])
        used.add(entry_id(exam_pool[0]))

    # 多样性补充 ×1：不要求主线非空；tie-breaker 偏好「主线不在已选集合」
    selected_lines = {_entry_line(e) for e in graded if entry_id(e) in used and _entry_line(e)}

    def extra_rank(entry: _Graded) -> int:
        line = _entry_line(entry)
        if line and line not in selected_lines:
            return 0  # 新主线：多样性最佳
        if not line:
            return 1  # 无主线：中性（不违反多样性）
        return 2  # 主线已选：重复，最不优先

    remaining = sorted(
        (e for e in pool if entry_id(e) not in used),
        key=lambda e: (_sort_key(e), extra_rank(e)),
    )
    if remaining:
        slots["extra"] = entry_id(remaining[0])
        used.add(entry_id(remaining[0]))

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


def card_budget_for(remaining_quota: int, remaining_articles: int) -> int:
    """每日新卡配额分配：按剩余篇数均分（向上取整）。

    为什么需要它：原实现是 `budget = 每日上限 - 已用`（先到先得），
    第一篇文章就能吃掉全部 5 张，**后面被选中的文章一张卡都拿不到**——
    那"选材 ≥2 篇"就失去了意义：选它出来就是为了让它产出可复习的卡片。

    向上取整让靠前的槽位（头版要闻 / 申论精读）略多，同时保证每篇都拿得到。
    """
    if remaining_articles <= 0:
        return max(0, remaining_quota)
    if remaining_quota <= 0:
        return 0
    return (remaining_quota + remaining_articles - 1) // remaining_articles


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
    # 每日新卡配额按「被选中的篇数」均分，而不是先到先得。
    # 原实现 `budget = 上限 - 已用` 允许第一篇文章吃掉全部 5 张，
    # 后面被选中的文章一张卡都拿不到——那"选材 ≥2 篇"就没有意义了：
    # 选它出来的目的就是让它产出可复习的卡片。
    # 向上取整分配：靠前的槽位（头版要闻/申论精读）略多，且每篇都拿得到。
    picked_ids: list[str] = [aid for aid in picks["picked"] if by_id.get(aid) is not None]
    for index, aid in enumerate(picked_ids):
        article = by_id.get(aid)
        if article is None:
            continue
        # 主线归属回写（来自 build_picks 的评级结果，不重复调用模型）
        line_id = picks.get("assignments", {}).get(aid)
        if line_id:
            article["policyLine"] = line_id
        # 卡片提炼（每日新卡 ≤5 全局配额，按剩余篇数均分——见 card_budget_for）
        left = max(0, DAILY_NEW_CARD_LIMIT - quota_used)
        budget = card_budget_for(left, len(picked_ids) - index)
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
    # picks.json 只在**真的选出内容**时写。
    # 选不到东西时写 `picked: []` 会违反 picks.schema.json 的 minItems:1，
    # 产出一个非法文件（实测踩过：对 08-12 跑策展写了空 picks，Schema 测试直接挂）。
    # 选不到材料是"降级"而不是"产出"——report 里已记录，管道的质量门禁
    # 也把 picks_missing 当降级态处理，不写文件才是符合约定的行为。
    if not picks["picked"]:
        report["curation"]["picksWritten"] = False
        return report
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
