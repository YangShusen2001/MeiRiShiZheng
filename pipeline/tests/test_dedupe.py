# -*- coding: utf-8 -*-
"""去重层单测（v2 新增：cluster_dedupe 簇去重）。"""
import datetime as dt

from kaogong.dedupe import (
    _article_serial,
    _host_of,
    _lcs_len,
    cluster_dedupe,
    dedupe_items,
    is_same_event,
    normalize_title,
)
from kaogong.http import IndexedLink
from kaogong.models import Candidate


def test_normalize_title_strips_source_prefix():
    assert normalize_title("人民网：习近平致慰问电") == "习近平致慰问电"


def test_normalize_title_fullwidth_to_halfwidth():
    # 全角数字与冒号转半角；中文不受影响
    assert normalize_title("２０２６年：报告") == "2026年报告"


def test_normalize_title_removes_punct_and_space():
    assert normalize_title("【时政】高质量发展：新征程") == "时政高质量发展新征程"


def test_is_same_event_true_on_shared_substring():
    assert is_same_event("高质量发展是首要任务", "高质量发展是当前首要任务") is True


def test_is_same_event_false_on_unrelated():
    assert is_same_event("高质量发展是首要任务", "乡村振兴战略全面推进") is False


def test_dedupe_removes_same_url_and_near_dup_title():
    items = [
        IndexedLink(dt.date(2026, 8, 12), "人民网：高质量发展是首要任务", "u1"),
        IndexedLink(dt.date(2026, 8, 12), "高质量发展是当前首要任务", "u2"),
        IndexedLink(dt.date(2026, 8, 12), "乡村振兴战略全面推进", "u3"),
    ]
    out = dedupe_items(items)
    assert [x.url for x in out] == ["u1", "u3"]


def test_dedupe_keeps_first_on_dup_url():
    items = [
        IndexedLink(dt.date(2026, 8, 12), "短标题", "same"),
        IndexedLink(dt.date(2026, 8, 12), "更长的标题", "same"),
    ]
    out = dedupe_items(items)
    assert len(out) == 1
    assert out[0].title == "短标题"


# —— v2 §4 cluster_dedupe：同源同日拆条簇聚合 ——


def _cand(title: str, url: str, date: str = "2026-09-11") -> Candidate:
    return Candidate(title=title, url=url, date=dt.date.fromisoformat(date), slot="essay")


def test_host_and_serial_helpers():
    assert _host_of("https://sichuan.scol.com.cn/ggxw/202609/83320358.html") == "sichuan.scol.com.cn"
    assert _host_of("not-a-url") == ""
    assert _article_serial("https://x.com/ggxw/202609/83320358.html") == 83320358
    assert _article_serial("https://x.com/n1/2026/0911/c1001-40796429.html") == 40796429
    assert _article_serial("https://x.com/a/11/2.html") is None  # 无 ≥4 位数字
    assert _lcs_len("高质量发展新赛道", "高质量推进发展") == 3
    assert _lcs_len("", "abc") == 0


def test_cluster_dedupe_collapses_suining_series():
    """黄金样本：遂宁专场发布会 7 条拆条（83320357-83320365）聚合为 1，保留首条。"""
    titles = [
        ("以“五个发力”，实现“工业倍增”丨起步奋进“十五五”遂宁专场新闻发布会", 83320358),
        ("构建遂宁128实验室体系，打造技术创新“训练场”、硬核企业“健身房”丨起步奋进“十五五”遂宁专场新闻发布会", 83320361),
        ("在遂宁，每一名劳动者都会被看见、被尊重、受保障｜起步奋进“十五五”遂宁专场新闻发布会", 83320364),
        ("爱上一座城：赛事“燃”、演艺“火”、夜色“亮”|起步奋进“十五五”遂宁专场新闻发布会", 83320365),
        ("枢纽遂宁，如何织密立体交通网？丨起步奋进“十五五”遂宁专场新闻发布会", 83320357),
        ("涪江复航，建设成都平原经济区东向“第一港”丨起步奋进“十五五”遂宁专场新闻发布会", 83320360),
        ("打造“西部期货交割高地”，遂宁还要留下更多丨起步奋进“十五五”遂宁专场新闻发布会", 83320359),
    ]
    cands = [_cand(t, f"https://sichuan.scol.com.cn/ggxw/202609/{n}.html") for t, n in titles]
    out = cluster_dedupe(cands)
    assert len(out) == 1
    assert out[0].title == titles[0][0]  # 保留列表首条


def test_cluster_dedupe_keeps_unrelated_same_host():
    """同源同日但内容无关（两个理论栏目 IN）不合并。"""
    a = _cand("构建公正合理的全球人工智能治理体系丨新思想自习室",
              "https://sichuan.scol.com.cn/ggxw/202609/83320187.html")
    b = _cand("追星自由不能逾越社会救助的制度边界丨天府新视界",
              "https://sichuan.scol.com.cn/ggxw/202609/83320107.html")
    assert len(cluster_dedupe([a, b])) == 2


def test_cluster_dedupe_requires_same_host():
    """跨源不合并：同标题同日不同 host 各自保留。"""
    a = _cand("高质量发展是首要任务", "https://a.com/20260911/10001.html")
    b = _cand("高质量发展是首要任务", "https://b.com/20260911/10002.html")
    assert len(cluster_dedupe([a, b])) == 2


def test_cluster_dedupe_requires_same_date():
    """跨日不合并：同源同标题不同日期各自保留。"""
    a = _cand("高质量发展是首要任务", "https://a.com/20260911/10001.html", date="2026-09-11")
    b = _cand("高质量发展是首要任务", "https://a.com/20260912/10001.html", date="2026-09-12")
    assert len(cluster_dedupe([a, b])) == 2


def test_cluster_dedupe_serial_adjacent_signal():
    """信号②：标题共享长子串且 URL 序号相邻（差≤2）→ 同簇聚合。"""
    a = _cand("遂宁文旅消费季启幕畅游涪江", "https://x.com/ggxw/202609/83320401.html")
    b = _cand("遂宁文旅消费季升级夜游经济", "https://x.com/ggxw/202609/83320402.html")
    out = cluster_dedupe([a, b])
    assert len(out) == 1
    assert out[0].title == "遂宁文旅消费季启幕畅游涪江"


def test_cluster_dedupe_chain_merges_via_union_find():
    """链式相邻（A↔B 相邻、B↔C 相邻）聚成一簇，即使 A↔C 序号差超限。"""
    base = "聚焦低空经济发展"
    a = _cand(f"{base}新观察", "https://x.com/ggxw/202609/83320401.html")
    b = _cand(f"{base}再提速", "https://x.com/ggxw/202609/83320402.html")
    c = _cand(f"{base}看未来", "https://x.com/ggxw/202609/83320403.html")
    assert len(cluster_dedupe([a, b, c])) == 1


def test_cluster_dedupe_empty_and_single():
    assert cluster_dedupe([]) == []
    solo = _cand("唯一文章", "https://x.com/a.html")
    assert cluster_dedupe([solo]) == [solo]


def test_cluster_dedupe_no_false_merge_on_year_string():
    """回归（黄金样本实证）：同源同日、标题仅共享「2026年」（5 字）不合并。

    is_same_event 的实际阈值是 5 字连续子串，直接复用会把这类对误聚合；
    cluster_dedupe 按方案阈值（≥8 字 / ≥6 字∧序号差≤2）判定。
    """
    a = _cand("2026年中国农民丰收节 四川180余场活动庆丰收",
              "https://sichuan.scol.com.cn/ggxw/202609/83320378.html")
    b = _cand("每人资助40万元！四川2026年博士后创新人才支持项目申报开始",
              "https://sichuan.scol.com.cn/ggxw/202609/83320319.html")
    assert len(cluster_dedupe([a, b])) == 2
