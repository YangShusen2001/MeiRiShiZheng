# -*- coding: utf-8 -*-
"""候选 → DailyDigest 组装（替代原 build_md 的拼 markdown 部分）。

纯函数、无 IO：只把去重后的候选按「栏目槽位」分组，产出结构化 DailyDigest。
金句/正文摘要的抓取属 IO，放在单独的「富化」阶段，不混进这里。
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from .dedupe import cluster_dedupe, dedupe_items
from .http import IndexedLink
from .models import Candidate, DailyDigest, DigestItem, DigestSection

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 槽位 → 人读来源名（v2 §6：gd/sc/js 随地方分节删除；
# essay 承接大洋网 + 川观理论栏目——保留地方栏目的文章统一进申论精读，拍板⑧）
SLOT_SOURCE = {
    "pol": "人民网时政",
    "gov": "中国政府网政策",
    "shi": "人民网时评",
    "qst": "求是网",
    "xh": "新华时评",
    "rm": "人民日报评论",
    "byt": "半月谈今日谈",
    "essay": "大洋网/川观理论栏目",
    "gdp": "广东政策",
    "nf": "南方时评",
}


def _to_item(c: Candidate) -> DigestItem:
    return DigestItem(title=c.title, date=c.date.strftime("%m-%d"), source_url=c.url, summary=c.summary)


def _dedupe(candidates: list[Candidate]) -> list[Candidate]:
    """按 URL + 归一化标题近似去重；来源优先级 = 传入顺序（先到先得）。"""
    links = [IndexedLink(c.date, c.title, c.url) for c in candidates]
    kept_urls = [link.url for link in dedupe_items(links)]
    by_url: dict[str, Candidate] = {}
    for c in candidates:
        by_url.setdefault(c.url, c)
    return [by_url[u] for u in kept_urls]


def build_digest(candidates: list[Candidate], date: dt.date) -> DailyDigest:
    """把候选按栏目槽位分组，产出结构化日报。"""
    # v2 §4 簇去重入口：同源同日拆条簇（遂宁式发布会拆条）聚合为每簇一条
    candidates = cluster_dedupe(candidates)
    by_slot: dict[str, list[Candidate]] = defaultdict(list)
    for c in candidates:
        by_slot[c.slot].append(c)

    sections: list[DigestSection] = []

    # 全国时政要闻 = 人民网时政 + 新华网时政 + 中国政府网政策（合并近似去重）
    national = _dedupe(by_slot.get("pol", []) + by_slot.get("gov", []))
    if national:
        sections.append(DigestSection("national", "全国时政要闻", [_to_item(c) for c in national]))

    # 申论精读 = 人民网时评 + 求是网 + 新华时评 + 人民日报评论 + 今日谈(最多2) + 南方时评
    #          + 大洋网/川观理论栏目（slot=essay；v2 拍板⑧：保留地方栏目统一进申论精读，
    #            黄坤明调研/琴澳/AI治理/追星四篇 IN 自然流入）（按 url 去重）
    essay: list[Candidate] = []
    seen: set[str] = set()
    for slot in ("shi", "qst", "xh", "rm"):
        for c in by_slot.get(slot, []):
            if c.url not in seen:
                seen.add(c.url)
                essay.append(c)
    for c in by_slot.get("byt", [])[:2]:
        if c.url not in seen:
            seen.add(c.url)
            essay.append(c)
    for c in by_slot.get("nf", []):
        if c.url not in seen:
            seen.add(c.url)
            essay.append(c)
    for c in by_slot.get("essay", []):
        if c.url not in seen:
            seen.add(c.url)
            essay.append(c)
    if essay:
        sections.append(DigestSection("essay", "申论精读", [_to_item(c) for c in essay]))

    # 政策解读（v2 §6：id guangdong-policy→policy，去地方化）
    gdp = by_slot.get("gdp", [])
    if gdp:
        sections.append(DigestSection("policy", "政策解读", [_to_item(c) for c in gdp]))

    return DailyDigest(
        date=date.isoformat(),
        title=f"每日日报 · {date:%Y-%m-%d}（{WEEKDAYS[date.weekday()]}）",
        sections=sections,
    )
