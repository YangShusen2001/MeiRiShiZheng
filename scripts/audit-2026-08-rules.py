# -*- coding: utf-8 -*-
"""零 API 规则漏斗扫描：用 T01-T04 的纯规则闸门（密度 G1-G4 + 配额/CAPS）
复核历史数据，产出人工审核清单。

背景（2026-09-12 用户指令）：不用 DeepSeek API 补跑 7/8 月。
7 月本地无数据且源站列表页翻不到历史 → 不可行；8 月本地有 7 天数据可跑。

只读：不改动 content/ 下任何产物，输出到 _review/。
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.density import density_gate, total_chars  # noqa: E402
from kaogong.pipeline import _apply_quota_and_caps, _slot_of  # noqa: E402
from kaogong.dedupe import is_same_event, normalize_title  # noqa: E402

CONTENT = ROOT / "content"
OUT = ROOT / "_review" / "audit-2026-08-rules.json"


def _section_map(day: Path) -> dict[str, str]:
    """从 digest.json 构建 url → section_id（兼容旧六分节）。"""
    p = day / "digest.json"
    if not p.exists():
        return {}
    digest = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for sec in digest.get("sections") or []:
        sid = str(sec.get("id") or "")
        for item in sec.get("items") or []:
            url = str(item.get("sourceUrl") or item.get("url") or "")
            if url:
                out[url] = sid
    return out


def _cluster_dedupe(items: list[dict]) -> tuple[list[dict], list[dict]]:
    """标题级簇去重（零 AI）：同事件只留正文最长的一篇。"""
    kept: list[dict] = []
    cut: list[dict] = []
    for art in items:
        title = str(art.get("title") or "")
        dup = None
        for k in kept:
            if is_same_event(normalize_title(title), normalize_title(str(k.get("title") or ""))):
                dup = k
                break
        if dup is None:
            kept.append(art)
        else:
            # 留长弃短
            if total_chars(art.get("paragraphs") or []) > total_chars(dup.get("paragraphs") or []):
                kept.remove(dup)
                kept.append(art)
                cut.append({**dup, "_cutReason": "cluster_duplicate"})
            else:
                cut.append({**art, "_cutReason": "cluster_duplicate"})
    return kept, cut


def scan_day(day: Path) -> dict:
    arts = [json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(day.glob("article-*.json"))]
    sec_map = _section_map(day)

    # 闸门一：密度门禁（正文层）
    dense_kept: list[dict] = []
    density_cut: list[dict] = []
    for a in arts:
        reason = density_gate(a.get("paragraphs") or [])
        if reason:
            density_cut.append({**a, "_cutReason": f"density_low:{reason}"})
        else:
            dense_kept.append(a)

    # 闸门二：标题簇去重
    cluster_kept, cluster_cut = _cluster_dedupe(dense_kept)

    # 闸门三：配额 + CAPS（total_chars 降序）
    final, quota_cut = _apply_quota_and_caps(cluster_kept, sec_map)

    def _row(a: dict) -> dict:
        return {
            "id": a.get("id"),
            "title": a.get("title"),
            "source": a.get("source"),
            "url": a.get("url"),
            "chars": total_chars(a.get("paragraphs") or []),
            "section": sec_map.get(str(a.get("url") or ""), ""),
            "slot": _slot_of(str(a.get("url") or ""), sec_map.get(str(a.get("url") or ""), "")),
            "aiStatus": a.get("aiStatus"),
            "reason": a.get("_cutReason", ""),
        }

    # 标题去重展示用
    seen_titles: Counter[str] = Counter()
    for a in arts:
        seen_titles[str(a.get("title") or "")] += 1

    return {
        "date": day.name,
        "total": len(arts),
        "aiReady": sum(1 for a in arts if a.get("aiStatus") == "ok"),
        "survivors": [_row(a) for a in final],
        "cut": {
            "density": [_row(a) for a in density_cut],
            "cluster": [_row(a) for a in cluster_cut],
            "quota": [_row(a) for a in quota_cut],
        },
        "counts": {
            "total": len(arts),
            "densityCut": len(density_cut),
            "clusterCut": len(cluster_cut),
            "quotaCut": len(quota_cut),
            "survived": len(final),
        },
    }


def main() -> int:
    days = sorted(p for p in CONTENT.glob("2026-08-*") if p.is_dir())
    report = {
        "generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "zero-ai-rule-funnel",
        "note": "密度门禁 + 簇去重 + 配额/CAPS 纯规则；未调用任何 AI",
        "days": [scan_day(d) for d in days],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'日期':<12}{'总':>4}{'密度砍':>7}{'簇砍':>6}{'配额砍':>7}{'存活':>6}")
    for d in report["days"]:
        c = d["counts"]
        print(f"{d['date']:<12}{c['total']:>4}{c['densityCut']:>7}"
              f"{c['clusterCut']:>6}{c['quotaCut']:>7}{c['survived']:>6}")
    tot = sum(d["counts"]["total"] for d in report["days"])
    sur = sum(d["counts"]["survived"] for d in report["days"])
    print(f"{'合计':<12}{tot:>4}{'':>20}{sur:>6}")
    print(f"\n输出: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
