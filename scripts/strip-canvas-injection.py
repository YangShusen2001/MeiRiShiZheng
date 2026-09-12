#!/usr/bin/env python3
"""剥离画布宿主注入到 HTML 源文件里的注解属性。

## 为什么需要这个脚本

设计画布（Ardot）宿主在会话期间会给工作区里的 HTML 文件加注解，用来把 DOM 节点映射回画布节点：

    data-page-node-id="<22 位 id>"

它对运行时无害（未定义属性会被浏览器忽略），但**会写进仓库源文件**：实测 `index.html` 在 HEAD 里
0 处，经一次编辑后变成 120+ 处，`git diff` 从 2 行涨到 208 行 —— 提交进去就是宿主产物污染仓库，
评审也没法看。而且它不是一次性注入：文件被还原（`git checkout --`）后毫秒级又被写回。

已知的注入形态：
    data-page-node-id="…"        节点映射（主要形态）
    data-pnid-…="…"              历史形态
    style="…box-sizing…"         把外部 CSS 展开成内联样式（会架空样式表，**必须删**）

判据：我们自己的内联 style 从不写 `box-sizing`，所以含 `box-sizing` 的 `style=` 一定是宿主注入的。

## 用法

    python scripts/strip-canvas-injection.py                    # 检查（不写盘），列出待清理文件
    python scripts/strip-canvas-injection.py --write            # 就地清理
    python scripts/strip-canvas-injection.py --write path ...   # 只处理指定文件

退出码：0 = 干净；1 = 发现注入（未加 --write 时）。可直接用于提交前检查。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 只扫版本化的前端源文件，不碰构建产物与第三方
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".venv", "oh_modules", ".hvigor", "output"}
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("data-page-node-id", re.compile(r'\s+data-page-node-id="[^"]*"')),
    ("data-pnid", re.compile(r'\s+data-pnid-[a-z-]+="[^"]*"')),
    ("inline box-sizing style", re.compile(r'\s+style="[^"]*box-sizing[^"]*"')),
]


def iter_html() -> list[Path]:
    out: list[Path] = []
    for path in REPO.rglob("*.htm*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        out.append(path)
    return out


def strip(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, pattern in PATTERNS:
        text, n = pattern.subn("", text)
        if n:
            counts[label] = n
    return text, counts


def main() -> int:
    parser = argparse.ArgumentParser(description="剥离画布宿主注入的 HTML 注解属性")
    parser.add_argument("paths", nargs="*", help="指定文件；省略则扫描整个仓库")
    parser.add_argument("--write", action="store_true", help="就地清理（默认只检查）")
    args = parser.parse_args()

    targets = [Path(p) for p in args.paths] if args.paths else iter_html()
    dirty = 0

    for path in targets:
        if not path.is_file():
            print(f"跳过（不是文件）：{path}")
            continue
        original = path.read_text(encoding="utf-8")
        cleaned, counts = strip(original)
        if not counts:
            continue
        dirty += 1
        rel = path.relative_to(REPO) if path.is_absolute() and REPO in path.parents else path
        detail = "、".join(f"{k} ×{v}" for k, v in counts.items())
        if args.write:
            path.write_text(cleaned, encoding="utf-8")
            print(f"已清理 {rel}：{detail}")
        else:
            print(f"发现注入 {rel}：{detail}")

    if dirty == 0:
        print("✓ 未发现注入")
        return 0
    if not args.write:
        print(f"\n共 {dirty} 个文件被注入。清理：python scripts/strip-canvas-injection.py --write")
        return 1
    print(f"\n已清理 {dirty} 个文件。注意：会话期间仍可能被再次注入 —— **提交前重跑本脚本的检查模式**。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
