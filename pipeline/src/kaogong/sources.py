# -*- coding: utf-8 -*-
"""新闻源适配层：官方源列表页 → Candidate 列表。

三大类源（按「日期怎么来」划分）：
- url        日期内嵌在文章 URL 里（如 /20260812/），直接解析；
- list_pages 人民网式多页频道（index.html → index{i}.html），复用 http.list_pages；
- pubdate    URL 无精确日期（如 gd.gov.cn、南方网），抓文章页 page_pub_date 取日期，
             锚文本 min/max 得标题/摘要；取不到日期时可用 fallback（如 gov/scol 回退到当月 1 日）。

设计：抽成配置表 + 通用提取器，新增源 = 加一行 Source 配置。
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Callable

import httpx

from .http import IndexedLink, abs_url, anchors, clean, fetch, list_pages, page_pub_date
from .models import Candidate

DateFn = Callable[[re.Match], dt.date | None]
FallbackFn = Callable[[str], dt.date | None]


# —— 日期解析小函数（URL 内嵌日期源用，每种 URL 形态一个）——

def _ymd(m: re.Match) -> dt.date | None:
    """三组 year/month/day（可能不补零），如 dayoo / jiangsu。"""
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except (ValueError, IndexError):
        return None


def _yyyymmdd(m: re.Match) -> dt.date | None:
    """一组 YYYYMMDD，如 qstheory / news.cn / banyuetan。"""
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _n1_yyyymmdd(m: re.Match) -> dt.date | None:
    """两组 year + monthday（/n1/YYYY/MMDD/），如 people.com.cn 详情页。"""
    try:
        return dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d").date()
    except ValueError:
        return None


# —— pubdate 源的日期回退：URL 里只有年月，抓不到精确日期时退回当月 1 日 ——

def _month_first(regex: str) -> FallbackFn:
    def fn(url: str) -> dt.date | None:
        m = re.search(regex, url)
        if not m:
            return None
        try:
            return dt.datetime.strptime(m.group(1), "%Y%m").date()
        except ValueError:
            return None
    return fn


@dataclass(frozen=True)
class Source:
    """一个官方源的抓取配置。"""
    name: str
    slot: str                 # 栏目槽位（与 build.SLOT_SOURCE 对应）
    page: str                 # 列表页 URL
    href_re: str = ""         # 匹配文章链接的正则
    mode: str = "url"         # url | list_pages | pubdate
    date_fn: DateFn | None = None          # mode=url：从匹配解析日期
    fallback_re: str = ""     # mode=pubdate：日期回退（URL 里的年月正则）
    title_min: int = 1
    title_drop: tuple[str, ...] = ()
    limit: int = 20
    max_pages: int = 6        # mode=list_pages / url / pubdate 的翻页数
    page_template: str = ""   # 可选翻页：含 {i} 的完整 URL（i 从 1 起表示第 2 页起）


def page_urls(page: str, max_pages: int, template: str = "") -> list[str]:
    """列表页翻页 URL：首页 + template 生成的后续页（i 从 1 起）。"""
    if not template or max_pages <= 1:
        return [page]
    return [page] + [template.format(i=i) for i in range(1, max_pages)]


# date_fn 序列化映射（函数名 → 函数），用于后台增删改源时的 JSON 往返
_DATE_FN_MAP: dict[str, DateFn] = {
    "_yyyymmdd": _yyyymmdd,
    "_ymd": _ymd,
    "_n1_yyyymmdd": _n1_yyyymmdd,
}


def source_to_dict(s: Source) -> dict:
    """Source → JSON 可序列化 dict（date_fn 存函数名）。"""
    d: dict = {
        "name": s.name,
        "slot": s.slot,
        "page": s.page,
        "href_re": s.href_re,
        "mode": s.mode,
        "title_min": s.title_min,
        "title_drop": list(s.title_drop),
        "limit": s.limit,
        "max_pages": s.max_pages,
        "page_template": s.page_template,
        "fallback_re": s.fallback_re,
    }
    if s.date_fn is not None:
        d["date_fn"] = s.date_fn.__name__
    return d


def source_from_dict(d: dict) -> Source:
    """dict → Source（date_fn 按函数名还原，fallback_re 还原月首回退）。"""
    return Source(
        name=str(d.get("name", "")),
        slot=str(d.get("slot", "")),
        page=str(d.get("page", "")),
        href_re=str(d.get("href_re", "")),
        mode=str(d.get("mode", "url")),
        date_fn=_DATE_FN_MAP.get(str(d.get("date_fn", ""))),
        fallback_re=str(d.get("fallback_re", "")),
        title_min=int(d.get("title_min", 1)),
        title_drop=tuple(str(x) for x in (d.get("title_drop") or [])),
        limit=int(d.get("limit", 20)),
        max_pages=int(d.get("max_pages", 6)),
        page_template=str(d.get("page_template", "")),
    )


def load_sources(config: dict | None) -> tuple[Source, ...]:
    """从站点配置读新闻源；配置缺失/非法时回退默认源。"""
    raw = (config or {}).get("sources")
    if not isinstance(raw, list) or not raw:
        return DEFAULT_SOURCES
    out: list[Source] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(source_from_dict(item))
            except Exception:
                continue
    return tuple(out) if out else DEFAULT_SOURCES


def load_noise_title(config: dict | None) -> tuple[str, ...]:
    """从站点配置读内容筛选关键词；配置缺失时回退默认。"""
    raw = (config or {}).get("noiseTitle")
    if not isinstance(raw, list) or not raw:
        return DEFAULT_NOISE_TITLE
    return tuple(str(x) for x in raw if str(x).strip())


# 无意义/推广类标题过滤（默认值；可在后台站点配置里覆盖）。命中任一关键词直接丢弃。
# 0018：scol 视频栏目（理响巴蜀/政策翻译机等）对纯文本阅读站无价值，候选阶段直接过滤，
# 避免剪藏时以 video_no_text 失败（命中即整篇不进，属可接受取舍）。
DEFAULT_NOISE_TITLE: tuple[str, ...] = (
    "C视觉", "每日一图", "每日一景", "影像数据库",
    "理响巴蜀", "政策翻译机", "空天侦探社", "食情局", "成工之恋", "川观解盘",
)

# 向后兼容别名
NOISE_TITLE = DEFAULT_NOISE_TITLE


def is_noise_title(title: str, noise: tuple[str, ...] | None = None) -> bool:
    """命中推广/无意义关键词（如 C视觉·每日一图）返回 True。noise 可注入。"""
    for p in (noise if noise is not None else DEFAULT_NOISE_TITLE):
        if p in title:
            return True
    return False


DEFAULT_SOURCES: tuple[Source, ...] = (
    # —— URL 内嵌精确日期 ——
    Source("求是网", "qst", "http://www.qstheory.cn/",
           r"/(\d{8})/[0-9a-f]+/c\.html", date_fn=_yyyymmdd, limit=12),
    Source("新华时评", "xh", "https://www.news.cn/depthobserve/xhsd.html",
           r"/(\d{8})/[0-9a-f]+/c\.html", date_fn=_yyyymmdd, limit=12),
    Source("新华网评论", "xh", "http://www.news.cn/comments/",
           r"/(\d{8})/[0-9a-f]+/c\.html", date_fn=_yyyymmdd, limit=12),
    Source("人民日报评论", "rm", "http://opinion.people.com.cn/GB/8213/49160/index.html",
           r"/n1/(\d{4})/(\d{4})/", date_fn=_n1_yyyymmdd, limit=10, title_drop=("网友热议",)),
    Source("半月谈今日谈", "byt", "http://www.banyuetan.org/byt/jinritan/index.html",
           r"/jrt/detail/(\d{8})/", date_fn=_yyyymmdd, limit=8),
    Source("大洋网广东", "gd", "https://www.dayoo.com/",
           r"/guangdong/(\d{4})(\d{2})/(\d{2})/", date_fn=_ymd, limit=8),
    Source("江苏政府网要闻", "js", "http://www.jiangsu.gov.cn/col/col84322/index.html",
           r"/art/(\d{4})/(\d{1,2})/(\d{1,2})/", date_fn=_ymd, limit=15),

    # —— 人民网多页频道（list_pages）——
    Source("人民网时政", "pol", "http://politics.people.com.cn/GB/1024/index.html",
           mode="list_pages", limit=20, max_pages=8),
    Source("新华网时政", "pol", "http://www.news.cn/politics/",
           r"/(\d{8})/[0-9a-f]+/c\.html", date_fn=_yyyymmdd, limit=15),
    Source("人民网时评", "shi", "http://opinion.people.com.cn/GB/223228/index.html",
           mode="list_pages", limit=15, max_pages=6),

    # —— URL 无精确日期：抓文章页取发布日期 ——
    Source("中国政府网政策", "gov", "https://www.gov.cn/zhengce/",
           r"/zhengce/content/(\d{6})/", mode="pubdate",
           fallback_re=r"/zhengce/content/(\d{6})/", limit=10),
    Source("广东政府网要闻", "gd", "https://www.gd.gov.cn/gdywdt/",
           r"/content/post_", mode="pubdate", limit=12),
    Source("广东政策解读", "gdp", "https://www.gd.gov.cn/zwgk/zcjd/",
           r"/content/post_", mode="pubdate", limit=15),
    Source("南方时评", "nf", "https://opinion.southcn.com/",
           r"opinion\.southcn\.com/node_[0-9a-f]+/[0-9a-f]+\.shtml", mode="pubdate", limit=10),
    Source("四川全媒快讯", "sc", "https://sichuan.scol.com.cn/ggxw/",
           r"ggxw/(\d{6})/", mode="pubdate",
           fallback_re=r"ggxw/(\d{6})/", limit=12),
    Source("天府评论", "sc", "https://comment.scol.com.cn/",
           r"comment\.scol\.com\.cn", mode="pubdate", limit=12),
    Source("交汇点时评", "js", "https://www.xhby.net/xpinglun/",
           r"/content/", mode="pubdate", title_drop=("举报", "联系我们"), limit=10),
)

# 向后兼容别名
SOURCES = DEFAULT_SOURCES


def extract(source: Source, *, client: httpx.Client | None = None) -> list[IndexedLink]:
    """通用提取器（mode=url）：抓列表页（可翻页）→ 匹配 URL 日期 → 清洗/过滤标题 → 去重。"""
    out: list[IndexedLink] = []
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    for page in page_urls(source.page, source.max_pages, source.page_template):
        try:
            text = fetch(page, client=client)
        except Exception:
            break
        added = 0
        for href, txt in anchors(text):
            m = re.search(source.href_re, href)
            if not m or source.date_fn is None:
                continue
            d = source.date_fn(m)
            if d is None:
                continue
            t = clean(txt)
            if not t or len(t) < source.title_min:
                continue
            if any(x in t for x in source.title_drop):
                continue
            if t in seen_titles:
                continue
            u = abs_url(href, page)
            if u in seen_urls:
                continue
            seen_titles.add(t)
            seen_urls.add(u)
            out.append(IndexedLink(d, t, u))
            added += 1
            if len(out) >= source.limit:
                return out
        if added == 0:
            break
    return out


def _extract_pubdate(source: Source, *, client: httpx.Client | None = None) -> list[Candidate]:
    """pubdate 提取器（可翻页）：锚文本 min/max 得标题/摘要，抓文章页取精确发布日期。"""
    by_url: dict[str, list[str]] = {}
    for page in page_urls(source.page, source.max_pages, source.page_template):
        try:
            text = fetch(page, client=client)
        except Exception:
            break
        added = 0
        for href, txt in anchors(text):
            if not re.search(source.href_re, href):
                continue
            t = clean(txt)
            if not t or any(x in t for x in source.title_drop):
                continue
            u = abs_url(href, page)
            if u not in by_url:
                added += 1
            by_url.setdefault(u, []).append(t)
        if added == 0:
            break
    out: list[Candidate] = []
    for u, ts in by_url.items():
        if not ts:
            continue
        title = min(ts, key=len)
        summary = max(ts, key=len)
        if summary == title:
            summary = ""
        d = page_pub_date(u, client=client)
        if d is None and source.fallback_re:
            d = _month_first(source.fallback_re)(u)
        if d is None:
            continue
        out.append(Candidate(title=title, url=u, date=d, slot=source.slot, summary=summary))
        # 扩池：收集到 limit×3 再交给 fetch_candidates 过滤当天，保证当天文章不漏
        if len(out) >= source.limit * 3:
            break
    return out


def fetch_source(source: Source, *, client: httpx.Client | None = None) -> list[Candidate]:
    """抓一个源，产出带槽位的 Candidate 列表（交给 build_digest 组装）。"""
    if source.mode == "pubdate":
        return _extract_pubdate(source, client=client)
    if source.mode == "list_pages":
        links = list_pages(source.page, source.max_pages, client=client)
        return [
            Candidate(title=link.title, url=link.url, date=link.date, slot=source.slot)
            for link in links[:source.limit]
        ]
    return [
        Candidate(title=link.title, url=link.url, date=link.date, slot=source.slot)
        for link in extract(source, client=client)
    ]
