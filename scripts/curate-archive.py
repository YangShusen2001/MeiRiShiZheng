# -*- coding: utf-8 -*-
"""档案策展：把某月抓到的政策文件过一遍 AI，产出「月度政策档案」。

对每篇输出四件事（考公视角）：
  importance  高/中/低——对公务员考试的价值（高=申论/常识核心考点）
  topic       主题归类（十五五规划 / 民生保障 / 产业发展 / 法治建设 …）
  gist        核心要点 40-90 字（考点角度，非新闻复述）
  figures     关键数字——这份文件定的量化指标名（画布 3:382 政策卡上那一行）

用法：
  python scripts/curate-archive.py --month 2026-07
  python scripts/curate-archive.py --month 2026-07 --batch 12 --dry

输出：content/archive/<YYYY-MM>/archive.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.deepseek import chat, load_config  # noqa: E402

# 关键数字的形状上限（画布 3:382）：单件 8-12 字、整行一两件。
# 这里挡的是 AI 走形——件数超限、单件写成整句、整行超长；宁可少显示，也不截出半个指标名。
FIGURES_MAX_ITEMS = 3
FIGURES_MAX_ITEM_LENGTH = 20
FIGURES_MAX_LENGTH = 60
# 关键数字用的正文摘录长度。比 gist 的 700 字长得多 —— 实测（2026-09-15）：
# 规划类文件的量化目标常写在正文中后部的「主要目标」章节，700 字里只有抬头与发文语，
# 召回率被压在 21%；放到 3000 字后能捞回国土空间规划、十五五规划那一批硬指标。
# 只对 figures 放宽，gist 保持 700（那是已定稿的措辞，不重跑）。
FIGURES_EXCERPT_LIMIT = 3000
# 分隔符只认这些：中点（画布 3:382 用的）、分号、竖线。
# ⚠️ 顿号与逗号**不在第一层切** —— 它们多半是枚举内部的分隔
# （实测踩坑：「评价结果分 A、B、C」被切成三项、「专业养殖、经济林 40%至50%」被切出「专业养殖」，
# 都是没有信息量的碎片）。短件里的顿号是内容的一部分，不该动。
_FIGURES_SPLIT = re.compile(r"[·；;|]+")
# 只有单件超长（AI 把好几项用顿号连成一句）时才按它们再切一刀，把被连写的多项救回来
_FIGURES_SPLIT_SOFT = re.compile(r"[、，,]+")

SYSTEM = (
    "你是公务员考试的时政内容主编。任务：判断一份政策文件对考公的价值，并提炼考点要点。"
    "只返回 JSON，不得返回 Markdown/HTML。"
    "对每一份文件给出："
    "1. importance：\"高\"（申论/常识判断的核心考点，如五年规划、重要法律、中央级战略部署）、"
    "\"中\"（了解即可，如部门实施方案、专项工作通知）、"
    "\"低\"（技术性细则、办事流程、名单批复、地方事务）。"
    "2. topic：从下列主题中选择一个最贴切的："
    "十五五规划、经济发展、民生保障、科技创新、绿色低碳、法治建设、乡村振兴、"
    "教育人才、医疗卫生、文化体育、对外开放、社会治理、安全生产、其他。"
    "3. gist：核心要点 40-90 字。写「这份文件定了什么」，供考生记忆；"
    "不要复述新闻，不要写「本文介绍了」，直接给结论性内容。"
    "4. figures：这份文件里值得记的量化指标，用「 · 」分隔，最多 3 项、整行不超过 60 字。"
    "每项都要写成**完整的指标名**（带上主语，如「天然气产量目标」「储气能力占消费量比重」），"
    "不要只写名词碎片；指标带明确目标值就连值一起写（如「参保率 95% 以上」），"
    "不要写正文里的普通数字。"
    "importance 不是「高」、或文件里没有量化指标时，给空字符串。"
    "输出形状：{\"items\":[{\"index\":0,\"importance\":\"高\",\"topic\":\"十五五规划\","
    "\"gist\":\"…\",\"figures\":\"…\"}]}"
)


def _figures(value: object) -> str:
    """把 AI 返回的关键数字收敛成画布形状（画布 3:382 是「指标名 · 指标名」）。

    只做格式收敛，不判断内容真假：空串表示「这份文件没有可量化的指标」，照原样保留。
    宁可少显示几件，也不截出半个指标名。

    ⚠️ 试过再加一道「软切产物必须带指标信号」的门禁（挡「高血压」这类裸名词），
    实测对 56 条存量**零影响** —— 说明那个碎片来自 AI 原始输出，不是切分产物；
    而它却改掉了「超长件丢弃」的既有行为（打红两个单测）。不可验证的投机约束不留，
    该问题交给提示词侧（FIGURES_SYSTEM 已要求「完整指标名、不写名词碎片」）。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    for chunk in _FIGURES_SPLIT.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= FIGURES_MAX_ITEM_LENGTH:
            parts.append(chunk)
        else:
            # 超长件：多半是多项被顿号连写，再切一刀；切完仍超长的件在下面被丢掉
            parts.extend(p.strip() for p in _FIGURES_SPLIT_SOFT.split(chunk) if p.strip())
    kept: list[str] = []
    total = 0
    for part in parts:
        if len(part) > FIGURES_MAX_ITEM_LENGTH:
            continue
        extra = len(part) + (3 if kept else 0)  # 分隔符 " · " 占 3 个字符
        if len(kept) >= FIGURES_MAX_ITEMS or total + extra > FIGURES_MAX_LENGTH:
            break
        kept.append(part)
        total += extra
    return " · ".join(kept)


# 「只补关键数字」用的提示词：比 SYSTEM 短得多，因为不需要重判 importance / 重写 gist。
FIGURES_SYSTEM = (
    "你是公务员考试的时政内容主编。下面每一条是一份政策文件的标题、发文机关与正文摘录。"
    "只做一件事：抽出这份文件里值得考生记住的量化指标。"
    "用「 · 」分隔，最多 3 项、整行不超过 60 字。"
    "每项都要写成**完整的指标名**（带上主语，如「天然气产量目标」「储气能力占消费量比重」），"
    "不要只写名词碎片；指标带明确目标值就连值一起写（如「参保率 95% 以上」）；"
    "不要写正文里的普通数字（年份、文号、条款序号、举例金额）。"
    "没有量化指标就给空字符串。"
    "输出形状：{\"items\":[{\"index\":0,\"figures\":\"…\"}]}"
)



def _load_month(month: str) -> tuple[list[dict], dict[str, dict]]:
    day = ROOT / "content" / "archive" / month
    listing = json.loads((day / "policy-list.json").read_text(encoding="utf-8"))
    bodies: dict[str, dict] = {}
    for f in sorted(day.glob("article-*.json")):
        art = json.loads(f.read_text(encoding="utf-8"))
        if art.get("status") == "ok" and art.get("paragraphs"):
            bodies[art.get("url") or art.get("id")] = art
    return listing["items"], bodies


def _excerpt(art: dict, limit: int = 700) -> str:
    text = "".join(art.get("paragraphs") or [])
    return text[:limit]


def _payload(items: list[dict]) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


def _json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def curate_month(month: str, cfg: dict[str, str], batch: int, dry: bool = False) -> dict:
    items, bodies = _load_month(month)
    rows: list[dict] = []
    for it in items:
        art = bodies.get(it["url"])
        rows.append({
            "url": it["url"], "title": it["title"], "date": it["date"],
            "lib": it["libName"], "topic_hint": it.get("topic", ""),
            "officialSummary": it.get("summary", "")[:200],
            "excerpt": _excerpt(art) if art else "",
            "hasBody": bool(art),
        })
    print(f"{month}: 清单 {len(rows)} 条，其中有正文 {sum(1 for r in rows if r['hasBody'])} 条")

    results: dict[str, dict] = {}
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        payload = [
            {
                "index": i,
                "title": r["title"],
                "issuer": r["lib"],
                "date": r["date"],
                "officialSummary": r["officialSummary"],
                "excerpt": r["excerpt"],
            }
            for i, r in enumerate(chunk)
        ]
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _payload(payload)},
        ]
        if dry:
            print(f"  [dry] 批 {start//batch+1}: {len(chunk)} 篇")
            continue
        out: dict = {}
        for attempt in range(2):
            try:
                # max_tokens 按单批上限反推：batch=12 时每篇约 110 token
                # （gist 40-90 字 + topic + figures + JSON 外壳），合计约 1300，留一倍余量。
                # 截断会让整个 JSON 解析失败 → 整批降级成「中」，所以宁给宽一点。
                out = _json_object(chat(messages, cfg, max_tokens=3000, temperature=0.2))
            except Exception as exc:
                print(f"  批 {start//batch+1} 第 {attempt+1} 次失败：{type(exc).__name__}")
                time.sleep(2)
                continue
            if isinstance(out.get("items"), list):
                break
        got = out.get("items") if isinstance(out.get("items"), list) else []
        for raw in got:
            try:
                idx = int(raw.get("index"))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(chunk):
                continue
            url = chunk[idx]["url"]
            importance = str(raw.get("importance") or "").strip()
            if importance not in ("高", "中", "低"):
                importance = "中"
            results[url] = {
                "importance": importance,
                "topic": str(raw.get("topic") or "其他").strip()[:12],
                "gist": str(raw.get("gist") or "").strip()[:200],
                "figures": _figures(raw.get("figures")),
            }
        print(f"  批 {start//batch+1}: 返回 {len(got)} 条")
        time.sleep(0.5)

    if dry:
        return {}

    merged = []
    for r in rows:
        ai = results.get(r["url"]) or {}
        merged.append({
            **{k: r[k] for k in ("url", "title", "date", "lib", "topic_hint")},
            "hasBody": r["hasBody"],
            "importance": ai.get("importance", "中"),
            "topic": ai.get("topic") or "其他",
            "gist": ai.get("gist", ""),
            "figures": ai.get("figures", ""),
        })
    order = {"高": 0, "中": 1, "低": 2}
    merged.sort(key=lambda x: (order.get(x["importance"], 1), x["date"]), reverse=False)
    doc = {
        "month": month,
        "count": len(merged),
        "high": sum(1 for x in merged if x["importance"] == "高"),
        "medium": sum(1 for x in merged if x["importance"] == "中"),
        "low": sum(1 for x in merged if x["importance"] == "低"),
        "items": merged,
    }
    out_path = ROOT / "content" / "archive" / month / "archive.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{month}: 高 {doc['high']} / 中 {doc['medium']} / 低 {doc['low']} → {out_path}")
    return doc


def fill_figures(
    month: str, cfg: dict[str, str], batch: int, dry: bool = False, refill: bool = False
) -> int:
    """只补 figures，不动已有的 importance / topic / gist。

    为什么不直接重跑 curate_month：那会重新生成全部字段，而 AI 是非确定性的 ——
    已定稿的 gist 会被改写，等于覆盖既有工作。历史档案只需要补一个新字段，
    所以单开这条路径：prompt 更短、输出更小、只回写 figures。

    只补 importance == "高" 的条目 —— 画布只在核心考点卡上渲染这一行（3:382），
    「了解 · 细则」行上没有位置，补了也不显示。

    refill=True 时连已有值一起重算（提示词或摘录长度调整后用）。
    """
    path = ROOT / "content" / "archive" / month / "archive.json"
    if not path.exists():
        print(f"{month}: 没有 archive.json，跳过")
        return 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    items = doc.get("items") or []
    try:
        _, bodies = _load_month(month)
    except Exception:
        bodies = {}

    todo: list[dict] = []
    for it in items:
        if it.get("importance") != "高":
            continue
        if not refill and str(it.get("figures") or "").strip():
            continue  # 已有值不重算（重算会漂移）
        art = bodies.get(it.get("url") or "")
        todo.append({
            "url": it["url"],
            "title": it.get("title", ""),
            "issuer": it.get("lib", ""),
            "date": it.get("date", ""),
            "excerpt": _excerpt(art, FIGURES_EXCERPT_LIMIT) if art else "",
        })
    print(f"{month}: 共 {len(items)} 条，核心考点待补 {len(todo)} 条")
    if dry or not todo:
        return len(todo)

    filled: dict[str, str] = {}
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        payload = [
            {
                "index": i,
                "title": r["title"],
                "issuer": r["issuer"],
                "date": r["date"],
                "excerpt": r["excerpt"],
            }
            for i, r in enumerate(chunk)
        ]
        messages = [
            {"role": "system", "content": FIGURES_SYSTEM},
            {"role": "user", "content": _payload(payload)},
        ]
        out: dict = {}
        for attempt in range(2):
            try:
                out = _json_object(chat(messages, cfg, max_tokens=1200, temperature=0.2))
            except Exception as exc:
                print(f"  批 {start//batch+1} 第 {attempt+1} 次失败：{type(exc).__name__}")
                time.sleep(2)
                continue
            if isinstance(out.get("items"), list):
                break
        got = out.get("items") if isinstance(out.get("items"), list) else []
        for raw in got:
            try:
                idx = int(raw.get("index"))
            except (TypeError, ValueError):
                continue
            if not 0 <= idx < len(chunk):
                continue
            value = _figures(raw.get("figures"))
            if value:
                filled[chunk[idx]["url"]] = value
        print(f"  批 {start//batch+1}: 返回 {len(got)} 条，有指标 {sum(1 for r in got if _figures(r.get('figures')))} 条")
        time.sleep(0.5)

    if refill:
        # 重算模式下先清空，否则「这次没抽出指标」的条目会留着上一轮的旧值
        for it in items:
            it.pop("figures", None)
    changed = 0
    for it in items:
        value = filled.get(it.get("url") or "")
        if value:
            it["figures"] = value
            changed += 1
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{month}: 补上 {changed} 条关键数字 → {path}")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM，或 all（全部月份）")
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument(
        "--figures-only",
        action="store_true",
        help="只补「关键数字」字段，保留已有的 importance / topic / gist（用于历史档案回填）",
    )
    ap.add_argument(
        "--refill",
        action="store_true",
        help="配合 --figures-only：连已有值一起重算（提示词 / 摘录长度调整后用）",
    )
    args = ap.parse_args()
    cfg = load_config()
    if not cfg.get("deepseek_api_key") and not args.dry:
        print("未配置 DEEPSEEK_API_KEY")
        return 2

    if args.month == "all":
        months = sorted(
            p.name for p in (ROOT / "content" / "archive").iterdir()
            if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}", p.name)
        )
    else:
        months = [args.month]

    for month in months:
        if args.figures_only:
            fill_figures(month, cfg, args.batch, dry=args.dry, refill=args.refill)
        else:
            curate_month(month, cfg, args.batch, dry=args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
