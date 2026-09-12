# -*- coding: utf-8 -*-
"""零 AI 成本抓取：只跑「抓取 → 组装 digest → 剪藏原文」，跳过全部 DeepSeek 调用。

用途：DeepSeek 额度耗尽时，先把当天的文章与原文落盘到 content/{date}/，
后续再补跑 AI（--reanalyze / --curate-only）。

与完整管道的差异（有意为之）：
- v2.1 起 fetch 层（fetch_candidates）本身就是纯规则零 AI（配额/CAPS 已后移
  clip 层，仅有 MAX_PRECLIP 安全阀）——本脚本清空 DEEPSEEK_API_KEY 属双保险。
- clip_content 的 analyze_article 每篇调 AI → 本脚本只调 clip_article（纯抓取）。
- 不跑 summary_content / practice_content / curate_content（都要 AI）。

产出：content/{date}/digest.json + content/{date}/article-*.json + _reports/{date}.json
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

import httpx  # noqa: E402

from kaogong.clip import clip_article  # noqa: E402
from kaogong.pipeline import build_content  # noqa: E402


def main(argv: list[str]) -> int:
    target = dt.date.fromisoformat(argv[1]) if len(argv) > 1 else dt.date.today()
    content_dir = ROOT / "content"

    # 1) 抓取 + 组装 digest
    #    v2.1：fetch_candidates 为纯规则零 AI（_pick_top/judge_item 已随配额
    #    后移摘除），清空 DEEPSEEK_API_KEY 属双保险，确保任何路径都不调 AI。
    import os as _os

    _os.environ["DEEPSEEK_API_KEY"] = ""  # 后续 load_config 全部返回空 dict
    path = build_content(target, content_dir, client=httpx.Client(timeout=20.0, follow_redirects=True))
    digest = json.loads(path.read_text(encoding="utf-8"))
    print(f"[fetch] digest -> {path}")

    # 2) 统计候选
    items: list[tuple[str, str]] = []
    per_section: list[tuple[str, int]] = []
    for sec in digest.get("sections", []):
        rows = [it for it in sec.get("items", []) if it.get("sourceUrl")]
        per_section.append((sec.get("name") or sec.get("slot") or "?", len(rows)))
        items.extend((it.get("sourceUrl", ""), it.get("title", "")) for it in rows)
    print(f"[fetch] 候选 {len(items)} 篇，分节：{per_section}")

    # 3) 纯剪藏（无 AI 分析）
    out_dir = content_dir / target.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    ok, failed = [], []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for url, title in items:
            clip = clip_article(url, title, target.isoformat(), client=client)
            if clip.get("status") == "ok":
                (out_dir / f"article-{clip['id']}.json").write_text(
                    json.dumps(clip, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                ok.append(clip)
            else:
                failed.append({"title": title, "error": clip.get("error", "")})

    print(f"[clip] 成功 {len(ok)} 篇，失败 {len(failed)} 篇")
    for f in failed:
        print(f"  ✗ {f['error'][:60]} | {f['title'][:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
