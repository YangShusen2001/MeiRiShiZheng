# -*- coding: utf-8 -*-
"""政策档案正文补跑 AI 标注：让 `/read/<id>/` 的政策阅读页真的有考点/观点/术语/数字。

背景
----
政策档案（`content/archive/<YYYY-MM>/`）此前只跑了**策展层**
（`scripts/curate-archive.py` → `archive.json` 的 importance/topic/gist/figures），
**没有跑文章层**。于是 1137 篇政策正文里 `aiStatus` 字段全部缺失，
而阅读页是 `aiStatus === "ok"` 才渲染标注 —— 政策阅读页等于只有原文。

本脚本补的就是这一层。刻意**复用** `kaogong.article_ai.analyze_article`：
同一套提示词、同一套三层密度上限、同一套 `validate_article_ai` 语义校验。
另写一套提示词会让政策页的标注密度/口径与日报页分叉。

为什么不做进 `reanalyze.py`
--------------------------
`reanalyze_content()` 的入参是**日期**（`content/<YYYY-MM-DD>/`），跑完还要回写
`_reports/<date>.json` 的统计。档案的目录键是**月份**（`content/archive/<YYYY-MM>/`）
且没有报告文件。硬塞进去要么给 reanalyze 加分支、要么让它对着不存在的报告空转。
所以单开一个脚本，共用底层函数，不共用入口。

用法
----
  # 先看会跑哪些（不花钱、不写盘）
  python scripts/annotate-archive.py --month 2026-09 --dry

  # 试跑 10 篇，验证端到端
  python scripts/annotate-archive.py --month 2026-09 --limit 10

  # 只跑「核心」（archive.json 里 importance=高）
  python scripts/annotate-archive.py --importance 高

  # 全量（4 路并发，约 20 分钟）
  python -u scripts/annotate-archive.py --workers 4

并发说明
--------
`analyze_article` 是纯函数（`deepseek.chat` 每次新建 httpx.Client，无共享状态），
可安全多线程。单篇 3~4s 几乎全是网络等待，所以 4 路接近线性加速。
429/超时会被 `analyze_article` 内部兜成 `aiStatus=error` 并计入 failures，
不会中断整批 —— 重跑同一命令即续上。

月份顺序
--------
**新的月份在前**（见 `_months`）。全量要跑一个多小时，中断不可避免；
倒序保证最近的政策先有标注。

断点续跑
--------
`aiStatus == "ok"` 的文章默认跳过，所以中断后重跑同一命令即可继续。
`--force` 才会重跑已成功的（会重新消耗 API 额度并覆盖旧标注）。

输出
----
直接回写原 `article-*.json`（`indent=2, ensure_ascii=False`，与管道其它写盘点一致），
另在 `content/_reports/annotate-archive.json` 记一份本次运行的统计（便于中断后核对）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from kaogong.article_ai import analyze_article, normalize_article  # noqa: E402
from kaogong.deepseek import load_config  # noqa: E402

ARCHIVE_DIR = ROOT / "content" / "archive"
# ⚠️ 日志**不能**放 ARCHIVE_DIR：契约测试 `test_content_schema.py` 会扫
# `content/<非 _ 开头目录>/*.json`，`_annotate-log.json` 落进去 → classify_artifact 返回 None
# → `test_published_content_matches_schema` 红。它只排除 `_` 开头的**目录**，不排除文件。
# 放 `content/_reports/`：既有目录、被测试排除、且本就是「运行统计」的既定位置。
LOG_PATH = ROOT / "content" / "_reports" / "annotate-archive.json"


def _months(requested: list[str]) -> list[str]:
    """月份列表，**新的在前**。

    顺序即处理顺序。倒序是刻意的：全量 1100+ 篇要跑一个多小时，
    中断不可避免（额度、网络、关终端）。倒序保证「最近的政策先有标注」——
    对考公用户而言 2026-08 的价值远高于 2025-01，中断时不该把好月份留在队尾。
    """
    if requested:
        return sorted(requested, reverse=True)
    return sorted(
        (p.name for p in ARCHIVE_DIR.iterdir() if p.is_dir() and p.name[:4].isdigit()),
        reverse=True,
    )


def _importance_index(month: str) -> dict[str, str]:
    """url → importance。拿不到 archive.json 时返回空字典（不过滤，全部纳入）。"""
    path = ARCHIVE_DIR / month / "archive.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {str(it.get("url", "")): str(it.get("importance", "")) for it in doc.get("items", [])}


def collect(months: list[str], importance: str | None, force: bool) -> list[Path]:
    """按月份顺序收集待跑文件。顺序即处理顺序（新月份在前由 _months 决定）。"""
    out: list[Path] = []
    for month in months:
        directory = ARCHIVE_DIR / month
        if not directory.is_dir():
            continue
        wanted = _importance_index(month) if importance else {}
        for path in sorted(directory.glob("article-*.json")):
            try:
                article = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if article.get("status") != "ok":
                continue
            if not (article.get("paragraphs") or []):
                continue
            if not force and article.get("aiStatus") == "ok":
                continue
            if importance and wanted.get(str(article.get("url", ""))) != importance:
                continue
            out.append(path)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="政策档案正文 AI 标注补跑")
    parser.add_argument("--month", action="append", default=[], help="限定月份 YYYY-MM，可重复；默认全部")
    parser.add_argument("--importance", choices=["高", "中", "低"], help="只跑该重要度（读 archive.json）")
    parser.add_argument("--limit", type=int, default=0, help="最多跑几篇（0 = 不限）")
    parser.add_argument("--force", action="store_true", help="连 aiStatus=ok 的也重跑（重新消耗额度）")
    parser.add_argument("--dry", action="store_true", help="只列出待跑清单，不调 API、不写盘")
    parser.add_argument("--sleep", type=float, default=0.0, help="每篇之间额外等待秒数（默认 0；仅 --workers 1 生效）")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="并发线程数（默认 1 = 串行）。单篇 3~4s 几乎全是网络等待，4 路可把全量从 ~70min 压到 ~20min",
    )
    parser.add_argument("--quiet", action="store_true", help="只打汇总，不打每篇进度")
    args = parser.parse_args()

    months = _months(args.month)
    targets = collect(months, args.importance, args.force)
    if args.limit:
        targets = targets[: args.limit]

    print(f"月份范围：{', '.join(months)}")
    print(f"待跑：{len(targets)} 篇" + (f"（重要度={args.importance}）" if args.importance else ""))
    if args.dry:
        for path in targets:
            print("  " + str(path.relative_to(ROOT)))
        return 0
    if not targets:
        print("没有需要补跑的文章（全部已是 aiStatus=ok，或用 --force 强制重跑）")
        return 0

    cfg = load_config()
    if not cfg.get("deepseek_api_key"):
        print("未配置 DEEPSEEK_API_KEY：环境变量与仓库根 .env.local 都没有，终止。", file=sys.stderr)
        return 2

    started = time.time()
    ok = error = 0
    failures: list[dict[str, str]] = []
    total_ann = 0
    total_terms = 0

    def process(path: Path) -> tuple[Path, str, int, int, str]:
        """读 → 标注 → 写盘。纯函数式，无共享状态，可多线程并发。

        逐篇立即落盘是**续跑的基础**：中断时已完成的不重跑。
        """
        article = json.loads(path.read_text(encoding="utf-8"))
        updated = analyze_article(normalize_article(article), cfg)
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        annotations = updated.get("aiAnnotations") or []
        terms = [a for a in annotations if a.get("type") == "term" and a.get("explanation")]
        return (
            path,
            str(updated.get("aiStatus", "")),
            len(annotations),
            len(terms),
            str(updated.get("aiError", "")),
        )

    def handle(index: int, result: tuple[Path, str, int, int, str]) -> None:
        nonlocal ok, error, total_ann, total_terms
        path, status, n_ann, n_terms, reason = result
        total_ann += n_ann
        total_terms += n_terms
        if status == "ok":
            ok += 1
        else:
            error += 1
            failures.append({"file": path.name, "reason": reason[:80]})
        if not args.quiet:
            elapsed = time.time() - started
            rate = elapsed / index
            eta = rate * (len(targets) - index)
            print(
                f"[{index}/{len(targets)}] {'ok ' if status == 'ok' else 'ERR'}"
                f" 标注 {n_ann:>2}（术语带释义 {n_terms}）"
                f" · 均 {rate:.1f}s · 余 ~{eta / 60:.0f}min · {path.parent.name}/{path.name}",
                flush=True,  # 重定向到文件时默认全缓冲，不加 flush 会十几分钟看不到一行
            )

    if args.workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process, path): path for path in targets}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                path = futures[future]
                try:
                    handle(index, future.result())
                except Exception as exc:  # 兜底：单篇炸掉不能拖垮整批
                    error += 1
                    failures.append({"file": path.name, "reason": f"worker:{type(exc).__name__}"})
                    print(f"[{index}/{len(targets)}] ERR 线程异常 {type(exc).__name__} · {path.name}", flush=True)
    else:
        for index, path in enumerate(targets, 1):
            handle(index, process(path))
            if args.sleep:
                time.sleep(args.sleep)

    elapsed = time.time() - started
    summary = {
        "ranAt": dt.datetime.now().isoformat(timespec="seconds"),
        "months": months,
        "importance": args.importance or "",
        "force": args.force,
        "workers": args.workers,
        "requested": len(targets),
        "ok": ok,
        "error": error,
        "annotations": total_ann,
        "termsWithExplanation": total_terms,
        "elapsedSeconds": round(elapsed, 1),
        "failures": failures,
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "─" * 60)
    print(f"完成 {ok + error} 篇 · ok {ok} · error {error} · 耗时 {elapsed / 60:.1f} 分钟")
    print(f"标注合计 {total_ann} 条（其中带释义术语 {total_terms} 条）")
    if failures:
        print(f"失败 {len(failures)} 篇，前 5 条：")
        for f in failures[:5]:
            print(f"  {f['file']} ← {f['reason']}")
        print(f"（完整清单见 {LOG_PATH.relative_to(ROOT)}；重跑同一命令即可续跑）")
    print(f"日志：{LOG_PATH.relative_to(ROOT)}")
    return 0 if error == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
