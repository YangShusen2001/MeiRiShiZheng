/**
 * 设计规范页（`/design/`）与数据来源页（`/sources/`）的数据层。
 *
 * **为什么全部生成、一处手写值都不留**：画布上那些色号、对比度、「品牌色相 229.6°」、
 * 「mut 暖底 5.70」全都是从令牌/配置实算出来的结果。手抄一份就是第二份真相 ——
 * 改令牌时页面会继续理直气壮地报旧值，而且没人会发现。
 *
 * 对比度走 `packages/design-tokens/wcag.mjs`（与 JS 侧测试向量同一份实现），
 * 不在页面里另写公式。
 *
 * ⚠️ 这里用**相对路径**而不是包名：`@kaogong/design-tokens` 没有写进 apps/web 的依赖，
 * pnpm 就不会把它链进 apps/web/node_modules（本环境的 safe-delete 护栏又拦着 `pnpm install`），
 * 用包名会直接构建失败。类型由同目录的 `wcag.d.mts` 提供。
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { contrast, hue, hueDistance, round } from "../../../../packages/design-tokens/wcag.mjs";

const TOKENS_PATH = fileURLToPath(new URL("../../../../packages/design-tokens/tokens.json", import.meta.url));
const CONFIG_PATH = fileURLToPath(new URL("../../../../pipeline/config.json", import.meta.url));

export const TOKENS = JSON.parse(readFileSync(TOKENS_PATH, "utf-8")) as Tokens;
export const PIPELINE_CONFIG = JSON.parse(readFileSync(CONFIG_PATH, "utf-8")) as PipelineConfig;

/** 与 `generate.mjs` 的 kebab 逐字一致，否则算出来的变量名跟产物对不上。 */
export const kebab = (s: string): string =>
  String(s).replace(/_/g, "-").replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();

const light = () => TOKENS.color.light;
const dark = () => TOKENS.color.dark;

// ─────────────────────────── 色系统 ───────────────────────────

export interface Swatch {
  /** 卡上那行文字：`brand · #3A4785` 或带备注 */
  label: string;
  /** 卡片底色 —— 直接取令牌里解析出来的值 */
  hex: string;
  /** 卡上文字颜色（画布逐卡指定，不是算出来的：品牌深底的浅靛与语义色的纯白是刻意的区分） */
  text: string;
  /** 亮/暗底判据，给页面上做无障碍说明用 */
  contrastOnBase?: number;
}

export interface SwatchGroup {
  title: string;
  /** 桌面网格列数：品牌/中性 6 列（卡 205），标注/深色 4 列（卡 316） */
  cols: number;
  swatches: Swatch[];
}

/** 画布 3:686-3:697 —— 品牌与语义 */
const BRAND_SEMANTIC: Array<[string, string]> = [
  ["brand", "#C7CDEB"],
  ["brandDeep", "#C7CDEB"],
  ["danger", "#FFFDF6"],
  ["warning", "#FFFDF6"],
  ["success", "#FFFDF6"],
  ["accent", "#FFFDF6"],
];

/** 画布 3:700-3:711 —— 中性暖墨阶；ink/sub/mut 额外挂一个「压底对比度」 */
const NEUTRALS = ["bg", "surface", "sunken", "ink", "sub", "mut"];

/** 画布 3:714-3:721 —— 标注四色 */
const HIGHLIGHTS: Array<[string, string]> = [
  ["exam_point", "考点"],
  ["viewpoint", "观点"],
  ["term", "术语"],
  ["figure", "数字"],
];

/** 画布 3:724-3:731 —— 深色取值 */
const DARK_ROW: Array<[string, string]> = [
  ["dark bg", "bg"],
  ["dark surface", "surface"],
  ["dark ink", "ink"],
  ["dark brand", "brand"],
];

const under = (label: string, hex: string): Swatch => ({ label, hex, text: "" });

export function swatchGroups(): SwatchGroup[] {
  const l = light();
  const d = dark();

  const brand: Swatch[] = BRAND_SEMANTIC.map(([key, text]) => ({
    label: `${key} · ${l[key]}`,
    hex: l[key],
    text,
  }));

  const neutral: Swatch[] = NEUTRALS.map((key) => {
    const hex = l[key];
    const isInk = key === "ink";
    const isFaded = key === "sub" || key === "mut";
    // 画布 3:707/3:709/3:711：ink 用 dark ink（暖白避眩光），sub/mut 压白字；三者都挂「压底对比度」
    const baseSwatch: Swatch = {
      label: isInk || isFaded
        ? `${key} · ${hex} · 底 ${contrast(hex, l.bg).toFixed(2)}`
        : `${key} · ${hex}`,
      hex,
      text: isInk ? d.ink : isFaded ? "#FFFDF6" : l.ink,
    };
    baseSwatch.contrastOnBase = round(contrast(hex, l.bg), 2);
    return baseSwatch;
  });

  const highlight: Swatch[] = HIGHLIGHTS.map(([key, cn]) => ({
    label: `${cn} ${key} · ${TOKENS.highlight.light[key]}`,
    hex: TOKENS.highlight.light[key],
    text: l.ink,
  }));

  // 标注软底（AI 标注正文用）：彩度压到原值 55%、亮度反解到「对正文底 1.18」。
  // 挂上对底对比度 —— 这组值最容易出的错就是「混得比正文底还亮」，标注直接消失，
  // 而文字对比度查不出来（文字压在软底上照样 11:1）。
  const highlightSoft: Swatch[] = HIGHLIGHTS.map(([key, cn]) => {
    const hex = TOKENS.highlightSoft.light[key];
    const sw: Swatch = {
      label: `${cn} ${key} · ${hex} · 底 ${contrast(hex, l.bg).toFixed(2)}`,
      hex,
      text: l.ink,
    };
    sw.contrastOnBase = round(contrast(hex, l.bg), 2);
    return sw;
  });

  const darkRow: Swatch[] = DARK_ROW.map(([label, key]) => {
    const hex = d[key];
    // 画布 3:725/3:727 用 dark mut，3:729 用 light ink，3:731 用 panelDeep
    const text = key === "ink" ? l.ink : key === "brand" ? "#232C5C" : d.mut;
    const suffix = key === "ink" ? "（暖白，避眩光）" : "";
    return { label: `${label} · ${hex}${suffix}`, hex, text };
  });

  return [
    { title: "品牌与语义", cols: 6, swatches: brand },
    { title: "中性暖墨阶（色相 34–37°，低饱和）", cols: 6, swatches: neutral },
    { title: "标注四色（用户划线用，深色下另有取值）", cols: 4, swatches: highlight },
    { title: "标注软底（AI 标注正文用：彩度 ×0.55，对正文底 1.18）", cols: 4, swatches: highlightSoft },
    { title: "深色（深暖灰，独立取值，不做反色）", cols: 4, swatches: darkRow },
  ];
}

/** 品牌色相与最近邻语义/标注色的距离 —— 审计里的硬约束，这里展示实算结果。 */
export function hueReport(): { brandHue: number; nearest: { token: string; distance: number } } {
  const audit = TOKENS.audit;
  const brandHex = light()[audit.brandToken];
  const brandHue = hue(brandHex);
  const candidates: Array<[string, string]> = [
    ...audit.hueSensitiveTokens.map((k) => [k, light()[k]] as [string, string]),
    ...audit.hueSensitiveHighlights.map((k) => [k, TOKENS.highlight.light[k]] as [string, string]),
  ];
  let nearest = { token: "", distance: Infinity };
  for (const [token, hex] of candidates) {
    const distance = round(hueDistance(brandHue, hue(hex)), 1);
    if (distance < nearest.distance) nearest = { token, distance };
  }
  return { brandHue: round(brandHue, 1), nearest };
}

// ─────────────────────────── 标尺 ───────────────────────────

export interface FontRow {
  key: string;
  size: number;
  sample: string;
  role: string;
}

/** 画布 3:732 的字号行：每档配一句示例与用途。 */
const FONT_SAMPLES: Record<string, [string, string]> = {
  display: ["时政精选", "首页 hero"],
  titleL: ["政策档案", "文章标题"],
  titleM: ["天府新区协同救助", "区块标题"],
  titleS: ["服务出海：新抓手", "卡片标题"],
  body: ["社会救助从给钱转向给服务", "正文"],
  meta: ["新华社 · 2026-09-12 · 阅读约 6 分钟", "次级 UI"],
  caption: ["按栏目分组 · 入选 3 篇", "序号来源"],
  micro: ["AI 概括已通过校验", "微角标"],
};

/** 按画布顺序（从大到小）排，不按 tokens.json 的书写顺序 —— 后者是维护顺序，不是视觉顺序。 */
export const FONT_ORDER = ["display", "titleL", "titleM", "titleS", "body", "meta", "caption", "micro"];

export function fontRows(): FontRow[] {
  return FONT_ORDER.filter((key) => key in TOKENS.font).map((key) => ({
    key,
    size: TOKENS.font[key],
    sample: FONT_SAMPLES[key]?.[0] ?? key,
    role: FONT_SAMPLES[key]?.[1] ?? "",
  }));
}

export interface LineRow {
  key: string;
  value: number;
  cn: string;
  role: string;
  highlight?: boolean;
}

/** 画布 3:732 的行高行：最后一档（reading）在画布上被高亮成选中态。 */
const LINE_META: Array<[string, string, string, boolean?]> = [
  ["tight", "tight", "大标题"],
  ["heading", "heading", "小标题"],
  ["ui", "ui", "界面文本"],
  ["reading", "reading", "正文框", true],
];

export function lineRows(): LineRow[] {
  return LINE_META.filter(([key]) => key in TOKENS.line).map(([key, cn, role, highlight]) => ({
    key,
    value: TOKENS.line[key],
    cn,
    role,
    highlight,
  }));
}

export const weightRows = (): number[] => Object.values(TOKENS.weight).sort((a, b) => a - b);

// ─────────────────────────── 间距与圆角 ───────────────────────────

export interface SpaceRow {
  key: string;
  value: number;
  note?: string;
}

const SPACE_ORDER = ["hair", "xs", "s", "m", "l", "xl", "xxl", "xxxl"];

export function spaceRows(): SpaceRow[] {
  return SPACE_ORDER.filter((k) => k in TOKENS.space).map((key) => ({
    key,
    value: TOKENS.space[key],
  }));
}

export interface RadiusRow {
  key: string;
  value: number;
  note?: string;
  highlight?: boolean;
}

const RADIUS_ORDER = ["xs", "sm", "md", "lg", "xl", "full"];
const RADIUS_NOTE: Record<string, string> = {
  sm: "输入框",
  lg: "卡片",
  full: "胶囊",
};

export function radiusRows(): RadiusRow[] {
  return RADIUS_ORDER.filter((k) => k in TOKENS.radius).map((key) => ({
    key,
    value: TOKENS.radius[key],
    note: RADIUS_NOTE[key],
    highlight: key === "full",
  }));
}

// ─────────────────────────── 无障碍硬约束 ───────────────────────────

export interface RuleRow {
  text: string;
}

/** 画布 3:855 的四条 —— 数字全部实算，不写死。 */
export function accessibilityRules(): RuleRow[] {
  const l = light();
  const { brandHue, nearest } = hueReport();
  const minimum = TOKENS.audit.hueMinDistanceDeg;
  // 对比度一律保留两位（5.70 而不是 5.7）：这是给人核的数值，位数不齐看着像随手写的
  const two = (v: number) => v.toFixed(2);
  return [
    { text: `交互元素高度 ≥ ${TOKENS.size.touchMin} —— 条目行、筛选按钮、列表行统一提到 ${TOKENS.size.touchMin}` },
    {
      text: `文本对比度 ≥ 4.5:1 —— mut 暖底 ${two(contrast(l.mut, l.bg))} / 纸卡 ${two(contrast(l.mut, l.surface))}，双底过 AA`,
    },
    { text: "不依赖颜色单独传达 —— 标注除底色外同时带类型文字标签" },
    {
      text: `品牌色相与任一语义／标注色距离 ≥ ${minimum}° —— ${brandHue}° 距最近邻 ${nearest.distance}°`,
    },
  ];
}

// ─────────────────────────── 数据来源 ───────────────────────────

export interface SourceRow {
  name: string;
  kind: string;
  usage: string;
}

/** 栏目槽位 → 面向读者的去向。槽位码一并展示，便于对着 config.json 核。 */
const SLOT_LABEL: Record<string, string> = {
  pol: "时政要闻",
  gov: "月度政策档案",
  gdp: "月度政策档案",
  qst: "申论精读",
  xh: "申论精读",
  rm: "申论精读",
  byt: "申论精读",
  shi: "申论精读",
  nf: "申论精读",
  gd: "地方要闻",
  js: "地方要闻",
  sc: "地方评论",
  essay: "地方理论专栏",
};

const TIER_LABEL: Record<string, string> = { core: "核心", background: "背景" };

/** 把 `column_keep_re` / `column_drop_re` / `title_drop` 翻译成人话 —— 这就是栏目级判定本身。 */
function usageText(src: PipelineSource): string {
  const parts: string[] = [];
  const tier = TIER_LABEL[src.tier] ?? src.tier;
  parts.push(`${tier}来源`);
  if (src.column_keep_re) parts.push(`只取匹配「${src.column_keep_re}」的栏目`);
  if (src.column_drop_re) parts.push(`排除匹配「${src.column_drop_re}」的条目`);
  if (src.title_drop?.length) parts.push(`标题层再丢 ${src.title_drop.length} 类（${src.title_drop.join(" / ")}）`);
  if (!src.column_keep_re && !src.column_drop_re && !src.title_drop?.length) parts.push("按来源整体采集");
  return parts.join(" · ");
}

export function sourceRows(): SourceRow[] {
  return PIPELINE_CONFIG.sources.map((src) => ({
    name: src.name,
    kind: `${SLOT_LABEL[src.slot] ?? src.slot}（${src.slot}）`,
    usage: usageText(src),
  }));
}

export function sourceStats(): { sources: number; rules: number } {
  // 「栏目级判定」的真实条数 = 保留规则 + 排除规则 + 标题层丢弃规则。
  // 画布上写的是「22 条栏目白名单」，那是画稿时的示意数；这里按 config 实数。
  const rules = PIPELINE_CONFIG.sources.reduce(
    (sum, s) => sum + (s.column_keep_re ? 1 : 0) + (s.column_drop_re ? 1 : 0) + (s.title_drop?.length ?? 0),
    0,
  );
  return { sources: PIPELINE_CONFIG.sources.length, rules };
}

// ─────────────────────────── 类型 ───────────────────────────

interface Tokens {
  meta: { version: string; updated: string; spec: string };
  color: { light: Record<string, string>; dark: Record<string, string> };
  highlight: { light: Record<string, string>; dark: Record<string, string> };
  highlightSoft: { light: Record<string, string>; dark: Record<string, string> };
  space: Record<string, number>;
  radius: Record<string, number>;
  font: Record<string, number>;
  line: Record<string, number>;
  weight: Record<string, number>;
  size: { touchMin: number };
  audit: {
    brandToken: string;
    hueSensitiveTokens: string[];
    hueSensitiveHighlights: string[];
    hueMinDistanceDeg: number;
    fontRungs: number[];
    lineRungs: number[];
  };
}

interface PipelineSource {
  name: string;
  slot: string;
  tier: string;
  column_keep_re?: string;
  column_drop_re?: string;
  title_drop?: string[];
}

interface PipelineConfig {
  sources: PipelineSource[];
}
