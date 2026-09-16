#!/usr/bin/env python3
"""设计令牌审计（纯 Python，无 Node 依赖，供 CI 使用）。

依据：docs/design/design-system-v3.md §4.1。

硬性检查（不通过即 exit 1）
  1. 源指纹一致：tokens.json 的 sha256 必须等于两份生成 CSS 里的 SOURCE_SHA256
     —— 抓住「改了源没重跑生成器」。
  2. 测试向量：与 packages/design-tokens/test-vectors.json 逐条复现比值（对照规范里的实算记录），
     正例须达标、负例（v3 之前的线上真实值）须不达标 —— 后者用于证明门禁不是空转。
  3. WCAG 断言：直接由 tokens.json 派生的成对检查（正文 ≥4.5、深色标注对卡面可见度 ≥1.6）。
  4. 色相环间距：品牌色与任一语义 / 标注色的色相距离 ≥30°（浅深两套主题）。
  5. 后台接线：9 个 --tblr-* 覆盖键齐备且指向 --kg-* 变量；index.html 的 tokens.css link
     必须存在且位于 Tabler CDN 之后。

报告项（默认只告警，--strict 升级为失败）
  6. 裸 hex 扫描：尚未迁移的消费文件里还有多少处硬编码颜色。
  7. 鸿蒙 Tokens.ets 值漂移：逐项比对，列出尚未对齐的令牌（规范 §8 第 3 步收口）。

注意 5 与 7 的区别是刻意的：接线是本次迁移的交付物，必须硬过；
鸿蒙在本轮尚未迁移，用告警如实登记，避免「用一个还没做的目标把 CI 卡死」。

用法：
    python scripts/audit-tokens.py [--json] [--strict]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS_PATH = REPO / "packages" / "design-tokens" / "tokens.json"
VECTORS_PATH = REPO / "packages" / "design-tokens" / "test-vectors.json"

HEX6 = re.compile(r"^#([0-9a-fA-F]{6})$")
ANY_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")

_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_JS_LINE_COMMENT = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    """扫描前先剥注释。

    注释是文档：写清「这个值为什么是 #5A66A8，而不是 color-mix 派生出来的 #616A9C」，
    正是令牌迁移要留下的证据。把注释里的色号算成裸 hex，等于让门禁惩罚正当的说明。

    行注释（`//`）也要剥：`.astro` 的 frontmatter 里会写「不是 var(--color-x)」这类说明，
    不剥的话 CSS 变量检查会把它当成一次真实引用。
    代价是同一行 `https://` 之后的文本也被切掉 —— 对字号/行高/色值这三项检查没有影响。
    """
    text = _JS_LINE_COMMENT.sub("", text)
    return _HTML_COMMENT.sub("", _CSS_COMMENT.sub("", text))


# ─────────────────────────── WCAG 2.1 ───────────────────────────
# ⚠️ 与 packages/design-tokens/wcag.mjs 是同一套公式的双实现。
# 两边共用 test-vectors.json 的向量与阈值，任一漂移即失败。


def parse_hex(value: str) -> tuple[int, int, int]:
    m = HEX6.match(str(value).strip())
    if not m:
        raise ValueError(f"不是可用的 6 位 hex 颜色：{value}")
    v = m.group(1)
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def _to_linear(channel8: int) -> float:
    c = channel8 / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    r, g, b = parse_hex(value)
    return 0.2126 * _to_linear(r) + 0.7152 * _to_linear(g) + 0.0722 * _to_linear(b)


def contrast(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    light, dark = max(a, b), min(a, b)
    return (light + 0.05) / (dark + 0.05)


def hue(value: str) -> float:
    r8, g8, b8 = parse_hex(value)
    r, g, b = r8 / 255, g8 / 255, b8 / 255
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d == 0:
        return 0.0
    if mx == r:
        h = ((g - b) / d) % 6
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return (h * 60) % 360


def hue_distance(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


# ─────────────────────────── 报告 ───────────────────────────


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []
        self.checks: dict[str, object] = {}

    def fail(self, msg: str) -> None:
        self.failures.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ─────────────────────────── 1. 源指纹 ───────────────────────────


def check_fingerprint(rep: Report, tokens_text: str, tokens: dict) -> None:
    # ⚠️ 必须与 generate.mjs 一样对换行归一化：Windows 上脚本/编辑器可能把 tokens.json 写成 CRLF，
    # 而 Node 按原字节哈希、Python 的 read_text 会把 CRLF 归一成 LF —— 不归一化就会出现
    # 「刚重跑完生成器，审计却说产物过期」这种最费时间的假告警。
    digest = hashlib.sha256(tokens_text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
    rep.checks["source_sha256"] = digest
    pattern = re.compile(tokens["audit"]["generatedBannerPattern"])
    found_any = False
    for key in ("webGenerated", "adminGenerated"):
        rel = tokens["audit"][key]
        path = REPO / rel
        if not path.exists():
            rep.fail(f"生成产物缺失：{rel}（跑 pnpm --filter @kaogong/design-tokens generate）")
            continue
        m = pattern.search(path.read_text(encoding="utf-8"))
        if not m:
            rep.fail(f"生成产物缺少源指纹标记：{rel}")
            continue
        found_any = True
        if m.group(1) != digest:
            rep.fail(f"生成产物已过期（源指纹不一致）：{rel} —— 改了 tokens.json 但没重跑生成器")
    rep.checks["fingerprint_ok"] = found_any and not rep.failures


# ─────────────────────────── 2. 测试向量 ───────────────────────────


def check_vectors(rep: Report) -> None:
    vectors = _load_json(VECTORS_PATH)
    thresholds = vectors["thresholds"]
    tol = vectors.get("tolerance", 0.03)
    checked = 0

    for case in vectors["cases"]:
        checked += 1
        got = contrast(case["fg"], case["bg"])
        if abs(got - case["expect"]) > tol:
            rep.fail(
                f"[向量] {case['label']}：实算 {got:.2f} ≠ 记录值 {case['expect']}"
                f"（容差 {tol}，双实现可能已漂移）"
            )
            continue
        key = case.get("threshold")
        if key and key in thresholds and got < thresholds[key]:
            rep.fail(f"[向量] {case['label']}：{got:.2f} < 阈值 {thresholds[key]}（{key}）")

    negatives = vectors.get("negativeCases", {}).get("cases", [])
    for case in negatives:
        checked += 1
        got = contrast(case["fg"], case["bg"])
        if abs(got - case["expect"]) > tol:
            rep.fail(f"[负例] {case['label']}：实算 {got:.2f} ≠ 记录值 {case['expect']}")
            continue
        if got >= thresholds["text"]:
            rep.fail(
                f"[负例] {case['label']}：实得 {got:.2f}，本应不达 text 阈值 "
                f"{thresholds['text']} —— 门禁形同空转"
            )

    rep.checks["vectors_checked"] = checked
    rep.checks["vectors_positive"] = len(vectors["cases"])
    rep.checks["vectors_negative"] = len(negatives)


# ─────────────────────────── 3. WCAG 派生断言 ───────────────────────────


def check_wcag(rep: Report, tokens: dict) -> None:
    text_min = 4.5
    visibility_min = 1.6
    light, dark = tokens["color"]["light"], tokens["color"]["dark"]
    hl_light, hl_dark = tokens["highlight"]["light"], tokens["highlight"]["dark"]
    label = {"exam_point": "考点", "viewpoint": "观点", "term": "术语", "figure": "数字"}

    pairs: list[tuple[str, str, str, float]] = []
    for name, c in (("浅色", light), ("深色", dark)):
        bg, surface = c["bg"], c["surface"]
        for key in ("ink", "sub", "mut"):
            pairs.append((f"{name} {key} 压暖底/深底", c[key], bg, text_min))
            pairs.append((f"{name} {key} 压卡片", c[key], surface, text_min))
        pairs.append((f"{name} brand 压底", c["brand"], bg, text_min))
        pairs.append((f"{name} brand 压卡片", c["brand"], surface, text_min))
        pairs.append((f"{name} brandDeep 压卡片", c["brandDeep"], surface, text_min))
        pairs.append((f"{name} brandInk 压 brandSoft", c["brandInk"], c["brandSoft"], text_min))
        pairs.append((f"{name} onBrand 压 brand（主按钮）", c["onBrand"], c["brand"], text_min))
        for key in ("danger", "warning", "success", "accent"):
            pairs.append((f"{name} {key} 压卡片", c[key], surface, text_min))
        # 中性软底（徽标「排除/未知」用）：文字压在上面必须达标
        pairs.append((f"{name} neutralSoft 软底压次级文字", c["sub"], c["neutralSoft"], text_min))

    # 品牌深底面板（首页 Hero / 页脚 / 被填充的月份卡）。
    # ⚠️ 只跑一遍：panel* 面板色族**两套主题同值**（见 tokens.json color._note），
    # 由 check_panel_invariance 强制这条不变式，所以拿浅色一套代表即可。
    # 如果这里跟着主题循环跑，深色一趟会用翻成亮靛青的 brandDeep/brand 去算，
    # 得出「面板在深色下不可读」的假告警 —— 面板压根不用那两个令牌。
    panel = light
    pairs.append(("面板 Hero 标题压品牌深底", panel["panelStrong"], panel["panelDeep"], text_min))
    pairs.append(("面板 Hero 摘要压品牌深底", panel["panelBody"], panel["panelDeep"], text_min))
    pairs.append(("面板次按钮文字压品牌深底", panel["panelOnBtn"], panel["panelDeep"], text_min))
    pairs.append(("面板日期/页脚链接压品牌深底", panel["panelMeta"], panel["panelDeep"], text_min))
    pairs.append(("面板页脚细字压品牌深底", panel["panelFaint"], panel["panelDeep"], text_min))
    pairs.append(("面板关键词文字压胶囊底", panel["panelBody"], panel["panelChip"], text_min))
    pairs.append(("面板月份数量压品牌底", panel["panelStrong"], panel["panelRaised"], text_min))
    pairs.append(("面板月份标签压品牌底", panel["panelLabel"], panel["panelRaised"], text_min))
    pairs.append(("面板月份要点压品牌底", panel["panelSmall"], panel["panelRaised"], text_min))

    for theme_name, hl in (("浅色", hl_light), ("深色", hl_dark)):
        on_hl = hl["onHighlight"]
        for key, cn in label.items():
            pairs.append((f"{theme_name} {cn}底压标注文字", on_hl, hl[key], text_min))

    # 深色标注底对卡片面的「可见度」：文字对比度合格不代表标记本身看得见（规范 §1.4）
    for key, cn in label.items():
        pairs.append((f"深色 {cn}底对深卡面可见度", hl_dark[key], dark["surface"], visibility_min))

    checked = 0
    worst: tuple[float, str] | None = None
    for name, fg, bg, minimum in pairs:
        checked += 1
        got = contrast(fg, bg)
        if got < minimum:
            rep.fail(f"[WCAG] {name}：{got:.2f} < {minimum}（{fg} on {bg}）")
        if minimum == text_min and (worst is None or got < worst[0]):
            worst = (got, name)

    rep.checks["wcag_pairs"] = checked
    rep.checks["wcag_text_worst"] = (
        {"ratio": round(worst[0], 2), "pair": worst[1]} if worst else None
    )


def check_highlight_soft(rep: Report, tokens: dict) -> None:
    """标注软底（AI 标注正文用）的五条不变式。

    这个检查存在的理由：软底一旦「比页面底还亮」，标注就在页面上消失，
    而 WCAG 文字对比度**查不出来** —— 文字压在软底上依然 11:1 达标。
    2026-09-16 真发生过一次：用 color-mix 朝 --surface(#FFFDF6) 混色，
    而正文底是 --bg(#F5F1E8)，混出来的底比正文底还亮 1%，标注等于没画。
    """
    soft, base = tokens["highlightSoft"], tokens["highlight"]
    keys = ("exam_point", "viewpoint", "term", "figure")
    text_min, visibility_min = 4.5, 1.6
    for theme in ("light", "dark"):
        bg = tokens["color"][theme]["bg"]
        surface = tokens["color"][theme]["surface"]
        on_hl = base[theme]["onHighlight"]
        ratios: list[float] = []
        for k in keys:
            s = soft[theme][k]
            r = contrast(s, bg)
            ratios.append(r)
            if r < 1.10:
                rep.fail(f"[标注软底] {theme} {k} 对页面底 {r:.3f} < 1.10，标注会看不见（{s} on {bg}）")
            t = contrast(on_hl, s)
            if t < text_min:
                rep.fail(f"[标注软底] {theme} {k} 上的标注文字 {t:.2f} < {text_min}（{on_hl} on {s}）")
            # 彩度必须真的降下来。用通道极差代理 OKLCh 彩度，避免再写第三份色彩空间实现。
            d_base = max(parse_hex(base[theme][k])) - min(parse_hex(base[theme][k]))
            d_soft = max(parse_hex(s)) - min(parse_hex(s))
            if d_soft > d_base * 0.75:
                rep.fail(f"[标注软底] {theme} {k} 彩度没降下来：通道极差 {d_soft} vs 原 {d_base}（应 ≤75%）")
            drift = hue_distance(hue(base[theme][k]), hue(s))
            if drift > 20:
                rep.fail(f"[标注软底] {theme} {k} 色相漂移 {drift:.1f}° > 20°，四类将难区分")
        spread = max(ratios) - min(ratios)
        if spread > 0.06:
            rep.fail(f"[标注软底] {theme} 四类对底不齐：极差 {spread:.3f} > 0.06 {[round(r, 3) for r in ratios]}")
        if theme == "dark":
            for k in keys:
                r = contrast(soft[theme][k], surface)
                if r < visibility_min:
                    rep.fail(f"[标注软底] 深色 {k} 对深卡面可见度 {r:.2f} < {visibility_min}")
        rep.checks[f"highlight_soft_{theme}_to_bg"] = [round(r, 3) for r in ratios]


# ─────────────────────── 3b. 标注可读性（解释型术语加粗） ───────────────────────


def check_annotation_affordance(rep: Report, tokens: dict) -> None:
    """「有 AI 解析的术语必须比正文更重」这条信号，不能被样式侧悄悄取消。

    为什么单独立一条：契约里 `explanation` 是 **term 独有**字段（contracts/content.ts），
    阅读页把同一个 `data-explanation` 既当 tooltip 触发器、又当加粗标记 ——
    一个属性承载两个信号。TS 侧有测试兜底（highlights.test.ts 断言它被输出），
    但样式侧如果哪天只剩 `cursor: help`，加粗就无声消失，而页面「看着仍然正常」。
    所以把字重区间钉死：必须严于正文 regular，且不得越过 bold。

    2026-09-16 用户要求：「有 AI 解析的词语，可以加粗」。
    """
    weight_scale = tokens["weight"]
    base = int(weight_scale["regular"])
    ceiling = int(weight_scale["bold"])
    path = REPO / tokens["audit"]["webConsumer"]
    if not path.exists():
        return
    css = strip_comments(path.read_text(encoding="utf-8"))
    rule = re.search(r"\.ai-term\[data-explanation\]\s*\{([^}]*)\}", css)
    if not rule:
        rep.fail(
            "[标注可读性] global.css 里找不到 `.ai-term[data-explanation]` 规则"
            " —— 有 AI 解析的术语将失去视觉区分（只剩 tooltip，用户看不见可悬停）"
        )
        return
    declared = re.search(r"font-weight:\s*(\d{3})", rule.group(1))
    if not declared:
        rep.fail("[标注可读性] `.ai-term[data-explanation]` 未声明 font-weight —— 加粗失效")
        return
    value = int(declared.group(1))
    rep.checks["annotation_explained_weight"] = {"declared": value, "body": base, "ceiling": ceiling}
    if value <= base:
        rep.fail(f"[标注可读性] 解释型术语字重 {value} ≤ 正文 {base}，与普通术语无区别")
    if value > ceiling:
        rep.fail(
            f"[标注可读性] 解释型术语字重 {value} 超过 bold 档 {ceiling}"
            " —— 正文 17px/1.8、标注密度高，过重会结黑斑"
        )


# ─────────────────────────── 4. 色相环间距 ───────────────────────────


def check_hue_ring(rep: Report, tokens: dict) -> None:
    audit = tokens["audit"]
    minimum = audit["hueMinDistanceDeg"]
    for theme in ("light", "dark"):
        brand = tokens["color"][theme][audit["brandToken"]]
        bh = hue(brand)
        distances: dict[str, float] = {}
        for key in audit["hueSensitiveTokens"]:
            distances[key] = hue_distance(bh, hue(tokens["color"][theme][key]))
        for key in audit["hueSensitiveHighlights"]:
            distances[key] = hue_distance(bh, hue(tokens["highlight"][theme][key]))
        closest = min(distances.items(), key=lambda kv: kv[1])
        rep.checks[f"hue_{theme}"] = {
            "brand_hue": round(bh, 1),
            "closest": {"token": closest[0], "distance": round(closest[1], 1)},
        }
        if closest[1] < minimum:
            rep.fail(
                f"[色相环] {theme}：品牌色相 {bh:.1f}° 距 {closest[0]} 仅 {closest[1]:.1f}°"
                f"，要求 ≥{minimum}°"
            )
        # 与背景/卡片对比度同时过关（品牌色相成立的附加条件）
        for bg_key in ("bg", "surface"):
            got = contrast(brand, tokens["color"][theme][bg_key])
            if got < 4.0:
                rep.warn(f"[色相环] {theme}：brand 压 {bg_key} 仅 {got:.2f}，偏低")


# ─────────────────── 4b. 不随主题翻转的色族不变式 ───────────────────


def check_panel_invariance(rep: Report, tokens: dict) -> None:
    """panel* 面板色族必须两套主题同值。

    这条不变式是别的检查的前提：check_wcag 只跑一遍面板对比度（拿浅色代表），
    一旦有人为了「修深色」只改 dark 块里的 panel*，面板就会在深色下偷偷换色，
    而对比度断言仍在拿旧值算 —— 于是门禁静默失效。宁可直接失败。
    """
    names = tokens["audit"]["panelTokens"]
    light, dark = tokens["color"]["light"], tokens["color"]["dark"]
    mismatched: list[dict[str, str]] = []
    for key in names:
        if key not in light or key not in dark:
            rep.fail(f"[面板] 令牌缺失：{key} 必须在 color.light 与 color.dark 同时存在")
            continue
        if light[key].upper() != dark[key].upper():
            mismatched.append({"token": key, "light": light[key], "dark": dark[key]})
    rep.checks["panel_tokens"] = len(names)
    rep.checks["panel_invariance_violations"] = mismatched
    for item in mismatched:
        rep.fail(
            f"[面板] {item['token']} 两套主题取值不同（{item['light']} / {item['dark']}）"
            " —— panel* 是品牌面，不随主题翻转"
        )


# ─────────────────────────── 5. 后台接线 ───────────────────────────

def check_admin_wiring(rep: Report, tokens: dict) -> None:
    audit = tokens["audit"]
    css_path = REPO / audit["adminGenerated"]
    if not css_path.exists():
        rep.fail(f"后台 tokens.css 缺失：{audit['adminGenerated']}")
        return
    css = css_path.read_text(encoding="utf-8")
    missing = [name for name in audit["tblrOverrides"] if f"{name}:" not in css]
    if missing:
        rep.fail(f"后台 tokens.css 缺少 Tabler 覆盖键：{', '.join(missing)}")
    bad = [
        name
        for name in audit["tblrOverrides"]
        if (m := re.search(rf"{re.escape(name)}:\s*([^;]+);", css)) and "var(--kg-" not in m.group(1)
    ]
    if bad:
        rep.fail(f"后台 Tabler 覆盖未指向 --kg-* 变量：{', '.join(bad)}")

    html = (REPO / audit["adminConsumer"]).read_text(encoding="utf-8")
    link = re.search(r"<link[^>]+href=\"([^\"]*tokens\.css)\"[^>]*>", html)
    if not link:
        rep.fail("后台 index.html 未引入 tokens.css")
        return
    rep.checks["admin_tokens_href"] = link.group(1)
    tabler = html.find("tabler")
    if tabler == -1 or html.find(link.group(1)) < tabler:
        rep.fail("后台 index.html 的 tokens.css 必须置于 Tabler CDN <link> 之后（否则会被 Tabler 覆盖）")


# ─────────────────────────── 6. 裸 hex 扫描（报告项） ───────────────────────────


def check_scale(rep: Report, tokens: dict) -> None:
    """字号 / 行高门禁：消费文件里不得出现令牌之外的硬编码档位。

    之前只扫颜色，于是字号可以随便写 —— 结果 Web 里散落着 13/15/16/18/22/30/38px 与 1.35/1.4/1.6/1.75/1.9。
    归并一次不够，得让它不能再散开。按值豁免见 tokens.json 的 scaleExemptions（图标字形、书法体 Logo）。
    """
    audit = tokens["audit"]
    font_rungs = {str(n) for n in audit["fontRungs"]}
    line_rungs = {str(v) for v in audit["lineRungs"]}
    exempt_font = set(audit["scaleExemptions"]["fontSize"].keys())
    exempt_line = set(audit["scaleExemptions"]["lineHeight"].keys())

    web_src = (REPO / audit["webConsumer"]).resolve().parent.parent
    targets: list[tuple[str, Path]] = [("global.css", REPO / audit["webConsumer"])]
    targets += [(p.name, p) for p in sorted(web_src.rglob("*.astro"))]

    bad_font: dict[str, set[str]] = {}
    bad_line: dict[str, set[str]] = {}
    for label, path in targets:
        if not path.exists():
            continue
        text = strip_comments(path.read_text(encoding="utf-8"))
        sizes = set(re.findall(r"font-size: *(\d+)px", text)) | set(re.findall(r"\b(\d+)px/", text))
        for size in sizes:
            if size not in font_rungs and size not in exempt_font:
                bad_font.setdefault(size, set()).add(label)
        for value in set(re.findall(r"line-height: *([0-9.]+);", text)):
            if value not in line_rungs and value not in exempt_line:
                bad_line.setdefault(value, set()).add(label)

    rep.checks["off_scale_font"] = {k: sorted(v) for k, v in sorted(bad_font.items(), key=lambda kv: int(kv[0]))}
    rep.checks["off_scale_line"] = {k: sorted(v) for k, v in sorted(bad_line.items())}
    rep.checks["scale_exempt_font"] = sorted(exempt_font, key=int)
    for size, where in sorted(bad_font.items(), key=lambda kv: int(kv[0])):
        rep.fail(f"[标尺] 非令牌字号 {size}px 出现在：{', '.join(sorted(where))}")
    for value, where in sorted(bad_line.items()):
        rep.fail(f"[标尺] 非令牌行高 {value} 出现在：{', '.join(sorted(where))}")


# ─────────────────── 6b. CSS 变量引用可解析性（硬失败） ───────────────────


# ⚠️ 名字必须**每一段都非空**（`--font-` 不算名字），且后面必须紧跟 `,` 或 `)`。
# 页面里会用模板字符串拼变量名（`var(--font-${kebab(key)})`）：
# 宽松的 `--[a-z0-9-]+` 会把 `--font-` 报成未定义变量，不要求闭合括号会把 `--radius` 也报出来。
CSS_VAR_NAME = r"--[a-z0-9]+(?:-[a-z0-9]+)*"
CSS_VAR_DEF = re.compile(rf"({CSS_VAR_NAME})\s*:")
CSS_VAR_USE = re.compile(rf"var\(\s*({CSS_VAR_NAME})\s*(,|\))")


def check_css_var_refs(rep: Report, tokens: dict) -> None:
    """global.css 与 *.astro 里 `var(--x)` 用到的变量，必须真的有人定义（或带兜底值）。

    为什么算硬失败：CSS 变量取不到值时**不报错**，`color: var(--brand)` 会静默回退成继承值。
    本轮就踩了这个 —— 别名层暴露的名字是 `--primary`，我写了 `--brand`，
    结果底部导航的当前项跟未选中项一个颜色。页面看着「正常」，
    只有量 computed style 才看得出来 —— 正是门禁该拦的那类问题。

    带兜底值的用法（`var(--av, var(--primary-soft))`）**不算违规**：那是有意写的降级，
    典型场景是页面用 style 属性注入（`--av: var(--avatar-3)`），静态扫描看不到定义处。
    """
    web_src = (REPO / tokens["audit"]["webConsumer"]).resolve().parent.parent
    sources = [REPO / tokens["audit"]["webGenerated"], REPO / tokens["audit"]["webConsumer"]]
    sources += sorted(web_src.rglob("*.astro"))

    defined: set[str] = set()
    for path in sources:
        if path.exists():
            defined |= set(CSS_VAR_DEF.findall(strip_comments(path.read_text(encoding="utf-8"))))

    missing: dict[str, set[str]] = {}
    for path in sources:
        if not path.exists():
            continue
        for name, terminator in CSS_VAR_USE.findall(strip_comments(path.read_text(encoding="utf-8"))):
            # 第二个捕获组是 `,` 或 `)`：只有 `,` 才代表带了兜底值
            if terminator == "," or name in defined:
                continue
            missing.setdefault(name, set()).add(path.name)

    rep.checks["undefined_css_vars"] = {k: sorted(v) for k, v in sorted(missing.items())}
    rep.checks["css_var_definitions"] = len(defined)
    for name, where in sorted(missing.items()):
        rep.fail(
            f"[CSS 变量] {name} 既无定义也无兜底值（出现在：{', '.join(sorted(where))}）"
            " —— var() 取不到值会静默回退，界面上只会表现为「颜色不对」"
        )


def check_raw_hex(rep: Report, tokens: dict) -> None:
    audit = tokens["audit"]
    for label, rel in (("Web 全局样式", audit["webConsumer"]), ("后台页面", audit["adminConsumer"])):
        path = REPO / rel
        if not path.exists():
            continue
        count = len(ANY_HEX.findall(strip_comments(path.read_text(encoding="utf-8"))))
        rep.checks[f"raw_hex_{label}"] = count
        if count:
            rep.warn(f"[裸 hex] {label}（{rel}）还有 {count} 处硬编码颜色，待迁移为令牌变量")


# ─────────────────────────── 7. 鸿蒙值漂移（报告项） ───────────────────────────


def check_harmony_drift(rep: Report, tokens: dict) -> None:
    path = REPO / tokens["audit"]["harmonyTokens"]
    if not path.exists():
        rep.warn("[鸿蒙] 找不到 Tokens.ets，跳过比对")
        return

    source = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"static\s+(\w+)\(\):\s*string\s*\{\s*\n\s*return\s+KColor\.isDark\(\)\s*\?\s*"
        r"'(#[0-9A-Fa-f]{6})'\s*:\s*'(#[0-9A-Fa-f]{6})';"
    )
    found = {m.group(1): {"dark": m.group(2), "light": m.group(3)} for m in pattern.finditer(source)}

    # Tokens.ets 方法名 → tokens.json 令牌名（只比对有对应者）
    mapping = {
        "bg": ("color", "bg"),
        "surface": ("color", "surface"),
        "surfaceAlt": ("color", "surfaceAlt"),
        "ink": ("color", "ink"),
        "sub": ("color", "sub"),
        "mut": ("color", "mut"),
        "line": ("color", "line"),
        "lineSoft": ("color", "lineSoft"),
        "primary": ("color", "brand"),
        "primaryText": ("color", "brandInk"),
        "primarySoft": ("color", "brandSoft"),
        "danger": ("color", "danger"),
        "warnInk": ("color", "warning"),
        "neutralSoft": ("color", "neutralSoft"),
        "annExam": ("highlight", "exam_point"),
        "annViewpoint": ("highlight", "viewpoint"),
        "annTerm": ("highlight", "term"),
        "annFigure": ("highlight", "figure"),
        "annInk": ("highlight", "onHighlight"),
    }

    drifted: list[dict[str, str]] = []
    compared = 0
    for method, (group, key) in mapping.items():
        if method not in found:
            rep.warn(f"[鸿蒙] Tokens.ets 未找到方法 {method}()，跳过")
            continue
        for theme in ("light", "dark"):
            compared += 1
            want = tokens[group][theme][key]
            got = found[method][theme]
            if got.upper() != want.upper():
                drifted.append(
                    {"method": f"KColor.{method}()", "theme": theme, "ets": got, "tokens": want}
                )

    rep.checks["harmony_compared"] = compared
    rep.checks["harmony_drift_count"] = len(drifted)
    rep.checks["harmony_drift"] = drifted
    if drifted:
        rep.warn(
            f"[鸿蒙] Tokens.ets 与 tokens.json 有 {len(drifted)}/{compared} 项色值不一致"
            f"（规范 §8 第 3 步收口，需在 DevEco 真机确认）"
        )


# ─────────────────────────── main ───────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="设计令牌审计")
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把报告项（裸 hex / 鸿蒙漂移）升级为失败 —— 三端迁移完成后在 CI 打开",
    )
    args = parser.parse_args()

    tokens_text = TOKENS_PATH.read_text(encoding="utf-8")
    tokens = json.loads(tokens_text)

    rep = Report()
    check_fingerprint(rep, tokens_text, tokens)
    check_vectors(rep)
    check_wcag(rep, tokens)
    check_highlight_soft(rep, tokens)
    check_annotation_affordance(rep, tokens)
    check_hue_ring(rep, tokens)
    check_panel_invariance(rep, tokens)
    check_admin_wiring(rep, tokens)
    check_scale(rep, tokens)
    check_css_var_refs(rep, tokens)
    check_raw_hex(rep, tokens)
    check_harmony_drift(rep, tokens)

    ok = not rep.failures and not (args.strict and rep.warnings)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "failures": rep.failures,
                    "warnings": rep.warnings,
                    "checks": rep.checks,
                    "strict": args.strict,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if ok else 1

    print("设计令牌审计（依据 docs/design/design-system-v3.md §4.1）")
    print("─" * 64)
    src = rep.checks.get("source_sha256", "")
    print(f"源指纹      tokens.json sha256 = {str(src)[:16]}…")
    print(f"生成产物    指纹{'一致' if rep.checks.get('fingerprint_ok') else '不一致或缺失'}")
    print(
        f"测试向量    {rep.checks.get('vectors_checked', 0)} 项"
        f"（正例 {rep.checks.get('vectors_positive', 0)} / 负例 {rep.checks.get('vectors_negative', 0)}）"
    )
    print(f"WCAG 成对   {rep.checks.get('wcag_pairs', 0)} 组")
    if worst := rep.checks.get("wcag_text_worst"):
        print(f"            最紧一档 {worst['ratio']} —— {worst['pair']}")
    for theme in ("light", "dark"):
        info = rep.checks.get(f"hue_{theme}")
        if info:
            print(
                f"色相环 {theme:<5} 品牌 {info['brand_hue']}° · 最近邻 "
                f"{info['closest']['token']} {info['closest']['distance']}°"
            )
    if href := rep.checks.get("admin_tokens_href"):
        print(f"后台接线    link href = {href}")
    print(
        f"面板色族    {rep.checks.get('panel_tokens', 0)} 项主题不变"
        f"（违例 {len(rep.checks.get('panel_invariance_violations') or [])}）"
    )
    for label in ("Web 全局样式", "后台页面"):
        count = rep.checks.get(f"raw_hex_{label}")
        if count is not None:
            print(f"裸 hex      {label} {count} 处")
    undefined = rep.checks.get("undefined_css_vars") or {}
    print(
        f"CSS 变量    {rep.checks.get('css_var_definitions', 0)} 个定义 / "
        f"{len(undefined)} 个无定义且无兜底"
    )
    off_font = rep.checks.get("off_scale_font") or {}
    off_line = rep.checks.get("off_scale_line") or {}
    print(
        f"标尺        非令牌字号 {len(off_font)} 类 / 非令牌行高 {len(off_line)} 类"
        f"（豁免字号 {rep.checks.get('scale_exempt_font')}）"
    )
    compared = rep.checks.get("harmony_compared", 0)
    drift = rep.checks.get("harmony_drift_count", 0)
    if compared:
        print(f"鸿蒙漂移    {drift}/{compared} 项色值待对齐（Tokens.ets 手写，值由本审计强制）")
    print("─" * 64)

    for w in rep.warnings:
        print(f"⚠ {w}")
    for f in rep.failures:
        print(f"✗ {f}")

    if rep.failures:
        print(f"\n✗ 失败 {len(rep.failures)} 项")
    elif args.strict and rep.warnings:
        print(f"\n✗ --strict：报告项 {len(rep.warnings)} 项未清零")
    else:
        print(f"\n✓ 通过（硬性检查全绿；报告项 {len(rep.warnings)} 条待迁移）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
