# -*- coding: utf-8 -*-
"""新闻源提取器单测（HTML fixture + httpx.MockTransport，不真实联网）。"""
import datetime as dt

import httpx

from kaogong.sources import (
    SOURCES,
    Source,
    _extract_pubdate,
    extract,
    fetch_source,
    is_noise_title,
    load_noise_title,
    load_sources,
    page_urls,
    source_from_dict,
    source_to_dict,
)


def _source(slot: str):
    return next(s for s in SOURCES if s.slot == slot)


def _extract(slot: str, html: str):
    src = _source(slot)

    def handler(request):
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return extract(src, client=client)


def test_extract_qstheory_yyyymmdd():
    html = '<a href="/20260812/abc123def/c.html">求是文章标题</a>'
    items = _extract("qst", html)
    assert len(items) == 1
    assert items[0].date == dt.date(2026, 8, 12)


def test_extract_renmin_title_drop():
    html = (
        '<a href="/n1/2026/0812/c1.html">人民日报评论标题</a>'
        '<a href="/n1/2026/0812/c2.html">网友热议：某某话题</a>'
    )
    items = _extract("rm", html)
    assert len(items) == 1
    assert items[0].date == dt.date(2026, 8, 12)


def test_extract_dayoo_three_groups():
    html = '<a href="/guangdong/202608/12/abc.html">广东要闻标题</a>'
    items = _extract("gd", html)
    assert len(items) == 1
    assert items[0].date == dt.date(2026, 8, 12)


def test_extract_failure_returns_empty():
    def handler(request):
        return httpx.Response(500, text="error")

    src = _source("qst")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert extract(src, client=client) == []


def test_fetch_source_assigns_slot():
    src = _source("qst")
    html = '<a href="/20260812/abc123def/c.html">标题</a>'

    def handler(request):
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_source(src, client=client)
    assert len(cands) == 1
    assert cands[0].slot == "qst"
    assert cands[0].date == dt.date(2026, 8, 12)


def test_pubdate_title_summary_and_date():
    """URL 无日期：抓文章页取日期，锚文本 min/max 得标题/摘要。"""
    src = _source("nf")

    def handler(request):
        if "node_" in request.url.path:
            return httpx.Response(200, text='<div>发布日期：2026-08-12 08:00</div>')
        return httpx.Response(
            200,
            text=(
                '<a href="https://opinion.southcn.com/node_0244e664bd/10b339a5bf.shtml">短标题</a>'
                '<a href="https://opinion.southcn.com/node_0244e664bd/10b339a5bf.shtml">这是更长的摘要文本内容</a>'
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_source(src, client=client)
    assert len(cands) == 1
    assert cands[0].date == dt.date(2026, 8, 12)
    assert cands[0].title == "短标题"
    assert cands[0].summary == "这是更长的摘要文本内容"
    assert cands[0].slot == "nf"


def test_pubdate_collects_pool_three_times_limit():
    """扩池：pubdate 源收集到 limit×3 而不是 limit，保证当天文章不漏。"""
    src = Source(
        name="测试", slot="nf", page="https://opinion.southcn.com/",
        href_re=r"opinion\.southcn\.com/node_[0-9a-f]+/[0-9a-f]+\.shtml",
        mode="pubdate", limit=3,
    )

    def handler(request):
        if "node_" in request.url.path:
            return httpx.Response(200, text='<div>发布日期：2026-08-12 08:00</div>')
        links = "".join(
            f'<a href="https://opinion.southcn.com/node_0244e664bd/{i:08x}.shtml">标题{i}</a>'
            for i in range(12)
        )
        return httpx.Response(200, text=links)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = _extract_pubdate(src, client=client)
    assert len(cands) == 9  # limit(3) × 3


def test_pubdate_fallback_to_month_first():
    """gov.cn URL 只有年月，抓不到精确日期时回退当月 1 日。"""
    src = _source("gov")

    def handler(request):
        if "content_" in request.url.path:
            return httpx.Response(200, text="<div>无日期</div>")
        return httpx.Response(200, text='<a href="/zhengce/content/202608/content_1.html">政策标题</a>')

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_source(src, client=client)
    assert len(cands) == 1
    assert cands[0].date == dt.date(2026, 8, 1)


def test_page_urls_generates_subsequent_pages():
    assert page_urls("https://x.com/index.html", 3, "https://x.com/index{i}.html") == [
        "https://x.com/index.html",
        "https://x.com/index1.html",
        "https://x.com/index2.html",
    ]
    # 无模板或单页时只抓首页
    assert page_urls("https://x.com/", 3, "") == ["https://x.com/"]
    assert page_urls("https://x.com/", 1, "https://x.com/index{i}.html") == ["https://x.com/"]


def test_extract_paginates_and_dedups():
    """mode=url 带 page_template 时翻页抓取，跨页按 URL 去重。"""
    src = Source(
        "测试翻页", "x", "https://x.com/index.html",
        r"/(\d{8})/", date_fn=lambda m: dt.date(2026, 8, 16),
        limit=3, max_pages=3, page_template="https://x.com/index{i}.html",
    )

    def handler(request):
        if request.url.path == "/index.html":
            return httpx.Response(200, text='<a href="/20260816/a.html">标题A</a>')
        if request.url.path == "/index1.html":
            return httpx.Response(
                200,
                text='<a href="/20260816/b.html">标题B</a>'
                     '<a href="/20260816/a.html">标题A（重复）</a>',
            )
        if request.url.path == "/index2.html":
            return httpx.Response(200, text='<a href="/20260816/c.html">标题C</a>')
        return httpx.Response(404, text="")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        items = extract(src, client=client)
    assert [i.url for i in items] == [
        "https://x.com/20260816/a.html",
        "https://x.com/20260816/b.html",
        "https://x.com/20260816/c.html",
    ]


def test_new_news_cn_sources_parse():
    """新增新华网时政/评论源，URL 内嵌日期可解析。"""
    by_name = {s.name: s for s in SOURCES}
    for name in ("新华网时政", "新华网评论"):
        src = by_name[name]
        html = f'<a href="/20260816/abcdef123/c.html">{name}标题</a>'
        items = _extract_by(src, html)
        assert len(items) == 1
        assert items[0].date == dt.date(2026, 8, 16)


def _extract_by(src, html):
    def handler(request):
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return extract(src, client=client)


def test_is_noise_title_filters_promotional_content():
    """推广/无意义标题（C视觉·每日一图 等）被识别为噪声。"""
    assert is_noise_title("广东：千帆竞发迎开渔｜C视觉·每日一图（2026年8月16日）")
    assert is_noise_title("每日一图丨奋进四川的磅礴气象")
    assert not is_noise_title("习近平：提高防灾减灾救灾能力")
    assert not is_noise_title("切实维护人民群众生命财产安全和社会稳定")


def test_source_dict_roundtrip():
    """Source ↔ dict 往返：date_fn 按函数名还原、fallback_re 还原月首回退。"""
    src = _source("gov")  # pubdate + fallback_re
    d = source_to_dict(src)
    back = source_from_dict(d)
    assert back.name == src.name
    assert back.slot == src.slot
    assert back.mode == src.mode
    assert back.fallback_re == src.fallback_re
    assert back.limit == src.limit


def test_load_sources_prefers_config_over_defaults():
    cfg = {"sources": [{"name": "测试源", "slot": "test", "page": "https://x.com/", "mode": "url", "limit": 5}]}
    srcs = load_sources(cfg)
    assert [s.name for s in srcs] == ["测试源"]
    # 配置缺失/空则回退默认
    assert load_sources({}) == SOURCES


def test_load_noise_title_from_config():
    cfg = {"noiseTitle": ["推广", "广告"]}
    assert load_noise_title(cfg) == ("推广", "广告")
    # 0018：默认值含 scol 视频栏目关键词（候选阶段过滤视频稿）
    assert load_noise_title({}) == (
        "C视觉", "每日一图", "每日一景", "影像数据库",
        "理响巴蜀", "政策翻译机", "空天侦探社", "食情局", "成工之恋", "川观解盘",
    )
