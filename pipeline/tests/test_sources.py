# -*- coding: utf-8 -*-
"""新闻源提取器单测（HTML fixture + httpx.MockTransport，不真实联网）。

v2（precision-pivot）新增：tier 过滤、栏目白/黑名单、config.json 防漂移一致性。
"""
import datetime as dt
import json
from pathlib import Path

import httpx

from kaogong.sources import (
    SOURCES,
    Source,
    _column_ok,
    _extract_pubdate,
    extract,
    fetch_source,
    is_noise_title,
    load_all_sources,
    load_noise_title,
    load_sources,
    page_urls,
    source_from_dict,
    source_to_dict,
)

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"


def _by_name(name: str) -> Source:
    return next(s for s in SOURCES if s.name == name)


def _extract_src(src: Source, html: str):
    def handler(request):
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return extract(src, client=client)


def test_extract_qstheory_yyyymmdd():
    html = '<a href="/20260812/abc123def/c.html">求是文章标题</a>'
    items = _extract_src(_by_name("求是网"), html)
    assert len(items) == 1
    assert items[0].date == dt.date(2026, 8, 12)


def test_extract_renmin_title_drop():
    html = (
        '<a href="/n1/2026/0812/c1.html">人民日报评论标题</a>'
        '<a href="/n1/2026/0812/c2.html">网友热议：某某话题</a>'
    )
    items = _extract_src(_by_name("人民日报评论"), html)
    assert len(items) == 1
    assert items[0].date == dt.date(2026, 8, 12)


def test_extract_dayoo_three_groups():
    html = '<a href="/guangdong/202608/12/abc.html">广东要闻标题</a>'
    items = _extract_src(_by_name("大洋网广东"), html)
    assert len(items) == 1
    assert items[0].date == dt.date(2026, 8, 12)


def test_extract_failure_returns_empty():
    def handler(request):
        return httpx.Response(500, text="error")

    src = _by_name("求是网")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert extract(src, client=client) == []


def test_fetch_source_assigns_slot_and_source_name():
    src = _by_name("求是网")
    html = '<a href="/20260812/abc123def/c.html">标题</a>'

    def handler(request):
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_source(src, client=client)
    assert len(cands) == 1
    assert cands[0].slot == "qst"
    assert cands[0].date == dt.date(2026, 8, 12)
    assert cands[0].source_name == "求是网"  # v2 §3：配额分组键回填


def test_pubdate_title_summary_and_date():
    """URL 无日期：抓文章页取日期，锚文本 min/max 得标题/摘要。"""
    src = _by_name("南方时评")

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
    assert cands[0].source_name == "南方时评"


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
    src = _by_name("中国政府网政策")

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
    for name in ("新华网时政", "新华网评论"):
        src = _by_name(name)
        html = f'<a href="/20260816/abcdef123/c.html">{name}标题</a>'
        items = _extract_src(src, html)
        assert len(items) == 1
        assert items[0].date == dt.date(2026, 8, 16)


def test_is_noise_title_filters_promotional_content():
    """推广/无意义标题（C视觉·每日一图 等）被识别为噪声。"""
    assert is_noise_title("广东：千帆竞发迎开渔｜C视觉·每日一图（2026年8月16日）")
    assert is_noise_title("每日一图丨奋进四川的磅礴气象")
    assert not is_noise_title("习近平：提高防灾减灾救灾能力")
    assert not is_noise_title("切实维护人民群众生命财产安全和社会稳定")


def test_is_noise_title_filters_coupon_ads():
    """v2 §2.6：消费券广告类标题进默认噪声词（大洋网广告兜底，双保险）。

    注：优惠券只在大洋网 column_drop_re（源级黑名单），不进全局噪声词。
    """
    assert is_noise_title("最高减500元！广东3000万元文旅消费券9月11日发放")
    assert not is_noise_title("某地发放文旅优惠券提振消费")


def test_source_dict_roundtrip():
    """Source ↔ dict 往返：date_fn 按函数名还原、fallback_re 还原月首回退。"""
    src = _by_name("中国政府网政策")  # pubdate + fallback_re
    d = source_to_dict(src)
    back = source_from_dict(d)
    assert back.name == src.name
    assert back.slot == src.slot
    assert back.mode == src.mode
    assert back.fallback_re == src.fallback_re
    assert back.limit == src.limit


def test_source_dict_roundtrip_tier_and_column_regexes():
    """v2 §2.3：tier / column_keep_re / column_drop_re 三字段 JSON 往返不丢。"""
    for name in ("四川全媒快讯", "大洋网广东", "天府评论", "求是网"):
        src = _by_name(name)
        back = source_from_dict(source_to_dict(src))
        assert back == src, name


# —— v2 §2.3 tier 机制 ——


def test_load_sources_filters_background_tier():
    """load_sources 只返回 core 源；background 可逆移出。

    口径说明：方案 §2.4 处置清单标 ❌ 的恰为 4 源（江苏/广东政府网要闻、天府评论、
    交汇点时评），17 - 4 = 13 个 core 源（T01 验收文字里的「11 源/6 个移出」
    与表格不一致，以表格为准，已向主理人报备）。
    """
    core = load_sources({})
    assert len(core) == 13
    names = {s.name for s in core}
    assert "四川全媒快讯" in names and "大洋网广东" in names  # 栏目白名单保留
    assert not {"江苏政府网要闻", "广东政府网要闻", "天府评论", "交汇点时评"} & names


def test_load_all_sources_keeps_background():
    """load_all_sources 供后台展示/写回：全部 17 源都在，不丢移出源。"""
    assert len(load_all_sources({})) == 17


def test_load_sources_config_background_respected():
    """配置里的 tier 同样生效：background 源不进抓取池。"""
    src = source_to_dict(_by_name("求是网")) | {"tier": "background"}
    assert load_sources({"sources": [src]}) == ()
    assert len(load_all_sources({"sources": [src]})) == 1


# —— v2 §2.3 栏目白/黑名单 ——


def test_column_ok_semantics():
    """空正则不过滤；白名单命中才过；黑名单命中即丢；白黑可组合。"""
    plain = Source("普通源", "x", "https://x.com/")
    assert _column_ok(plain, "任意标题")

    scol = _by_name("四川全媒快讯")
    assert _column_ok(scol, "构建公正合理的全球人工智能治理体系丨新思想自习室")
    assert _column_ok(scol, "追星自由不能逾越社会救助的制度边界丨天府新视界")
    assert _column_ok(scol, "在遂宁，每一名劳动者都会被看见｜天府新视界")  # 全角竖线兼容
    assert not _column_ok(scol, "以“五个发力”，实现“工业倍增”丨起步奋进“十五五”遂宁专场新闻发布会")
    assert not _column_ok(scol, "制定一体推进教育科技人才发展方案丨天天学习")

    dayoo = _by_name("大洋网广东")
    assert _column_ok(dayoo, "黄坤明到广州调研并主持召开座谈会")
    assert not _column_ok(dayoo, "最高减500元！广东3000万元文旅消费券9月11日发放")


def test_scol_column_whitelist_via_fetch_source():
    """四川在线端到端：ggxw 快讯全灭，仅两个理论栏目进池（黄金样本 20 条 → 2 条）。"""
    src = _by_name("四川全媒快讯")
    titles = [
        ("83320187", "构建公正合理的全球人工智能治理体系丨新思想自习室"),
        ("83320107", "追星自由不能逾越社会救助的制度边界丨天府新视界"),
        ("83320103", "制定一体推进教育科技人才发展方案丨天天学习"),
        ("83320358", "以“五个发力”，实现“工业倍增”丨起步奋进“十五五”遂宁专场新闻发布会"),
        ("83320357", "枢纽遂宁，如何织密立体交通网？丨起步奋进“十五五”遂宁专场新闻发布会"),
        ("83320254", "黎明任雅安市人民政府副市长、代理市长"),
        ("83320378", "2026年中国农民丰收节 四川180余场活动庆丰收"),
    ]
    links = "".join(
        f'<a href="https://sichuan.scol.com.cn/ggxw/202609/{aid}.html">{t}</a>'
        for aid, t in titles
    )

    def handler(request):
        if "/ggxw/202609/" in request.url.path:
            return httpx.Response(200, text='<div>发布日期：2026-09-11 08:00</div>')
        return httpx.Response(200, text=links)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_source(src, client=client)
    assert [c.title for c in cands] == [
        "构建公正合理的全球人工智能治理体系丨新思想自习室",
        "追星自由不能逾越社会救助的制度边界丨天府新视界",
    ]
    assert all(c.slot == "essay" for c in cands)  # 拍板⑧：保留栏目进申论精读
    assert all(c.source_name == "四川全媒快讯" for c in cands)


def test_dayoo_column_drop_re_kills_coupon_ads():
    """大洋网端到端：消费券广告被 column_drop_re 拦下，正常文章放行。"""
    src = _by_name("大洋网广东")
    html = (
        '<a href="/guangdong/202609/11/a1.htm">黄坤明到广州调研并主持召开座谈会</a>'
        '<a href="/guangdong/202609/11/a2.htm">最高减500元！广东3000万元文旅消费券9月11日发放</a>'
    )
    items = _extract_src(src, html)
    assert [i.title for i in items] == ["黄坤明到广州调研并主持召开座谈会"]


def test_extract_limit_counts_after_column_filter():
    """limit 计的是栏目过滤后的条数：白名单源扫到足够净流量才停。"""
    src = Source(
        "白名单源", "essay", "https://x.com/",
        r"/(\d{8})/", date_fn=lambda m: dt.date(2026, 9, 11),
        limit=2, column_keep_re=r"[丨｜]理论栏目",
    )
    html = "".join(
        f'<a href="/20260911/a{i}.html">快讯标题{i}：地方动态一览</a>' for i in range(5)
    ) + (
        '<a href="/20260911/b1.html">深读文章一丨理论栏目</a>'
        '<a href="/20260911/b2.html">深读文章二丨理论栏目</a>'
    )
    items = _extract_src(src, html)
    assert [i.title for i in items] == ["深读文章一丨理论栏目", "深读文章二丨理论栏目"]


# —— v2 §2.1/§2.6 config.json ↔ DEFAULT_SOURCES 一致性（防漂移）——


def test_config_json_sources_in_sync_with_defaults():
    """生产读 config.json：源清单、槽位、limit/tier/栏目正则必须与 DEFAULT_SOURCES 一致。"""
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    entries = data.get("sources") or []
    assert entries, "config.json 缺 sources"
    by_name_cfg = {e.get("name"): e for e in entries}
    by_name_def = {s.name: s for s in SOURCES}
    assert set(by_name_cfg) == set(by_name_def)
    for name, s in by_name_def.items():
        assert source_from_dict(by_name_cfg[name]) == s, f"config.json 与默认源漂移：{name}"


def test_config_json_noise_title_in_sync_with_defaults():
    data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    assert list(data.get("noiseTitle") or []) == list(load_noise_title({}))


def test_load_sources_prefers_config_over_defaults():
    cfg = {"sources": [{"name": "测试源", "slot": "test", "page": "https://x.com/", "mode": "url", "limit": 5}]}
    srcs = load_sources(cfg)
    assert [s.name for s in srcs] == ["测试源"]
    # 配置缺失/空则回退默认（v2：回退值经 tier 过滤，只含 core 源）
    assert load_sources({}) == tuple(s for s in SOURCES if s.tier == "core")


def test_load_noise_title_from_config():
    cfg = {"noiseTitle": ["推广", "广告"]}
    assert load_noise_title(cfg) == ("推广", "广告")
    # 0018：默认值含 scol 视频栏目关键词（候选阶段过滤视频稿）
    # v2：追加「消费券」（大洋网广告兜底，双保险）
    assert load_noise_title({}) == (
        "C视觉", "每日一图", "每日一景", "影像数据库",
        "理响巴蜀", "政策翻译机", "空天侦探社", "食情局", "成工之恋", "川观解盘",
        "消费券",
    )
