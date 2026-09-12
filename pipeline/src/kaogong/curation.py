# -*- coding: utf-8 -*-
"""每日选材漏斗：粗筛（减法）→ AI 评级与主线归属（只排序）→ 槽位分配 → picks 定稿。

规则见提案 0022 §4 + v2.1 §7：AI 输出等级（S/A/B/C）+ 进池/不进池信号 +
模糊地带 needsHuman + 主线归属；程序负责过滤、排序与槽位。头版要闻可脱离主线池；
申论精读 ×2（essay 路由）/ 考点提炼 ×1（file 路由）/ 多样性补充 ×1：槽位按
**路由类型**分配，主线归属只作同分 tie-breaker（0022 P0 修复：原「绑主线」硬条件
在主线归属失手时让三槽位恒空，已解耦）。

v2.1 §7.1 宁缺勿滥：MIN_PICKS 2→0、历史补剧删除——补剧把「当日没选出来」伪装成
「选出来了」，且历史文章不是当日核心。1≤picked<2 落盘并标 slots.sparse=true
（合法 sparse 日）；picked=0 不落 picks.json。needsHuman（发布会/调研类模糊地带、
无 key 程序兜底）与 C 级（不进池 8 类）文章不进槽位，交审核工作台。
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
# v2.1 §7.1 宁缺勿滥：下限 2→0（历史补剧同步删除）。picked<2 时 build_picks
# 置 slots["sparse"]=true（合法 sparse 日）；picked=0 不落 picks.json。
MIN_PICKS = 0
# AI 评级每批文章数：单次输出受 max_tokens=1200 约束，一次评 30+ 篇会被截断
# 导致整批降级 needsHuman（2026-09-12 修复，详见 assign_grades 文档串）。
GRADE_BATCH = 12


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
    # v2.1 §7.2 进池判据透传（T04）：模型输出的进池/不进池信号标签（观测用）；
    # partial_gold 时的段落聚焦（_normalize_focus 校验后的 {"from","to"}）；
    # needsHuman=模糊地带交人审（assign_slots 过滤，不自动放行）。
    signals: list[str]
    focus: dict
    needsHuman: bool


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
        f"标注密度 {it['metadata']['annotationDensity']} | 金句 {it['metadata']['keySentenceCount']} | "
        f"摘要: {it['metadata']['summary']}"
        for i, it in enumerate(items)
    )
    # 0022 P0（1a）：few-shot 示例的 policyLine 从 lines 动态注入，与清单永远同源。
    # 修复前硬编码提案设计值 `15w-plan`（不在真实主线池），模型照抄示例 → 主线归属
    # 0% 命中（实测 0/159）。主线池换代后也不会复发同一接缝 bug。
    # 无活跃主线时示例输出 null，与 system 提示「无归属输出 null」保持一致。
    import json

    sample_line = lines[0]["id"] if lines else None
    # v2.1 §7.2（T04）：7 进 8 出判据——判据在「栏目+内容形态」级，不在「源」级
    # （四川在线"新思想自习室"是金子、"ggxw"是垃圾；领导人活动看信息密度不看出席级别）。
    output_shape = json.dumps(
        {"items": [{
            "index": 0, "grade": "A", "policyLine": sample_line, "reason": "权威源+分析深度",
            "signals": ["analysis_depth"], "focus": None, "needsHuman": False,
        }]},
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": (
            "你是公务员考试的时政编辑。只返回 JSON，不得输出其他内容。"
            "任务：按「进池 7 信号 / 不进池 8 类」对候选文章评级（S=当日必须精读 / "
            "A=值得精读 / B=有价值 / C=不进池）并判断主线归属。"
            "进池 7 信号（命中即进池，等级取命中的最高档）："
            "gold_density(金句密度→S)、exam_hot(常考性→S)、analysis_depth(分析深度→A)、"
            "structure_value(结构价值→A)、province_practices(分省做法罗列→A)、"
            "public_opinion(社会舆情→A)、partial_gold(段落级金子→B，必须给 focus 段落范围)。"
            "不进池 8 类（只命中这些→C）：empty_notice(空壳领导人短讯)、local_bound(地方强绑定)、"
            "carrier_defect(载体缺陷：视频/图配字)、pure_data(纯数据无分析)、presser_sten(发布会通稿)、"
            "too_granular(粒度太细)、ad_service(广告服务)、case_personnel(案件人事)。"
            "signals 输出命中的信号标签数组（进池或进池外类别均可）。"
            "发布会/调研类拿不准的模糊地带：needsHuman=true 交人审，不要硬判等级。"
            "判定看「栏目+内容形态」，不看源的名气：权威源也有垃圾栏目，地方源也有金子。"
            "focus 仅 partial_gold 时输出 {\"from\": 段索引, \"to\": 段索引}（闭区间、不跨出全文），否则 null。"
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


def _normalize_focus(raw: object, paragraph_count: int) -> dict | None:
    """段落聚焦校验（v2.1 §7.2 partial_gold）：0 ≤ from ≤ to < paragraph_count。

    模型输出 {"from": 段索引, "to": 段索引}（闭区间）；越界/倒置/非整数一律
    丢弃返回 None——宁缺勿滥，不带病透传（与 article_ai 的 aiFocus 同一校验口径）。
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


def _program_fallback(article: dict) -> _Graded:
    """程序兜底排序（无 key / 模型漏评时）：权威性 × 标注密度，不依赖模型。

    0022 P0（1c，方案 α）：只加 lineSource 观测标记、不猜主线（policyLine 仍为 None）。
    误归属比 None 更糟——None 是「明确未知」可降级，误归属是「错误确定」。
    v2.1 §7.2（T04）：兜底评级没有进池判据判断能力 → needsHuman=true，
    不自动放行进槽位（宁缺勿滥：没 AI 判断就不自动选，文章照常发布）。
    """
    score = authority_rank(str(article.get("source", ""))) * (1 + len(article.get("aiAnnotations") or []))
    grade = "A" if score >= 6 else "B"
    return {
        "article": article,
        "grade": grade,
        "reason": "程序兜底排序",
        "policyLine": None,
        "lineSource": "none",
        "needsHuman": True,
    }


def assign_grades(
    articles: list[dict],
    lines: list[dict],
    cfg: dict[str, str],
    *,
    call: Callable[..., str] = chat,
) -> list[_Graded]:
    """AI 评级 + 主线归属（分批改批）；单批失败仅该批降级为程序兜底。

    2026-09-12 修复：原为「一次调用评完全部文章」+ max_tokens=1200——文章多时
    输出被截断，JSON 解析失败 → 整批走 _program_fallback（needsHuman=true）。
    实测 09-11 黄金日 34 篇全被误判「待人工」、picked=0；15 篇量级（黄金日
    最初验证规模）尚可容纳，故问题在改造后的大候选池才暴露。
    按 GRADE_BATCH 分批调用，每批输出完整，批内 index 映射回全局下标。
    """
    if not articles:
        return []
    if not cfg.get("deepseek_api_key"):
        return [_program_fallback(a) for a in articles]
    meta = [graded_meta(a) for a in articles]
    by_index: dict[int, dict] = {}
    for start in range(0, len(meta), GRADE_BATCH):
        chunk = meta[start:start + GRADE_BATCH]
        # v2.1 §7.2（T04）：输出含 signals/focus/needsHuman 三字段，故 token 上限 1200
        payload = _json_object(call(
            _grade_messages([{"metadata": m} for m in chunk], lines), cfg,
            max_tokens=1200, temperature=0.2,
        ))
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            continue  # 该批失败/截断 → 该批文章各自走兜底
        for item in raw_items:
            try:
                idx = int(item.get("index", -1))
                grade = str(item.get("grade", "")).upper()
                if 0 <= idx < len(chunk) and grade in GRADES:
                    by_index[start + idx] = item
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
        # v2.1 §7.2（T04）：进池判据三字段透传（保守清洗，不带病透传）
        raw_signals = item.get("signals")
        signals = [
            str(s).strip()[:40] for s in raw_signals
            if isinstance(s, str) and s.strip()
        ][:8] if isinstance(raw_signals, list) else []
        focus = _normalize_focus(item.get("focus"), len(article.get("paragraphs") or []))
        graded.append({
            "article": article,
            "grade": str(item.get("grade", "B")).upper(),
            "reason": str(item.get("reason", ""))[:60],
            "policyLine": line_id,
            # 观测标记（1c）：命中（精确或归一化）=model；null/未命中=none
            "lineSource": "model" if line_id else "none",
            "signals": signals,
            "focus": focus,
            "needsHuman": bool(item.get("needsHuman")),
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
    # v2.1 §7.2（T04）进池过滤：needsHuman（发布会/调研类模糊地带、无 key 兜底）
    # 与 C 级（不进池 8 类）不进任何槽位——needsHuman 交 review 工作台，
    # 不放行不硬判；C 级是「机器判定不进池」的明确结论。
    pool = sorted(
        (e for e in graded if not e.get("needsHuman") and e.get("grade", "B") != "C"),
        key=_sort_key,
    )
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
    max_picks: int = MAX_PICKS,
) -> dict:
    """完整选材漏斗：粗筛 → 评级/主线 → 槽位 → picks（宁缺勿滥，不再补剧）。

    v2.1 §7.1（T04）：历史补剧删除——补剧把「当日没选出来」伪装成「选出来了」，
    且历史文章不是当日核心。1≤picked<2 时 slots["sparse"]=true（合法 sparse 日，
    quality_gate 判 sparse 而非 degraded）；picked=0 时调用方不落 picks.json
    （schema minItems:1），quality_gate 依据 report["curation"]["picksWritten"]
    判 sparse。needsHuman 文章不进槽位，随返回值上交审核工作台。
    """
    pool = coarse_filter(articles, target)
    graded = assign_grades(pool, lines, cfg, call=call)
    slots = assign_slots(graded, limit=max_picks)
    picked = slots.pop("picked")
    needs_human = [str(e["article"].get("id", "")) for e in graded if e.get("needsHuman")]
    if len(picked) < 2:
        slots["sparse"] = True
    return {
        "date": target.isoformat(),
        "slots": slots,
        "picked": picked[:max_picks],
        "assignments": {str(e["article"].get("id")): e.get("policyLine") for e in graded},
        "needsHuman": needs_human,
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
    # v2.1 §7.1（T04）：历史加载删除——补剧废弃；_load_history 函数体保留备查
    picks = build_picks(articles, lines, cfg, target=target, call=call)

    report = {
        "date": target.isoformat(),
        "curation": {
            "candidates": len(articles),
            "coarseKept": len(coarse_filter(articles, target)),
            "picked": len(picks["picked"]),
            "slots": picks["slots"],
            "needsHuman": picks["needsHuman"],
            "cardErrors": 0,
            "relationErrors": 0,
            "cardsProduced": 0,
            "relationsProduced": 0,
        },
    }
    quota_used = 0
    by_id: dict[str, dict] = {str(a.get("id")): a for a in articles}
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
    # picks.json 只在**真的选出内容**时写（picked=[] 违反 picks.schema.json 的
    # minItems:1，实测踩过：对 08-12 跑策展写了空 picks，Schema 测试直接挂）。
    # 但 curation 报告无论是否写出 picks 都并入 _reports/{date}.json（v2.1 §7.1）：
    # quality_gate 靠 picksWritten/picked 区分「curate 没跑」（picks_missing，
    # 管道不完整）与「跑了但当日无合格材料」（合法 sparse 日，宁缺勿滥）。
    report["curation"]["picksWritten"] = bool(picks["picked"])
    report_path = Path(content_dir) / "_reports" / f"{target.isoformat()}.json"
    try:
        if report_path.exists():
            merged = json.loads(report_path.read_text(encoding="utf-8"))
            merged["curation"] = report["curation"]
            report_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except (ValueError, OSError):
        pass
    if not picks["picked"]:
        return report
    (day_dir / "picks.json").write_text(
        json.dumps(picks, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
