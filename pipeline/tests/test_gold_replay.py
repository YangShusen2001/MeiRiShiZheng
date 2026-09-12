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

黄金样本/当日数据未入库时自动跳过（_review/ 与 content/20*/ 均为本地资产，后者被 gitignore）。
"""
import datetime as dt
import hashlib
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
DAY_DIR = _REPO / "content" / "2026-09-11"
DIGEST = DAY_DIR / "digest.json"

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


def _paragraphs_for(url: str) -> list[str] | None:
    """按 sourceUrl 读当日真实剪藏正文（零网络）；文件缺失返回 None。"""
    aid = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    path = DAY_DIR / f"article-{aid}.json"
    if not path.exists():
        return None
    try:
        return list(json.loads(path.read_text(encoding="utf-8")).get("paragraphs") or [])
    except (ValueError, OSError):
        return None


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


@pytest.mark.skipif(not DIGEST.exists(), reason="当日数据 content/2026-09-11 被 gitignore（本地资产）")
class TestTodayDigestReplay:
    """验收 5（v2.1 口径）：当日 40 条过 fetch 层闸门（栏目 → 簇 → MAX_PRECLIP），
    8/8 IN 存活——含被 v2 fetch 层配额误杀的政绩观（news.cn 第 5）/塞上江南
    （news.cn 第 6）/琴澳（dayoo 第 4）。

    回放口径：digest 条目不带源名，按 URL host 归源（news.cn 全部归新华网时政，
    为保守近似）。「≤15 条」最终规模验收移至 T04（密度门禁 + 后移配额/CAPS，
    按 total_chars 降序，见方案 §3.3/§3.4）。
    """

    def test_fetch_layer_keeps_all_in_articles_alive(self):
        data = json.loads(DIGEST.read_text(encoding="utf-8"))
        items = [it for sec in data["sections"] for it in sec["items"]]
        assert len(items) == 40

        cands = []
        for it in items:
            src = _source_for(it["sourceUrl"])
            cands.append(Candidate(
                title=it["title"], url=it["sourceUrl"], date=dt.date(2026, 9, 11),
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


@pytest.mark.skipif(not DIGEST.exists(), reason="当日数据 content/2026-09-11 被 gitignore（本地资产）")
class TestTodayFullChainReplay:
    """验收 6（T04 附录 B 全链路硬断言）：栏目 → 簇 → 密度门禁 → 配额/CAPS。

    - 8/8 IN 在全链路存活（含配额阶段——total_chars 降序下深度长文胜出，
      v2 fetch 层列表序配额误杀 3 篇 IN 的缺陷由后移配额修正）；
    - 当日 40 → ≤15（纯规则链，零 AI）；
    - 密度门禁用当日真实剪藏正文回放（零网络；缺文件的条目保守放行进配额阶段）。
    """

    def test_full_chain_keeps_all_in_alive_and_within_15(self):
        from kaogong.density import density_gate
        from kaogong.pipeline import _apply_quota_and_caps

        data = json.loads(DIGEST.read_text(encoding="utf-8"))
        items = [it for sec in data["sections"] for it in sec["items"]]
        assert len(items) == 40
        section_by_url = {
            it["sourceUrl"]: sec["id"] for sec in data["sections"] for it in sec["items"]
        }

        # 1) 栏目 + 噪声（与 TestTodayDigestReplay 同口径）
        alive = [it for it in items if _column_gate(it["title"], it["sourceUrl"])]
        assert len(alive) == 21  # 40 - 18 scol ggxw - 1 消费券

        # 2) 密度门禁：真实剪藏正文；缺文件的条目保守放行（total_chars=0，配额下最先让位）
        passed: list[dict] = []
        density_killed: list[tuple[str, str]] = []
        for it in alive:
            paras = _paragraphs_for(it["sourceUrl"])
            if paras is None:
                passed.append({"url": it["sourceUrl"], "title": it["title"], "paragraphs": []})
                continue
            reason = density_gate(paras)
            if reason is None:
                passed.append({"url": it["sourceUrl"], "title": it["title"], "paragraphs": paras})
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
