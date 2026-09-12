# -*- coding: utf-8 -*-
"""领域模型：与 content/schema/*.json 契约一一对应。

约定：Python 内部用 snake_case，`to_json()` 输出 camelCase（跨语言传输格式）。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass
class DigestItem:
    """日报里的单条新闻。"""
    title: str
    date: str          # 短写 "08-12"
    source_url: str    # 原文链接
    summary: str = ""  # 摘要（政策解读/地区/南方时评等栏目有）
    quotes: list[str] = field(default_factory=list)  # 金句摘录

    def to_json(self) -> dict:
        out: dict = {
            "title": self.title,
            "date": self.date,
            "sourceUrl": self.source_url,
        }
        if self.summary:
            out["summary"] = self.summary
        if self.quotes:
            out["quotes"] = self.quotes
        return out


@dataclass
class DigestSection:
    """日报的一个栏目，如 "全国时政要闻" / "申论精读"。"""
    id: str
    title: str
    items: list[DigestItem] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "items": [i.to_json() for i in self.items],
        }


@dataclass
class DailyDigest:
    """一份每日日报。"""
    date: str
    title: str
    sections: list[DigestSection] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "date": self.date,
            "title": self.title,
            "sections": [s.to_json() for s in self.sections],
        }


@dataclass
class Candidate:
    """抓取阶段的候选条目（管道内部类型，不进 content 契约）。

    由各新闻源适配器产出，经去重后由 build_digest 组装成 DailyDigest。
    """
    title: str
    url: str
    date: dt.date
    slot: str          # 栏目槽位：pol/gov/shi/qst/xh/rm/byt/essay/gdp/nf
    summary: str = ""
    key: bool = False
    # 产出该候选的源名（v2 §3 每源配额的分组键；为空时回退 URL host）
    source_name: str = ""
