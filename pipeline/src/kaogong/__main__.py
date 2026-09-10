# -*- coding: utf-8 -*-
"""CLI 入口：python -m kaogong [date] [--content-dir DIR]。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .pipeline import backfill_summaries, build_content, clip_content, practice_content, quality_gate, summary_content
from .curation import curate_content
from .deepseek import load_config as load_ai_config
from .reanalyze import reanalyze_content


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="考公日报内容管道：抓取官方源 → 产出 content/ JSON")
    p.add_argument("date", nargs="?", default=None, help="目标日期 YYYY-MM-DD，默认今天")
    p.add_argument("--content-dir", default=None, help="content 目录，默认仓库根 content/")
    p.add_argument("--reanalyze", action="store_true", help="只对已有原文补跑 AI，不重新抓取")
    p.add_argument("--curate-only", action="store_true", help="只跑选材/抽卡/连线（读已有文章，不抓取不剪藏）")
    p.add_argument("--force", action="store_true", help="配合 --reanalyze：已成功的文章也重新分析（基于干净正文）")
    args = p.parse_args(argv)
    target = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    content_dir = (
        Path(args.content_dir)
        if args.content_dir
        else Path(__file__).resolve().parents[3] / "content"
    )
    if args.curate_only:
        curation = curate_content(target, content_dir, cfg=load_ai_config())
        print(json.dumps({
            "event": "pipeline.curate",
            "date": target.isoformat(),
            "curation": curation["curation"],
        }, ensure_ascii=False))
        return 0
    if args.reanalyze:
        rewritten = reanalyze_content(target, content_dir, force_ai=args.force)
        quality = quality_gate(target, content_dir)
        print(json.dumps({
            "event": "pipeline.reanalyze",
            "date": target.isoformat(),
            "rewritten": rewritten,
            "qualityStatus": quality["qualityStatus"],
        }, ensure_ascii=False))
        return 1 if quality["qualityStatus"] == "failed" else 0
    path = build_content(target, content_dir)
    n_clips = clip_content(target, content_dir)
    backfill_summaries(target, content_dir)
    practice_path = practice_content(target, content_dir)
    summary_path = summary_content(target, content_dir)
    curation = curate_content(target, content_dir, cfg=load_ai_config())  # 选材 + 卡片 + 关系标注
    quality = quality_gate(target, content_dir)
    print(json.dumps({
        "event": "pipeline.complete",
        "date": target.isoformat(),
        "digest": str(path),
        "articles": n_clips,
        "practice": str(practice_path) if practice_path else None,
        "summary": str(summary_path) if summary_path else None,
        "curation": curation["curation"],
        "qualityStatus": quality["qualityStatus"],
    }, ensure_ascii=False))
    return 1 if quality["qualityStatus"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
