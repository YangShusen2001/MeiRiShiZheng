# -*- coding: utf-8 -*-
"""档案策展脚本的「关键数字」收敛逻辑（画布 3:382）。

脚本在 scripts/ 下、不是可 import 的包，所以按路径加载。
只测 `_figures` —— 它是这一步里唯一有判断的纯函数（其余是 IO 与提示词）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "curate-archive.py"


def _load():
    spec = importlib.util.spec_from_file_location("curate_archive", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load()


def test_figures_keeps_canvas_sample_verbatim(mod):
    """画布 3:382 的原样：两件指标名，中点分隔。收敛不能改动合法输入。"""
    assert mod._figures("天然气产量目标 · 储气能力占消费量比重") == "天然气产量目标 · 储气能力占消费量比重"


def test_figures_keeps_value_bearing_sample(mod):
    """画布 3:393 的原样：指标名带目标值。"""
    assert mod._figures("参保率 95% 以上 · 人均预期寿命 80 岁") == "参保率 95% 以上 · 人均预期寿命 80 岁"


def test_figures_empty_input_returns_empty(mod):
    """空串是合法值（「这份文件没有可量化的指标」），不能被当成缺失去编造。"""
    assert mod._figures(None) == ""
    assert mod._figures("") == ""
    assert mod._figures("   ") == ""
    assert mod._figures(" · ") == ""


def test_figures_normalizes_semicolon_variants(mod):
    """分号 / 竖线是中点以外的项间分隔写法，统一成画布的中点。"""
    want = "参保率 95% 以上 · 人均预期寿命 80 岁"
    for raw in (
        "参保率 95% 以上;人均预期寿命 80 岁",
        "参保率 95% 以上；人均预期寿命 80 岁",
        "参保率 95% 以上|人均预期寿命 80 岁",
    ):
        assert mod._figures(raw) == want


def test_figures_keeps_enumeration_commas_inside_short_item(mod):
    """短件里的顿号是内容的一部分（枚举），不能被切成碎片。

    实测踩坑：「评价结果分 A、B、C」曾被切成三项「评价结果分 A」「B」「C」，
    「专业养殖、经济林 40%至50%」被切出没有信息量的「专业养殖」。
    """
    assert mod._figures("评价结果分 A、B、C") == "评价结果分 A、B、C"
    assert mod._figures("专业养殖、经济林 40%至50%") == "专业养殖、经济林 40%至50%"


def test_figures_splits_overlong_chunk_on_commas(mod):
    """只有单件超长时才按顿号再切一刀 —— AI 会把好几项用顿号连成一句。"""
    joined = "参保率 95% 以上、人均预期寿命 80 岁、每千人床位 8 张"
    assert len(joined) > mod.FIGURES_MAX_ITEM_LENGTH  # 前提：确实超长，否则走的不是这条路径
    assert mod._figures(joined) == "参保率 95% 以上 · 人均预期寿命 80 岁 · 每千人床位 8 张"


def test_figures_caps_item_count(mod):
    """件数超限只留前三 —— 画布那一行是 12px 单行，放不下更多。"""
    assert mod._figures("甲指标 · 乙指标 · 丙指标 · 丁指标") == "甲指标 · 乙指标 · 丙指标"
    assert mod._figures("甲指标 · 乙指标 · 丙指标 · 丁指标").count(" · ") == mod.FIGURES_MAX_ITEMS - 1


def test_figures_drops_overlong_item_instead_of_truncating(mod):
    """单件写成整句时整件丢弃 —— 截断会留下半个指标名，比不显示更糟。"""
    long_item = "长" * (mod.FIGURES_MAX_ITEM_LENGTH + 1)
    assert mod._figures(f"正常指标、{long_item}") == "正常指标"
    assert mod._figures(long_item) == ""


def test_figures_respects_total_length(mod):
    """三件各自合法但整行超长时，丢掉放不下的那件，不截半。"""
    unit = "一" * mod.FIGURES_MAX_ITEM_LENGTH
    out = mod._figures("、".join([unit, "二" * mod.FIGURES_MAX_ITEM_LENGTH, "三" * mod.FIGURES_MAX_ITEM_LENGTH]))
    assert len(out) <= mod.FIGURES_MAX_LENGTH
    assert out == " · ".join([unit, "二" * mod.FIGURES_MAX_ITEM_LENGTH])


def test_figures_bounds_are_ordered(mod):
    """上限之间要自洽：单件 ≤ 整行，否则任何输入都过不了。"""
    assert mod.FIGURES_MAX_ITEM_LENGTH <= mod.FIGURES_MAX_LENGTH
    assert mod.FIGURES_MAX_ITEMS >= 1
