/**
 * WCAG 2.1 相对亮度 / 对比度 —— JS 侧实现。
 *
 * ⚠️ 本文件与 scripts/audit-tokens.py 是同一套公式的**双实现**。
 * 一旦漂移就会出现「网页显示 7.70、脚本说 7.68」这类最难查的不一致。
 * 两边共用 packages/design-tokens/test-vectors.json 的向量与阈值，任一改动不一致即失败。
 */

/** 解析 #RGB / #RRGGBB。alpha 通道不在对比度计算范围内，遇到 8 位直接抛错以免静默算错。 */
export function parseHex(hex) {
  const raw = String(hex ?? "").trim();
  const short = /^#([0-9a-fA-F]{3})$/;
  const long = /^#([0-9a-fA-F]{6})$/;
  const mShort = raw.match(short);
  if (mShort) {
    const [r, g, b] = mShort[1].split("").map((c) => parseInt(c + c, 16));
    return [r, g, b];
  }
  const mLong = raw.match(long);
  if (mLong) {
    const v = mLong[1];
    return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
  }
  throw new Error(`不是可用的 6 位/3 位 hex 颜色：${raw}`);
}

function channelToLinear(channel8) {
  const c = channel8 / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** WCAG 2.1 相对亮度，返回 0–1。 */
export function luminance(hex) {
  const [r, g, b] = parseHex(hex);
  return 0.2126 * channelToLinear(r) + 0.7152 * channelToLinear(g) + 0.0722 * channelToLinear(b);
}

/** 对比度比值，返回 1–21。 */
export function contrast(fg, bg) {
  const a = luminance(fg);
  const b = luminance(bg);
  const light = Math.max(a, b);
  const dark = Math.min(a, b);
  return (light + 0.05) / (dark + 0.05);
}

/** 四舍五入到 n 位小数（用于展示；比较请用容差）。 */
export function round(value, digits = 2) {
  const f = Math.pow(10, digits);
  return Math.round(value * f) / f;
}

/** HSL 色相角（0–360）。低饱和中性色色相不稳定，只对已声明的语义/标注色使用。 */
export function hue(hex) {
  const [r8, g8, b8] = parseHex(hex);
  const r = r8 / 255;
  const g = g8 / 255;
  const b = b8 / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  if (d === 0) return 0;
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h *= 60;
  return h < 0 ? h + 360 : h;
}

/** 两个色相角的最短环形距离（0–180）。 */
export function hueDistance(a, b) {
  const d = Math.abs(((a - b) % 360 + 360) % 360);
  return d > 180 ? 360 - d : d;
}

/** 跑一遍测试向量，返回 { ok, failures, checked }。阈值与向量均来自 test-vectors.json。 */
export function runVectors(vectors) {
  const { thresholds, tolerance = 0.03, cases = [], negativeCases = {} } = vectors;
  const failures = [];
  let checked = 0;

  for (const c of cases) {
    checked += 1;
    const got = contrast(c.fg, c.bg);
    if (Math.abs(got - c.expect) > tolerance) {
      failures.push(`${c.label}: 实算 ${round(got)} ≠ 记录值 ${c.expect}（容差 ${tolerance}）`);
      continue;
    }
    if (c.threshold && thresholds[c.threshold] !== undefined && got < thresholds[c.threshold]) {
      failures.push(`${c.label}: ${round(got)} < 阈值 ${thresholds[c.threshold]}（${c.threshold}）`);
    }
  }

  for (const c of negativeCases.cases ?? []) {
    checked += 1;
    const got = contrast(c.fg, c.bg);
    if (Math.abs(got - c.expect) > tolerance) {
      failures.push(`[负例] ${c.label}: 实算 ${round(got)} ≠ 记录值 ${c.expect}`);
      continue;
    }
    if (got >= thresholds.text) {
      failures.push(`[负例] ${c.label}: 实得 ${round(got)} 本应不达 text 阈值 ${thresholds.text}——门禁形同空转`);
    }
  }

  return { ok: failures.length === 0, failures, checked };
}
