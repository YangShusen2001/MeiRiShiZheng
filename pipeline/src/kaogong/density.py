# -*- coding: utf-8 -*-
"""内容密度门禁（v2.1 §5）：四条纯规则判据，拦截「剪藏成功、有正文，但是垃圾」的载体缺陷稿。

黄金样本校准（40 条人工标注，`_review/gold-2026-09-11.json`）：
- G1 浅讯稿：金砖短讯 ~130 字 OUT；AI 治理（IN）~800 字 → 阈值 400 必须满足红线「G1 下限 ≤600」。
- G2 纯数据稿：大湾区进出口数字占比 ~0.15 且零分析词 OUT；学医（IN）数字也多，
  靠「分析词 = 0」合取条件保护 → G2 必须双条件合取。
- G3 图注/诗行稿：短段（<35 字）占绝对多数。
- G4 零分析拼盘稿：产业蝶变 12 段/~700 字/零分析词 OUT；救治善后（IN）是用户点名要的
  多省做法文章，靠「推动」命中分析词表保护 → G4 不得用「地名多」单独判杀。

分析词表（§5.2 脚注）：`因为|由于|意味着|反映|表明|分析|剖析|原因|得益于|推动|支撑|背后|折射|为何|为什么`
"""
from __future__ import annotations

import re

DENSITY_MIN_CHARS = 400     # G1：总字数下限（金砖 130 ✂，AI 治理 800 ✅）
DENSITY_DIGIT_RATIO = 0.12  # G2：数字+百分号占比阈值（大湾区 ~0.15 ✂，学医有分析词 ✅）
DENSITY_SHORT_RATIO = 0.60  # G3：短段占比阈值（诗行/图注稿）
DENSITY_SHORT_PARA = 35     # 「短段」定义（字）
DENSITY_PANCHA_CHARS = 1500  # G4：拼盘稿字数上限（产业蝶变 700 ✂，政绩观/学医 4000 ✅）
DENSITY_PANCHA_PARAS = 6    # G4：拼盘稿段数下限

ANALYSIS_WORDS = re.compile(r"因为|由于|意味着|反映|表明|分析|剖析|原因|得益于|推动|支撑|背后|折射|为何|为什么")

# 数字/百分号（含全角百分号），G2 的「纯数据」计量口径
_DIGIT_CHARS = re.compile(r"[0-9.%％]")


def total_chars(paragraphs: list[str]) -> int:
    """正文总字数。

    密度门禁与配额/CAPS（`_apply_quota_and_caps` 的 total_chars 降序截断）共用
    这一个指标——v2.1 §3.2-A2：配额排序键复用密度已算出的字数，零额外启发式。
    """
    return len("".join(paragraphs))


def density_gate(paragraphs: list[str]) -> str | None:
    """返回拒绝原因（'shallow_notice'|'pure_data'|'caption_style'|'patchwork'|'empty'），通过返回 None。

    判据按「信息充分度」依次检查，命中即拒绝；全部未命中 = 放行。
    拒绝原因会以 `density_low:<reason>` 前缀进入 report 的 clipDetails 流。
    """
    text = "".join(paragraphs)
    total = len(text)
    n = len(paragraphs)
    if total == 0:
        return "empty"
    # G1 浅讯稿：领导人短讯/一句话通稿
    if total < DENSITY_MIN_CHARS:
        return "shallow_notice"
    analysis_hits = len(ANALYSIS_WORDS.findall(text))
    # G2 纯数据稿：数字密集且零分析词（合取条件——学医类数字多的分析文靠分析词保护）
    digit_ratio = len(_DIGIT_CHARS.findall(text)) / total
    if digit_ratio >= DENSITY_DIGIT_RATIO and analysis_hits == 0:
        return "pure_data"
    # G3 图注/诗行稿：短段占绝对多数（溇港诗句、真·图注）
    short = sum(1 for p in paragraphs if len(p) < DENSITY_SHORT_PARA)
    if n >= 3 and short / n >= DENSITY_SHORT_RATIO:
        return "caption_style"
    # G4 零分析拼盘稿：段多、字少、无分析词（产业蝶变：多地掠影）
    # 三条件合取是保守设计：宁可漏杀（AI 层再判）不可误杀；地名多不单独判杀。
    if analysis_hits == 0 and n >= DENSITY_PANCHA_PARAS and total < DENSITY_PANCHA_CHARS:
        return "patchwork"
    return None
