# -*- coding: utf-8 -*-
"""跨源近似去重（移植自原 site_builder/digest_md.py 的纯函数部分）。

用途：不同新闻源（人民网/新华网/政府网…）常转载同一事件，标题略有差异。
通过「标题归一化 + 连续公共子串」判定近似重复，避免日报里同一条新闻出现多次。
"""
from __future__ import annotations

import re

from .http import IndexedLink
from .models import Candidate

# 常见来源前缀，归一化时去掉，避免「人民网：xxx」与「xxx」被当成两条
SOURCE_PREFIXES = [
    "人民网", "新华网", "新华社", "人民日报", "半月谈", "求是网",
    "南方网", "南方日报", "广州日报", "大洋网", "中国政府网", "粤学习",
]

_FULLWIDTH_RE = re.compile(r"[！-～]")
_PUNCT_RE = re.compile(r"[，。！？、；：,.!?;:<>\"'“”‘’【】\[\]（）()\-—_|/\\]")


def _fullwidth_to_halfwidth(ch: str) -> str:
    return chr(ord(ch) - 0xFEE0)


def normalize_title(t: str) -> str:
    """标题归一化：去来源前缀、全角转半角、去标点与空白，用于近似去重。"""
    t = str(t or "").replace("\u3000", " ").strip()
    t = _FULLWIDTH_RE.sub(lambda m: _fullwidth_to_halfwidth(m.group(0)), t)
    for p in SOURCE_PREFIXES:
        if t.startswith(p):
            t = t[len(p):]
    t = t.strip(" ：:|-—（）()[]【】")
    t = _PUNCT_RE.sub("", t)
    return re.sub(r"\s+", "", t)


def is_same_event(a: str, b: str) -> bool:
    """归一化标题的近似事件判定：共享任意连续 ≥8 字（4 个连续双字词）视为同事件。

    阈值保守（宁多勿漏）：两篇不同文章恰好连续 8 字相同的概率极低。
    """
    if not a or not b:
        return False
    if a == b:
        return True
    bigrams = {b[i:i + 2] for i in range(len(b) - 1)}
    run = 0
    for i in range(len(a) - 1):
        if a[i:i + 2] in bigrams:
            run += 1
            if run >= 4:  # 连续 4 个双字词 = 8 字重合
                return True
        else:
            run = 0
    return False


def dedupe_items(items: list[IndexedLink]) -> list[IndexedLink]:
    """按 URL 与归一化标题去重；来源优先级 = 调用方传入顺序（先到先得）。"""
    seen_url: set[str] = set()
    seen_title: list[str] = []
    out: list[IndexedLink] = []
    for it in items:
        if it.url in seen_url:
            continue
        norm = normalize_title(it.title)
        if norm and any(is_same_event(norm, s) for s in seen_title):
            continue
        seen_url.add(it.url)
        if norm:
            seen_title.append(norm)
        out.append(it)
    return out


# —— 簇去重（v2 §4）：同源同日「拆条簇」聚合 ——
# 黄金样本佐证：遂宁专场发布会 7 条拆条（83320357-83320365 相邻序号，标题共享
# 「丨起步奋进“十五五”遂宁专场新闻发布会」后缀）应聚合为 1 条。
# 栏目白名单已先行裁剪掉 ggxw 快讯，簇去重是双保险（若未来理论栏目也出拆条，仍能聚合）。

_HOST_RE = re.compile(r"https?://([^/?#]+)", re.IGNORECASE)
_NUM_RUN_RE = re.compile(r"\d+")


def _host_of(url: str) -> str:
    """从 URL 提取 host（小写），取不到返回空串。"""
    m = _HOST_RE.search(url or "")
    return m.group(1).lower() if m else ""


def _article_serial(url: str) -> int | None:
    """URL 里最末一个 ≥4 位数字（文章序号，如 ggxw/202609/83320358.html 的 83320358）。

    小数字（/n1/、日期 11 等）不参与，避免把路径杂讯当序号。
    """
    nums = [int(n) for n in _NUM_RUN_RE.findall(url or "") if len(n) >= 4]
    return nums[-1] if nums else None


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度（滚动数组 DP；标题长度小，开销可忽略）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def cluster_dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """簇去重：同源同日的拆条簇聚合为每簇一条（保留列表首条，先到先得）。

    判据（多信号投票，任一命中即同簇；前提 = 同 host ∧ 同日，归一化标题口径）：
      ① 标题近似：最长公共子串 ≥8 字（方案 v2 §4「is_same_event ≥8 字」的本意；
         不直接复用 is_same_event——其实现的实际阈值是 5 字连续子串（4 个重叠
         双字词），会把同源同日、标题里都含「2026年」的两篇无关文章误合并，
         黄金样本回放实证：丰收节 vs 博士后申报，LCS=5（"2026年"）误 fired）；
      ② 序号相邻：LCS≥6 字 ∧ URL 文章序号差 ≤2（同源拆条信号）。
    用并查集做连通分量（链式相邻也能聚成一簇），跨源/跨日不合并。
    """
    n = len(candidates)
    if n <= 1:
        return list(candidates)
    norms = [normalize_title(c.title) for c in candidates]
    hosts = [_host_of(c.url) for c in candidates]
    serials = [_article_serial(c.url) for c in candidates]
    lcs_cache: dict[tuple[int, int], int] = {}
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # 路径减半
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)  # 小索引当根 → 每簇保留列表首条

    for i in range(n):
        for j in range(i + 1, n):
            if hosts[i] != hosts[j] or candidates[i].date != candidates[j].date:
                continue
            key = (i, j)
            lcs = lcs_cache.get(key)
            if lcs is None:
                lcs = _lcs_len(norms[i], norms[j])
                lcs_cache[key] = lcs
            same = lcs >= 8
            if not same and serials[i] is not None and serials[j] is not None:
                same = lcs >= 6 and abs(serials[i] - serials[j]) <= 2
            if same:
                union(i, j)

    seen_clusters: set[int] = set()
    out: list[Candidate] = []
    for idx, c in enumerate(candidates):
        root = find(idx)
        if root not in seen_clusters:
            seen_clusters.add(root)
            out.append(c)
    return out
