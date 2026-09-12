"""设计令牌系统回归测试（跨模块：令牌被 pipeline 的审核后台直接消费）。

覆盖三件事：
1. WCAG 实现本身正确 —— 用规范里已实算的数值做独立断言，不依赖向量文件；
2. 审计脚本 --json 能跑通且指纹一致（守住「改了 tokens.json 没重跑生成器」）；
3. 迁移债务被**如实报告**而不是静默 —— 裸 hex 与鸿蒙漂移必须出现在结果里。

注意 3 是刻意的：这些债务在迁移完成前不应让 CI 变红（否则等于用一个还没做的目标把仓库卡死），
但也绝不能消失——所以测的是「有没有被报告」，而不是「是否为零」。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "scripts" / "audit-tokens.py"
TOKENS_PATH = REPO / "packages" / "design-tokens" / "tokens.json"
VECTORS_PATH = REPO / "packages" / "design-tokens" / "test-vectors.json"


def _audit_module():
    """用 spec 加载脚本（scripts/ 不是包），便于直接单测其中的 WCAG 实现。"""
    spec = importlib.util.spec_from_file_location("audit_tokens", AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_audit(*args: str) -> tuple[subprocess.CompletedProcess[bytes], dict]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, str(AUDIT), *args],
        capture_output=True,
        env=env,
        cwd=str(REPO),
    )
    return proc, json.loads(proc.stdout.decode("utf-8"))


# ─────────── 1. WCAG 实现（对照 docs/design/design-system-v3.md 的实算记录）───────────


def test_wcag_reproduces_documented_ratios():
    m = _audit_module()
    # 规范 §2.1：ink 压暖底 13.19；§2.4：考点底压 ink 12.17；§2.2：白字压 brand 8.68
    assert round(m.contrast("#2A2723", "#F5F1E8"), 2) == 13.19
    assert round(m.contrast("#2A2723", "#FFE7A0"), 2) == 12.17
    assert round(m.contrast("#FFFFFF", "#3A4785"), 2) == 8.68
    # 规范 §1.1：旧后台徽标 #c3c9d4 压白字 1.66（最低一档）
    assert round(m.contrast("#FFFFFF", "#c3c9d4"), 2) == 1.66


def test_hue_and_distance_match_spec():
    m = _audit_module()
    # 规范 §2.5：品牌靛青精确色相 229.6°，距术语石青 190.7° 为 38.9°
    assert round(m.hue("#3A4785"), 1) == 229.6
    assert round(m.hue_distance(m.hue("#3A4785"), m.hue("#B9DEE6")), 1) == 38.9


def test_relative_luminance_bounds():
    m = _audit_module()
    assert m.luminance("#000000") == 0.0
    assert round(m.luminance("#FFFFFF"), 4) == 1.0
    assert round(m.contrast("#FFFFFF", "#000000"), 1) == 21.0


# ─────────── 2. 审计脚本可跑通、指纹一致 ───────────


def test_audit_passes_strict_with_zero_debt():
    """迁移收口后，CI 用 --strict 跑：报告项必须为零，任何新增债务立刻变红。

    这一条是「门禁从『只报硬性』升级到『含债务』」的开关 —— 三端迁移做完（2026-09-12）才敢打开。
    如果它开始失败，先看 warnings：多半是有人往消费文件里又写了硬编码颜色，或鸿蒙令牌漂了。
    """
    proc, payload = _run_audit("--json", "--strict")
    assert proc.returncode == 0, payload.get("failures") or payload.get("warnings")
    assert payload["ok"] is True
    assert payload["failures"] == []
    assert payload["warnings"] == [], f"迁移债务不为零：{payload['warnings']}"

    checks = payload["checks"]
    assert checks["fingerprint_ok"] is True, "生成产物与 tokens.json 指纹不一致，需重跑生成器"
    assert checks["vectors_checked"] >= 46
    assert checks["wcag_pairs"] >= 44
    # 后台接线是本次迁移的交付物，必须硬过
    assert checks["admin_tokens_href"].endswith("tokens.css")
    # 三端消费文件都不该再有硬编码颜色
    assert checks["raw_hex_Web 全局样式"] == 0
    assert checks["raw_hex_后台页面"] == 0
    # 鸿蒙令牌与 tokens.json 逐项对齐
    assert checks["harmony_drift_count"] == 0, checks["harmony_drift"]
    # 色相环：品牌与最近邻的间距必须 ≥30°（浅深两套）
    for theme in ("light", "dark"):
        assert checks[f"hue_{theme}"]["closest"]["distance"] >= 30


def test_generated_css_carries_source_fingerprint():
    import hashlib

    tokens_text = TOKENS_PATH.read_text(encoding="utf-8")
    # 与 generate.mjs / audit-tokens.py 同一套归一化：指纹必须对换行不敏感
    digest = hashlib.sha256(tokens_text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    tokens = json.loads(tokens_text)
    for key in ("webGenerated", "adminGenerated"):
        css = (REPO / tokens["audit"][key]).read_text(encoding="utf-8")
        assert f"SOURCE_SHA256:{digest}" in css
        assert "请勿手改" in css


def test_admin_tokens_override_all_tabler_vars():
    tokens = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    css = (REPO / tokens["audit"]["adminGenerated"]).read_text(encoding="utf-8")
    for name in tokens["audit"]["tblrOverrides"]:
        assert f"{name}: var(--kg-" in css, f"{name} 未指向 --kg-* 变量"


# ─────────── 3. 迁移债务必须被报告（不得静默）───────────


def test_migration_debt_is_reported_not_silent():
    _, payload = _run_audit("--json")
    checks = payload["checks"]
    # 鸿蒙本轮未迁移：必须报告漂移数量，且明细可查
    assert isinstance(checks["harmony_drift_count"], int)
    assert checks["harmony_compared"] >= 18
    if checks["harmony_drift_count"] > 0:
        assert checks["harmony_drift"], "报告了漂移计数却没有明细"
        assert any("Tokens.ets" in w for w in payload["warnings"])
    # 未迁移的消费文件里的裸 hex 会被计数（Web 本轮不迁移）
    assert "raw_hex_Web 全局样式" in checks


def test_vectors_file_has_negative_cases():
    """负例是门禁的「非空转证明」：v3 之前的线上真实值必须被判为不达标。"""
    vectors = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    negatives = vectors["negativeCases"]["cases"]
    assert len(negatives) >= 5
    m = _audit_module()
    for case in negatives:
        assert m.contrast(case["fg"], case["bg"]) < vectors["thresholds"]["text"]


def test_strict_mode_escalates_warnings():
    """--strict 的语义：只要有报告项就转红。测的是**机制**而非当前债务数量，
    这样迁移收口后这条测试不会因为「债务清零」而失效。"""
    proc, payload = _run_audit("--json", "--strict")
    assert payload["strict"] is True
    if payload["warnings"]:
        assert payload["ok"] is False
        assert proc.returncode == 1
    else:
        assert payload["ok"] is True
        assert proc.returncode == 0
