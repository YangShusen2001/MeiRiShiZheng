# -*- coding: utf-8 -*-
"""密度门禁四判据（v2.1 §5，T04）：黄金样本校准值 + 保护用例。

判据按「信息充分度」依次检查：empty → G1 浅讯 → G2 纯数据 → G3 图注 → G4 拼盘。
因此非 G1 用例的总字数必须 ≥400，否则会先被 G1 截住、够不到目标判据。

校准依据（40 条人工标注 `_review/gold-2026-09-11.json`，阈值取值见 density.py 头注）：
- G1 浅讯稿：金砖短讯 ~130 字 OUT；AI 治理（IN）~800 字必须存活 → 阈值 400，红线 ≤600。
- G2 纯数据稿：大湾区进出口 OUT；学医（IN）数字也多、靠「分析词=0」合取保护。
- G3 图注/诗行稿：短段（<35 字）占绝对多数。
- G4 零分析拼盘稿：产业蝶变 OUT；救治善后（IN，多省做法）靠「推动」命中分析词保护。
"""
import pytest

from kaogong.density import (
    DENSITY_MIN_CHARS,
    ANALYSIS_WORDS,
    density_gate,
    total_chars,
)


def test_total_chars_joins_paragraphs():
    assert total_chars(["你好", "世界"]) == 4
    assert total_chars([]) == 0


def test_empty_body_rejected():
    assert density_gate([]) == "empty"
    assert density_gate([""]) == "empty"


def test_g1_shallow_notice_boundary():
    """G1：<400 杀（金砖短讯 130），≥400 放行（AI 治理 800）。红线 ≤600。"""
    assert DENSITY_MIN_CHARS <= 600  # 校准红线：AI 治理 800 字 IN 不得被 G1 误杀
    assert density_gate(["短" * 130]) == "shallow_notice"
    assert density_gate(["短" * 399]) == "shallow_notice"
    assert density_gate(["字" * 400]) is None  # 阈值边界：400 字放行
    assert density_gate(["字" * 800]) is None


def test_g2_pure_data_requires_both_conditions():
    """G2 合取：数字占比 ≥0.12 且零分析词才杀；学医类数字多的分析文靠分析词保护。"""
    pure = "2024年进出口12345678亿元增长12.3%。" * 25  # ~650 字、数字密集、零分析词
    assert density_gate([pure]) == "pure_data"
    # 同样数字密集，但含「因为/推动」分析词 → 放行（学医保护路径）
    with_analysis = "2024年进出口12345678亿元增长12.3%。" * 12 + "因为推动高质量发展。" * 12
    assert density_gate([with_analysis]) is None


def test_g3_caption_style_short_paragraph_dominance():
    """G3：段数 ≥3 且短段（<35 字）占比 ≥0.60 → 图注/诗行稿（溇港诗句类）。

    总字数 ≥400（否则 G1 先杀）；短段 12/15 = 0.8。
    """
    caption = ["春风又绿江南岸，明月何时照我还。"] * 12 + ["长段落" * 34] * 3
    assert density_gate(caption) == "caption_style"
    # 长段为主 → 放行
    prose = ["这是一个足够长的段落，" * 20] * 4
    assert density_gate(prose) is None


def test_g3_needs_at_least_three_paragraphs():
    """G3 防误杀：段数 <3 不判杀（两段长文即使偏短句化也放行）。"""
    assert density_gate(["短" * 400, "短" * 400]) is None


def test_g3_ratio_boundary():
    """短段占比恰为 0.60（3/5）即命中；占比不足放行。"""
    paras = ["短" * 400, "短" * 400, "短句。", "短句。", "短句。"]  # 3/5 短段
    assert density_gate(paras) == "caption_style"
    paras = ["短" * 400, "短" * 400, "短" * 400, "短句。", "短句。"]  # 2/5 短段
    assert density_gate(paras) is None


def test_g4_patchwork_conjunction():
    """G4 三条件合取：零分析词 ∧ 段数 ≥6 ∧ 字数 <1500（产业蝶变：多地掠影）。

    每段 60 字 ×8 段 = 480 字（≥400 绕过 G1；段长 ≥35 绕过 G3）。
    """
    patchwork = ["甲地加快布局新赛道。" * 6 for _ in range(8)]
    assert density_gate(patchwork) == "patchwork"
    # 含分析词 → 放行（救治善后保护：多省做法靠「推动/分析」命中）
    with_analysis = ["甲地推动善后处置并分析原因。" * 5 for _ in range(8)]
    assert density_gate(with_analysis) is None


def test_g4_boundaries_long_or_few_paragraphs_pass():
    """G4 防误杀：字数 ≥1500 或段数 <6 都放行；地名多不单独判杀。

    夹具总字数均 ≥400（否则 G1 先杀，够不到 G4）。
    """
    few = ["甲地加快布局新赛道，系统推进产业升级与配套改革。" * 4 for _ in range(5)]  # 5 段 480 字
    assert density_gate(few) is None  # 段数 5 < 6 → 放行
    long_one = ["乙地加快布局新赛道，全景扫描。"] + ["甲地加快布局新赛道。" * 30 for _ in range(6)]
    # 7 段但总字数 ≥1500 → 放行
    assert total_chars(long_one) >= 1500
    assert density_gate(long_one) is None


def test_analysis_words_table_locked():
    """分析词表锁定（§5.2 脚注）——改表须过黄金回放。"""
    expected = {"因为", "由于", "意味着", "反映", "表明", "分析", "剖析", "原因",
                "得益于", "推动", "支撑", "背后", "折射", "为何", "为什么"}
    for word in expected:
        assert ANALYSIS_WORDS.search(word), word
    assert not ANALYSIS_WORDS.search("增长")     # 数据动词不是分析词
    assert not ANALYSIS_WORDS.search("表示")     # 近词不入表（避免 G2 失守）


def test_gate_reasons_are_stable_vocabulary():
    """拒绝原因词表稳定：clipDetails/report 的 density_low:* 前缀依赖这些值。"""
    assert density_gate([]) == "empty"
    assert density_gate(["短" * 10]) == "shallow_notice"
    assert density_gate(["2024年12.3%" * 40]) == "pure_data"
    caption = ["春风又绿江南岸，明月何时照我还。"] * 12 + ["长段落" * 34] * 3
    assert density_gate(caption) == "caption_style"
    assert density_gate(["甲地加快布局新赛道。" * 7 for _ in range(6)]) == "patchwork"


@pytest.mark.parametrize("body,expected", [
    (["字" * 400], None),
    (["字" * 799], None),
    (["字" * 799] * 2, None),  # 1598 字零分析两段：G4 段数不足，放行
])
def test_calibration_protections(body, expected):
    """黄金样本保护汇总：长文/多字文不得被任何单判据误杀。"""
    assert density_gate(body) == expected
