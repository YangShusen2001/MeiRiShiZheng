# -*- coding: utf-8 -*-
"""黄金样本回放（precision-pivot v2.1 附录 B 验收基准）。

对 40 条人工标注（8 in / 32 out，全部带用户原话理由）回放纯规则闸门：
- 栏目闸门（tier 由 load_sources 承担，此处回放 column_keep_re/column_drop_re + noiseTitle）；
- 簇去重（cluster_dedupe）；
- MAX_PRECLIP 安全阀（v2.1：fetch 层唯一的总量控制）；
- T04 全链路：密度门禁（真实剪藏正文，零网络）→ 配额/CAPS（total_chars 降序）。

T01-T04 验收：
1. 8 篇 IN 全部通过「栏目 + 簇」闸门（尤其四川在线两篇理论栏目、大洋网两篇）；
2. 四川在线 ggxw 快讯 18 条 OUT 全灭（遂宁×7 / 强相关×10 / 天天学习×1）；
3. 文旅消费券被 column_drop_re 杀；
4. 簇去重把遂宁 7 条拆条聚合为 1，且不误杀 8 篇 IN；
5. 当日真实数据过 fetch 层闸门后 8/8 IN 存活（含被 v2 配额误杀的政绩观/塞上江南/琴澳）；
6. T04：8/8 IN 在「栏目 → 簇 → 密度 → 配额/CAPS」全链路存活，当日 40 → ≤15（纯规则链）。

**Fixture 纪律（2026-09-15 修复）**：尺子的三份输入全部入库冻结，测试完全自洽（hermetic），
不依赖任何本地/网络资产；原先两个 T04 验收类上的 skipif 已移除，尺子在任何一次 clone 上
都真正执行（文件内剩余两处 skipif 只守已入库的 GOLD，实际不会触发）。

| 输入 | 文件 | 原状态 |
|---|---|---|
| 40 条人工标注 | `_review/gold-2026-09-11.json` | 入库（不变） |
| 40 条候选样本 | `_review/sample-40.json` | 入库（不变） |
| 40 条剪藏正文 | `_review/gold-day-clips.json` | **本次冻结入库** |

修复前的缺陷（两处，同源）：测试读 `content/2026-09-11/digest.json` 与 `article-*.json`，
而 `content/20*/` 被 `.gitignore:59` 忽略。后果有二——① **静默跳过**：任何一次干净 clone
上 `content/2026-09-11/` 不存在，本文件两个 T04 验收类直接 skip，尺子从未被真正执行；
② **可被覆写**：该 digest 于 09-12 16:55 被后续 pipeline 重跑覆写（40 → 31 条，national
10 → 1），而硬断言 `len(items) == 40` 写在被测代码执行**之前**，于是红灯与任何闸门回归无关，
纯属 fixture 漂移。冻结后尺子与代码同生命周期，红灯只会由代码回归引起。
"""
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from kaogong.dedupe import cluster_dedupe
from kaogong.models import Candidate
from kaogong.pipeline import MAX_PRECLIP
from kaogong.sources import DEFAULT_SOURCES, _column_ok, is_noise_title

_REPO = Path(__file__).resolve().parents[2]
GOLD = _REPO / "_review" / "gold-2026-09-11.json"
SAMPLE = _REPO / "_review" / "sample-40.json"
CLIPS = _REPO / "_review" / "gold-day-clips.json"

# sample-40.json 存的是中文栏目名（旧管道产物），而 CAPS 槽位由分节 id 决定
# （_slot_of）：guangdong/sichuan 必须原样保留 id 才能命中 _LEGACY_ESSAY_SECTIONS
# → essay 槽位（v2.1 拍板⑧：地方栏目统一进申论精读）。SECTION_SLUG 已清理这两个
# 死映射，故此处显式补齐，不得依赖 slug 回退（回退会得到 pol 槽位，CAPS 行为改变）。
_SECTION_NAME_TO_ID = {
    "全国时政要闻": "national",
    "申论精读": "essay",
    "广东要闻动态": "guangdong",
    "四川要闻动态": "sichuan",
}

_BY_NAME = {s.name: s for s in DEFAULT_SOURCES}
# 标注 host（及 www 变体）→ Source 配置；无配置的 host 只过 noiseTitle
_HOST_TO_SOURCE = {
    "sichuan.scol.com.cn": _BY_NAME["四川全媒快讯"],
    "news.dayoo.com": _BY_NAME["大洋网广东"],
    "politics.people.com.cn": _BY_NAME["人民网时政"],
    "news.cn": _BY_NAME["新华网时政"],
    "www.news.cn": _BY_NAME["新华网时政"],
    "qstheory.cn": _BY_NAME["求是网"],
    "www.qstheory.cn": _BY_NAME["求是网"],
    "banyuetan.org": _BY_NAME["半月谈今日谈"],
    "www.banyuetan.org": _BY_NAME["半月谈今日谈"],
    "opinion.southcn.com": _BY_NAME["南方时评"],
}


def _labels() -> list[dict]:
    return json.loads(GOLD.read_text(encoding="utf-8"))["labels"]


def _sample_items() -> list[dict]:
    """黄金日 40 条候选（冻结入库副本），归一到回放所需的最小形状。

    返回项含 title/url/section(id)，与旧 digest.json 的分节条目等价；
    section 由中文栏目名经 _SECTION_NAME_TO_ID 还原为旧分节 id。
    """
    out = []
    for it in json.loads(SAMPLE.read_text(encoding="utf-8")):
        section = _SECTION_NAME_TO_ID.get(it["section"])
        assert section, f"sample-40 出现未登记栏目名：{it['section']!r}"
        out.append({"title": it["title"], "url": it["url"], "section": section})
    return out


_CLIPS_CACHE: dict[str, list[str]] | None = None


def _clips() -> dict[str, list[str]]:
    """url → 剪藏正文段（冻结入库副本），模块级缓存避免逐条重读 126 KB。"""
    global _CLIPS_CACHE
    if _CLIPS_CACHE is None:
        _CLIPS_CACHE = json.loads(CLIPS.read_text(encoding="utf-8"))["clips"]
    return _CLIPS_CACHE


def _paragraphs_for(url: str) -> list[str] | None:
    """按 url 读黄金日剪藏正文（冻结副本，零网络）；未冻结的条目返回 None。

    4 条非 IN 条目当日即无剪藏，故 None 是正常取值——调用方按「保守放行」处理
    （paragraphs 为空 → total_chars=0，配额降序下最先让位），与冻结前行为一致。
    """
    paras = _clips().get(url)
    return list(paras) if paras else None


def _source_for(url_or_host: str) -> object | None:
    host = urlparse(url_or_host).hostname or url_or_host if "//" in url_or_host else url_or_host
    return _HOST_TO_SOURCE.get(host or "")


def _column_gate(title: str, url_or_host: str) -> bool:
    """栏目闸门（column_keep_re/column_drop_re + noiseTitle）。True = 存活。"""
    src = _source_for(url_or_host)
    if src is not None and not _column_ok(src, title):
        return False
    return not is_noise_title(title)


@pytest.mark.skipif(not GOLD.exists(), reason="黄金样本 _review/gold-2026-09-11.json 不在库内")
class TestGoldColumnGate:
    """验收 1/2/3：IN 全存活、ggxw 快讯全灭、消费券被黑名单杀。"""

    def test_all_in_articles_survive(self):
        for lab in _labels():
            if lab["verdict"] == "in":
                assert _column_gate(lab["title"], lab["url"]), lab["title"]

    def test_scol_ggxw_flash_killed_by_whitelist(self):
        """四川在线 18 条 OUT 全灭：遂宁×7 / 强相关×10 / 天天学习×1（拍板⑥）。"""
        scol_out = [
            l for l in _labels()
            if l["host"] == "sichuan.scol.com.cn" and l["verdict"] == "out"
        ]
        assert len(scol_out) == 18
        for lab in scol_out:
            assert not _column_gate(lab["title"], lab["url"]), lab["title"]

    def test_dayoo_coupon_killed_and_in_survive(self):
        """文旅消费券（83532f1e7b）被 column_drop_re 杀；黄坤明/琴澳两篇 IN 存活。"""
        coupon = next(l for l in _labels() if "文旅消费券" in l["title"])
        assert not _column_gate(coupon["title"], coupon["url"])
        for key in ("黄坤明到广州调研", "琴澳五载同心同行"):
            lab = next(l for l in _labels() if key in l["title"])
            assert _column_gate(lab["title"], lab["url"]), lab["title"]


@pytest.mark.skipif(not GOLD.exists(), reason="黄金样本 _review/gold-2026-09-11.json 不在库内")
class TestGoldClusterDedupe:
    """验收 4：遂宁 7 条拆条聚合 1，8 篇 IN 不被误杀。"""

    def test_suining_collapses_and_in_survive(self):
        labels = _labels()
        cands = [
            Candidate(title=l["title"], url=l["url"], date=dt.date(2026, 9, 11), slot="x")
            for l in labels
        ]
        out = cluster_dedupe(cands)
        kept = {c.title for c in out}
        for lab in labels:
            if lab["verdict"] == "in":
                assert lab["title"] in kept, lab["title"]
        suining_kept = [t for t in kept if "遂宁专场" in t]
        assert len(suining_kept) == 1  # 7 条拆条 → 1 条
        assert len(out) == 34          # 40 - 遂宁 6 条，无其他误合并


class TestGoldFixtureIntegrity:
    """尺子自身的完整性：三份冻结输入必须描述同一组 40 篇，且无脏键。

    这是防 fixture 再次漂移的第一道闸——任何一份被单独重生成（只换 sample-40、
    只补剪藏、或标注与样本对不上），本类立即报错，而不是让下游验收给出
    似是而非的绿灯。2026-09-15 的红灯正是「输入之间失去同步」这一类。
    """

    def test_sample_and_labels_describe_same_articles(self):
        assert {it["url"] for it in _sample_items()} == {lab["url"] for lab in _labels()}

    def test_clips_keys_belong_to_the_gold_day(self):
        assert set(_clips()) <= {lab["url"] for lab in _labels()}

    def test_clips_cover_every_in_article(self):
        in_urls = {lab["url"] for lab in _labels() if lab["verdict"] == "in"}
        assert in_urls <= set(_clips()), "密度回放依赖 8 篇 IN 的剪藏正文"


class TestTodayDigestReplay:
    """验收 5（v2.1 口径）：当日 40 条过 fetch 层闸门（栏目 → 簇 → MAX_PRECLIP），
    8/8 IN 存活——含被 v2 fetch 层配额误杀的政绩观（news.cn 第 5）/塞上江南
    （news.cn 第 6）/琴澳（dayoo 第 4）。

    回放口径：digest 条目不带源名，按 URL host 归源（news.cn 全部归新华网时政，
    为保守近似）。「≤15 条」最终规模验收移至 T04（密度门禁 + 后移配额/CAPS，
    按 total_chars 降序，见方案 §3.3/§3.4）。
    """

    def test_fetch_layer_keeps_all_in_articles_alive(self):
        items = _sample_items()
        assert len(items) == 40

        cands = []
        for it in items:
            src = _source_for(it["url"])
            cands.append(Candidate(
                title=it["title"], url=it["url"], date=dt.date(2026, 9, 11),
                slot=src.slot if src is not None else "pol",
                source_name=src.name if src is not None else "",
            ))

        # 1) 栏目 + 噪声（tier 在 load_sources 阶段，回放数据里无 background 源条目）
        alive = [c for c in cands if _column_gate(c.title, c.url)]
        assert len(alive) == 21  # 40 - 18 scol ggxw - 1 消费券
        # 2) 簇去重（遂宁式拆条已在栏目层全灭，此层无进一步削减）
        alive = cluster_dedupe(alive)
        assert len(alive) == 21
        # 3) MAX_PRECLIP 安全阀（正常日 ~22 << 48，不触发）
        alive = alive[:MAX_PRECLIP]
        assert len(alive) == 21

        titles = [c.title for c in alive]
        # 8/8 IN 全存活——尤其 v2 fetch 层配额误杀的 3 篇（列表序先到先得
        # 与价值无关：政绩观/塞上江南走 news.cn 配额、琴澳走 dayoo 配额）
        for lab in _labels():
            if lab["verdict"] == "in":
                assert lab["title"] in titles, lab["title"]
        # 关键击杀仍成立：遂宁拆条、消费券广告；scol 出口仅剩两篇理论栏目 IN
        assert not any("遂宁专场" in t for t in titles)
        assert not any("消费券" in t for t in titles)
        scol_titles = [c.title for c in alive if "sichuan.scol.com.cn" in c.url]
        assert len(scol_titles) == 2  # 拍板⑥：ggxw 快讯全灭，白名单 2 栏目存活
        assert all(("新思想自习室" in t) or ("天府新视界" in t) for t in scol_titles)


class TestTodayFullChainReplay:
    """验收 6（T04 附录 B 全链路硬断言）：栏目 → 簇 → 密度门禁 → 配额/CAPS。

    - 8/8 IN 在全链路存活（含配额阶段——total_chars 降序下深度长文胜出，
      v2 fetch 层列表序配额误杀 3 篇 IN 的缺陷由后移配额修正）；
    - 当日 40 → ≤15（纯规则链，零 AI）；
    - 密度门禁用冻结剪藏正文回放（零网络）；未冻结的 4 条保守放行进配额阶段。
    """

    def test_full_chain_keeps_all_in_alive_and_within_15(self):
        from kaogong.density import density_gate
        from kaogong.pipeline import _apply_quota_and_caps

        items = _sample_items()
        assert len(items) == 40
        section_by_url = {it["url"]: it["section"] for it in items}

        # 1) 栏目 + 噪声（与 TestTodayDigestReplay 同口径）
        alive = [it for it in items if _column_gate(it["title"], it["url"])]
        assert len(alive) == 21  # 40 - 18 scol ggxw - 1 消费券

        # 2) 密度门禁：冻结剪藏正文；未冻结条目保守放行（paragraphs 空 → total_chars=0）
        passed: list[dict] = []
        density_killed: list[tuple[str, str]] = []
        for it in alive:
            paras = _paragraphs_for(it["url"])
            if paras is None:
                passed.append({"url": it["url"], "title": it["title"], "paragraphs": []})
                continue
            reason = density_gate(paras)
            if reason is None:
                passed.append({"url": it["url"], "title": it["title"], "paragraphs": paras})
            else:
                density_killed.append((it["title"], reason))

        # 8/8 IN 必须有真实剪藏正文，且全部通过密度门禁（硬断言，无保守豁免）
        for lab in _labels():
            if lab["verdict"] == "in":
                paras = _paragraphs_for(lab["url"])
                assert paras, f"IN 缺剪藏正文：{lab['title']}"
                assert density_gate(paras) is None, f"IN 被密度门禁误杀：{lab['title']}"
        assert density_killed, "密度门禁在黄金日应至少拦截一条载体缺陷稿"

        # 3) 配额/CAPS（total_chars 降序，host 分组）
        final, cut = _apply_quota_and_caps(passed, section_by_url)
        titles = [c["title"] for c in final]

        # 验收：8/8 IN 全链路存活（含配额）
        for lab in _labels():
            if lab["verdict"] == "in":
                assert lab["title"] in titles, lab["title"]
        # 验收：当日 40 → ≤15（纯规则链，宁缺勿滥的目标规模）
        assert len(final) <= 15, f"全链路出口 {len(final)} 条超规模：{titles}"
        # 关键击杀保持：遂宁拆条 / 消费券不在任何阶段复活
        assert not any("遂宁专场" in t for t in titles)
        assert not any("消费券" in t for t in titles)
