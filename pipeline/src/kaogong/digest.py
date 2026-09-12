# -*- coding: utf-8 -*-
"""把原项目的「每日材料 markdown」解析成结构化 DailyDigest。

这是新架构的第一段「数据契约桥」：
旧格式(md) → DailyDigest 模型 → to_json() 产出 content/*.json（符合 content/schema/digest.schema.json）。

本模块只做解析（纯函数、无 IO、无网络），抓取与 AI 生成在后续阶段接入。
"""
from __future__ import annotations

import re

from .models import DailyDigest, DigestItem, DigestSection

# 注意：\s* 会匹配“零个空格”，若不约束井号数量，`##`/`###` 会被当成 `#`。
# 用负向前瞻 (?!#) 精确限定每一级标题的井号数量，避免层级串味。
_TITLE_RE = re.compile(r"^#(?!#)\s*(.*)$")        # 一级标题，恰好一个 #
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_SECTION_RE = re.compile(r"^##(?!#)\s*(.*)$")      # 二级标题，恰好两个 #
_SUB_RE = re.compile(r"^###\s*(?:\d+\.\s*)?(.*)$")  # 三级标题，恰好三个 #
_LINK_RE = re.compile(r"\[(?:原文|原文链接)\]\((.*?)\)")
_SHORT_DATE_RE = re.compile(r"[（(](\d{2}-\d{2})[）)]")
_QUOTE_RE = re.compile(r"^>\s*(.*)$")

# 栏目标题 → slug 的稳定映射（用「包含」匹配，兼容 "今日谈（半月谈·申论素材）" 这类带注的标题）
# v2 §6：地方分节删除后清理死映射（guangdong/sichuan/jiangsu）；
# 「广东政策解读」→ policy（guangdong-policy 已去地方化），兼容新旧两种栏目标题。
SECTION_SLUG = {
    "全国时政要闻": "national",
    "申论精读": "essay",
    "今日谈": "today-talk",
    "南方时评": "south-review",
    "金句精选": "quotes",
    "高频主题": "topics",
    "值得关注的政策": "policies",
    "相关主题": "related",
    "政策解读": "policy",
    "广东政策解读": "policy",
}


def _slug(title: str) -> str:
    for key, slug in SECTION_SLUG.items():
        if key in title:
            return slug
    return title


def _short_date(text: str) -> str:
    m = _SHORT_DATE_RE.search(text)
    return m.group(1) if m else ""


def _extract_date(text: str) -> str:
    m = _DATE_RE.search(text)
    return m.group(1) if m else ""


def _clean_title(text: str) -> str:
    """去掉加粗标记与首尾空白。"""
    return text.replace("**", "").strip()


def parse_daily_md(md: str) -> DailyDigest:
    digest = DailyDigest(date="", title="", sections=[])
    cur: DigestSection | None = None
    cur_item: DigestItem | None = None

    def add_item(title: str, date: str, source_url: str) -> DigestItem:
        nonlocal cur, cur_item
        if cur is None:
            # 防御：条目不应脱离栏目存在，但解析到孤立条目时不崩，归入 orphan 栏目
            cur = DigestSection(id="orphan", title="orphan", items=[])
            digest.sections.append(cur)
        item = DigestItem(title=title, date=date, source_url=source_url)
        cur.items.append(item)
        cur_item = item
        return item

    for raw in md.splitlines():
        s = raw.strip()
        if not s:
            continue

        m = _TITLE_RE.match(s)
        if m:
            digest.title = m.group(1).strip()
            digest.date = _extract_date(s)
            continue

        m = _SECTION_RE.match(s)
        if m:
            title = m.group(1).strip()
            cur = DigestSection(id=_slug(title), title=title, items=[])
            digest.sections.append(cur)
            cur_item = None
            continue

        m = _SUB_RE.match(s)
        if m:
            raw_title = m.group(1).strip()
            add_item(
                _clean_title(_SHORT_DATE_RE.sub("", raw_title)).strip(),
                _short_date(raw_title),
                "",
            )
            continue

        m = _QUOTE_RE.match(s)
        if m and cur_item is not None:
            cur_item.quotes.append(m.group(1).strip())
            continue

        if s.startswith("- "):
            body = s[2:]
            source_url = ""
            m_link = _LINK_RE.search(body)
            if m_link:
                source_url = m_link.group(1)
                body = body[: m_link.start()] + body[m_link.end():]
            date = _short_date(body)
            body = _SHORT_DATE_RE.sub("", body)
            add_item(_clean_title(body).strip(), date, source_url)
            continue

        m_link = _LINK_RE.search(s)
        if m_link and cur_item is not None:
            cur_item.source_url = m_link.group(1)
            continue

        # 其余无结构行（如 "金句摘录："）忽略

    return digest
