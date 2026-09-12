# -*- coding: utf-8 -*-
"""候选 → DailyDigest 组装单测（v2 §6：地方分节删除、保留栏目进 essay、policy 去地方化）。"""
import datetime as dt

from kaogong.build import SLOT_SOURCE, build_digest
from kaogong.models import Candidate


def _c(title, url, slot, date="2026-08-12", summary=""):
    return Candidate(title=title, url=url, date=dt.date.fromisoformat(date), slot=slot, summary=summary)


def test_build_groups_sections_in_order():
    cands = [
        _c("时政A", "u1", "pol"),
        _c("时评C", "u3", "shi"),
        _c("大洋网观察D", "u4", "essay"),          # 大洋网/川观理论栏目 → 申论精读
        _c("政策E", "u5", "gdp", summary="解读摘要"),
    ]
    d = build_digest(cands, dt.date(2026, 8, 12))
    assert [s.id for s in d.sections] == ["national", "essay", "policy"]


def test_build_merges_pol_and_gov_into_national():
    d = build_digest([_c("时政A", "u1", "pol"), _c("政策B", "u2", "gov")], dt.date(2026, 8, 12))
    assert d.sections[0].id == "national"
    assert len(d.sections[0].items) == 2


def test_build_near_dup_deduped():
    cands = [
        _c("人民网：高质量发展是首要任务", "u1", "pol"),
        _c("高质量发展是当前首要任务", "u2", "gov"),
    ]
    d = build_digest(cands, dt.date(2026, 8, 12))
    assert len(d.sections[0].items) == 1


def test_build_title_date_and_weekday():
    d = build_digest([_c("x", "u1", "pol")], dt.date(2026, 8, 12))
    assert d.date == "2026-08-12"
    assert "周三" in d.title
    assert d.sections[0].items[0].date == "08-12"


def test_build_essay_dedups_by_url():
    cands = [_c("时评1", "u", "shi"), _c("时评2", "u", "qst")]
    d = build_digest(cands, dt.date(2026, 8, 12))
    assert len(d.sections[0].items) == 1  # essay 里同一 url 只留一条


def test_build_merges_byt_nf_and_essay_slot_into_essay():
    """申论精读聚合：shi/qst/xh/rm + 今日谈(≤2) + 南方时评 + 大洋网/川观理论栏目(slot=essay)。"""
    cands = [
        _c("时评C", "u3", "shi"),
        _c("今日谈1", "u6", "byt"),
        _c("今日谈2", "u7", "byt"),
        _c("今日谈3", "u8", "byt"),  # 最多 2 条
        _c("南方时评1", "u9", "nf"),
        _c("黄坤明调研", "u10", "essay"),        # 大洋网
        _c("AI治理丨新思想自习室", "u11", "essay"),  # 川观理论栏目
    ]
    d = build_digest(cands, dt.date(2026, 8, 12))
    ids = [s.id for s in d.sections]
    assert "essay" in ids
    assert "today-talk" not in ids
    assert "south-review" not in ids
    essay = next(s for s in d.sections if s.id == "essay")
    titles = [it.title for it in essay.items]
    assert "今日谈1" in titles and "今日谈2" in titles
    assert "今日谈3" not in titles  # 今日谈最多 2 条
    assert "南方时评1" in titles
    assert "黄坤明调研" in titles and "AI治理丨新思想自习室" in titles  # v2 拍板⑧


def test_build_policy_section_renamed():
    """v2 §6：guangdong-policy → policy（去地方化）。"""
    d = build_digest([_c("解读A", "u1", "gdp")], dt.date(2026, 8, 12))
    assert d.sections[0].id == "policy"
    assert d.sections[0].title == "政策解读"


def test_build_local_slots_have_no_sections():
    """地方分节已删除：gd/sc/js 槽位候选不再产出分节（历史配置兜底，静默忽略）。"""
    cands = [
        _c("旧广东", "u1", "gd"),
        _c("旧四川", "u2", "sc"),
        _c("旧江苏", "u3", "js"),
    ]
    d = build_digest(cands, dt.date(2026, 8, 12))
    assert d.sections == []


def test_build_cluster_dedupe_at_entry():
    """v2 §4 簇去重入口：遂宁式拆条簇在组装前聚合为 1，理论栏目不受影响。"""
    cands = [
        _c("以“五个发力”，实现“工业倍增”丨起步奋进“十五五”遂宁专场新闻发布会",
           "https://sichuan.scol.com.cn/ggxw/202609/83320358.html", "essay", date="2026-09-11"),
        _c("构建遂宁128实验室体系丨起步奋进“十五五”遂宁专场新闻发布会",
           "https://sichuan.scol.com.cn/ggxw/202609/83320361.html", "essay", date="2026-09-11"),
        _c("追星自由不能逾越社会救助的制度边界丨天府新视界",
           "https://sichuan.scol.com.cn/ggxw/202609/83320107.html", "essay", date="2026-09-11"),
    ]
    d = build_digest(cands, dt.date(2026, 9, 11))
    essay = next(s for s in d.sections if s.id == "essay")
    assert [it.title for it in essay.items] == [
        "以“五个发力”，实现“工业倍增”丨起步奋进“十五五”遂宁专场新闻发布会",
        "追星自由不能逾越社会救助的制度边界丨天府新视界",
    ]


def test_build_empty_candidates():
    d = build_digest([], dt.date(2026, 8, 12))
    assert d.sections == []


def test_build_roundtrip_to_json():
    d = build_digest([_c("时政A", "u1", "pol", summary="摘要")], dt.date(2026, 8, 12))
    data = d.to_json()
    item = data["sections"][0]["items"][0]
    assert item["sourceUrl"] == "u1"
    assert item["summary"] == "摘要"


def test_slot_source_covers_active_slots_only():
    """槽位表清理：gd/sc/js 已删；essay 承接大洋网/川观理论栏目。"""
    assert not {"gd", "sc", "js"} & set(SLOT_SOURCE)
    assert SLOT_SOURCE["essay"] == "大洋网/川观理论栏目"
