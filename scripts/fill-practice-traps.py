# -*- coding: utf-8 -*-
"""给存量 practice.json 补「错因」（画布 3:617「错因：漏读题干」）。

为什么需要这个脚本：
  出题时 `traps` 与题目是**同一次** AI 调用产出的（pipeline/practice.py）。
  加 traps 之前生成的 practice.json 没有这个字段 —— 而站点当前服务的恰恰是这套存量题，
  不补的话端上「错因」永远是降级态：错题本预览退回「你的 X → 正确 Y」，
  错题本条目里干脆不显示。

为什么不在每日管道里加开关：
  新日期由 `python -m kaogong <date>` 天然带 traps；这里只做**存量回填**。
  与 curate-archive.py 的 `--figures-only` 是同一类活：只补一个新字段，不重算已定稿内容
  （题目本身重算会换题，等于覆盖既有工作）。

用法：
  python scripts/fill-practice-traps.py                 # 全部日期，只补缺 traps 的题
  python scripts/fill-practice-traps.py --date 2026-09-12
  python scripts/fill-practice-traps.py --refill        # 已有 traps 也重算
  python scripts/fill-practice-traps.py --dry           # 只报数不写盘

输出：原地更新 content/<date>/practice.json
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
from kaogong.pipeline import _digest_text  # noqa: E402
from kaogong.practice import (  # noqa: E402
    TRAP_MAX_LENGTH,
    TRAP_MIN_LENGTH,
    _parse_traps,
    duplicate_trap_count,
)

# 一次 AI 调用塞多少道题。输出本身很小（每题 4 个短标签），但输出越长越容易被 max_tokens
# 截断 —— 截断 → JSON 解析失败 → **整批**白跑。每日 20 题按 10 一批 = 2 次调用，留足余量。
TRAPS_BATCH = 10
# 材料摘录上限，与出题时一致（practice.py 的 _build_user_prompt 也是 8000）
MATERIAL_LIMIT = 8000

TRAPS_SYSTEM = (
    "你是资深公考辅导老师。用户给你一段时政材料和若干**已经出好的**四选一题目"
    "（含选项与正确答案下标）。"
    "请为每道题的 4 个选项各写一个「典型误因」短标签：写**选了这个选项的人通常错在哪**，"
    f"{TRAP_MIN_LENGTH}-{TRAP_MAX_LENGTH} 字、口语化。"
    "**正确选项那一项必须给空字符串** —— 它没有错因。"
    "三个错误选项的误因**必须互不相同**，要针对该选项本身的内容写；"
    "严禁三个选项复用同一个标签（如全是「张冠李戴」）——"
    "「错因」是给考生看「我错在哪」的，同质标签等于没写。"
    "可选标签示例：张冠李戴、数字记混、时间错位、对象混淆、以偏概全、过度引申、"
    "漏读题干、概念混淆、偷换主体、答非所问、因果倒置、绝对化。"
    "不要改题干、不要改选项、不要改答案，只输出误因。"
    "只输出 JSON："
    '{"traps":[{"id":"q1","t":["误因A","误因B","误因C","误因D"]}]}'
)


def _json_object(text: str) -> dict:
    """从 AI 返回里抽出最外层 JSON 对象；抽不出返回空 dict（不抛错）。"""
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _material(date: str) -> str:
    """当日材料全文（与出题同源：content/<date>/digest.json 汇总的正文）。"""
    digest_path = ROOT / "content" / date / "digest.json"
    if not digest_path.exists():
        return ""
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    return _digest_text(digest, ROOT / "content")


def _dup(traps: list[str]) -> bool:
    """三个错误项里有没有复用同一个标签。"""
    non_empty = [t for t in traps if t]
    return len(set(non_empty)) < len(non_empty)


def _score(traps: list[str] | None) -> int:
    """错因质量分：0 = 没有；1 = 有但标签重复；2 = 有且三个错误项互不相同。

    ⚠️ 重跑是**随机游走**，不是免费的改进：实测（2026-09-15）同一批题连跑两次，
    重复题数会从 21 涨到 34。所以回填必须**单调**——只接受分数更高的结果，
    分数持平就保留原值（也避免无意义的措辞漂移）。
    """
    if not traps:
        return 0
    non_empty = [t for t in traps if t]
    if not non_empty:
        return 0
    return 2 if len(set(non_empty)) == len(non_empty) else 1


def _ask(
    material: str,
    date: str,
    chunk: list[dict],
    cfg: dict,
    *,
    corrective: bool = False,
) -> dict[str, list[str]]:
    """问一批题的错因，返回 {题目 id: traps}。失败返回空 dict（调用方自然降级）。

    corrective=True 用于重问：显式点出「上次有选项复用了同一个标签」。
    """
    by_id = {str(q.get("id") or ""): q for q in chunk}
    payload = [
        {"id": q.get("id"), "q": q.get("q"), "options": q.get("options"), "answer": q.get("answer")}
        for q in chunk
    ]
    tail = (
        "\n\n【上次输出不合格】同一道题的多个错误选项复用了同一个误因标签。"
        "这次请针对每个选项**各自**的内容写，三个错误项的标签互不相同。"
        if corrective
        else ""
    )
    messages = [
        {"role": "system", "content": TRAPS_SYSTEM},
        {
            "role": "user",
            "content": (
                f"【日期】{date}\n\n【材料】\n{material[:MATERIAL_LIMIT]}\n\n"
                "【题目】\n" + json.dumps(payload, ensure_ascii=False) + tail
            ),
        },
    ]
    out: dict = {}
    for attempt in range(2):
        try:
            out = _json_object(
                chat(
                    messages,
                    cfg,
                    max_tokens=1500,
                    temperature=0.2,
                    extra={"response_format": {"type": "json_object"}},
                )
            )
        except Exception as exc:
            print(f"    第 {attempt + 1} 次调用失败：{type(exc).__name__}")
            time.sleep(2)
            continue
        if isinstance(out.get("traps"), list):
            break

    got = out.get("traps") if isinstance(out.get("traps"), list) else []
    result: dict[str, list[str]] = {}
    for raw in got:
        if not isinstance(raw, dict):
            continue
        q = by_id.get(str(raw.get("id") or ""))
        if not q:
            continue
        answer = q.get("answer")
        # bool 是 int 的子类，显式排除（与 parse_questions 同一处防御）
        if not isinstance(answer, int) or isinstance(answer, bool):
            continue
        traps = _parse_traps(raw.get("t"), answer)
        if traps:
            result[str(q.get("id"))] = traps
    return result


def fill_date(date: str, cfg: dict, batch: int, dry: bool = False, refill: bool = False) -> int:
    """给某天的 practice.json 补 traps，返回本轮改进的题数。

    逐题**按 id 对齐**回填，不按返回顺序 —— AI 少给/多给/换序都不会串题。
    拿不到 traps 的题原样保留（端上自然降级），不删题、不改题。

    单调性：只有分数**严格更高**才写回（见 `_score`）。所以这个脚本可以反复跑，
    结果只会变好不会变坏 —— 重跑是随机游走，不做单调约束就会越跑越差。
    """
    path = ROOT / "content" / date / "practice.json"
    if not path.exists():
        print(f"{date}: 没有 practice.json，跳过")
        return 0
    doc = json.loads(path.read_text(encoding="utf-8"))
    questions = doc.get("questions") or []
    material = _material(date)
    if not material.strip():
        print(f"{date}: 取不到当日材料（digest.json 缺失或正文为空），跳过")
        return 0

    # 默认只补「没有错因」的题；--refill 追加「有错因但标签重复」的题去重试
    # （已达满分 2 的题不再问 —— 单调约束下重问不可能更好，纯浪费调用）
    if refill:
        todo = [q for q in questions if _score(q.get("traps")) < 2]
    else:
        todo = [q for q in questions if not q.get("traps")]
    print(f"{date}: 共 {len(questions)} 题，待补/待修 {len(todo)} 题")
    if dry or not todo:
        return len(todo)

    filled: dict[str, list[str]] = {}
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        by_id = {str(q.get("id") or ""): q for q in chunk}
        first = _ask(material, date, chunk, cfg)
        hit = len(first)

        # 约束校验（画布 3:617）：三个错误项不得复用同一标签。
        # 命中重复只重问**这几道**，且只采纳确实不再重复的结果 —— 不让重试把结果弄差。
        bad = [qid for qid, traps in first.items() if _dup(traps)]
        if bad:
            retry_chunk = [by_id[qid] for qid in bad if qid in by_id]
            second = _ask(material, date, retry_chunk, cfg, corrective=True)
            fixed = 0
            for qid, traps in second.items():
                if not _dup(traps):
                    first[qid] = traps
                    fixed += 1
            print(f"  批 {start // batch + 1}: 返回 {hit} 条，标签重复 {len(bad)} 条，重问后修好 {fixed} 条")
        else:
            print(f"  批 {start // batch + 1}: 返回 {hit} 条，标签无重复")

        filled.update(first)
        time.sleep(0.5)

    improved = 0
    kept = 0
    for q in questions:
        new = filled.get(str(q.get("id")))
        if not new:
            continue
        old = q.get("traps")
        # 单调：重跑只有**严格更好**才采纳，分数持平保留原值（避免措辞漂移与倒退）
        if old and _score(new) <= _score(old):
            kept += 1
            continue
        q["traps"] = new
        improved += 1
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    left = duplicate_trap_count(questions)
    print(f"{date}: 改进 {improved} 题、保留原值 {kept} 题（仍重复 {left} 题）→ {path}")
    return improved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认全部有 practice.json 的日期")
    ap.add_argument("--batch", type=int, default=TRAPS_BATCH)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--refill", action="store_true", help="连「标签重复」的题一起重试（单调：只接受更好的结果）")
    args = ap.parse_args()
    cfg = load_config()
    if not cfg.get("deepseek_api_key") and not args.dry:
        print("未配置 DEEPSEEK_API_KEY")
        return 2

    if args.date:
        dates = [args.date]
    else:
        dates = sorted(p.parent.name for p in (ROOT / "content").glob("*/practice.json"))

    total = 0
    for date in dates:
        total += fill_date(date, cfg, args.batch, dry=args.dry, refill=args.refill)
    print(f"合计改进 {total} 题错因")
    return 0


if __name__ == "__main__":
    sys.exit(main())
