#!/usr/bin/env node
/**
 * 设计令牌生成器：tokens.json（唯一数值源）→ 两份 CSS。
 *
 *   → apps/web/src/styles/tokens.generated.css      Web（:root 浅色 + [data-theme="dark"] 深色）
 *   → pipeline/src/kaogong/review/ui/tokens.css     本地审核后台（--kg-* + --tblr-* 覆盖）
 *
 * 命名映射严格按 docs/design/design-system-v3.md §4 的表：
 *   color.ink      → Web --color-ink        后台 --kg-ink
 *   space.m        → Web --space-m          后台 --kg-space-m
 *   radius.lg      → Web --radius-lg        后台 --kg-radius-lg
 *   font.body      → Web --font-body        后台 --kg-font-body
 *   line.reading   → Web --line-reading     后台 --kg-line-reading
 *   dur.md         → Web --dur-md           后台 --kg-dur-md
 *   shadow.card    → Web --shadow-card      后台 --kg-shadow-card
 *   size.touchMin  → Web --size-touch-min   后台 --kg-size-touch-min
 *
 * 为什么只生成 CSS、不生成 ArkTS：鸿蒙 Tokens.ets 承载不可再生的踩坑注释（fontScale 的
 * ArkUI 依赖追踪陷阱、MUT 仅限白卡、"深色不做反色"的理由），生成器覆盖会毁掉这些知识。
 * 值由 scripts/audit-tokens.py 强制对齐，结构留给人维护。
 *
 * 用法：
 *   node packages/design-tokens/generate.mjs           写入产物
 *   node packages/design-tokens/generate.mjs --check    只校验产物是否与源一致（CI 用）
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const CHECK = process.argv.includes("--check");

const sourceText = readFileSync(join(HERE, "tokens.json"), "utf8");
const tokens = JSON.parse(sourceText);
// ⚠️ 指纹必须对换行不敏感：Windows 上的编辑器/脚本会把 LF 写成 CRLF，
// 而 Node 按原字节哈希、Python 的 read_text 会把 CRLF 归一成 LF → 不归一化就会「刚重跑完却说产物过期」。
const normalize = (s) => s.replace(/\r\n/g, "\n");
const SOURCE_SHA256 = createHash("sha256").update(normalize(sourceText)).digest("hex");

const kebab = (s) => String(s).replace(/_/g, "-").replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();
const px = (v) => `${v}px`;

/** 主题相关部分。colorPrefix/generalPrefix 决定命名（见文件头映射表）。 */
function themeVars(theme, { colorPrefix, generalPrefix }) {
  const out = [];
  for (const [k, v] of Object.entries(tokens.color[theme])) out.push([`--${colorPrefix}-${kebab(k)}`, v]);
  for (const [k, v] of Object.entries(tokens.highlight[theme])) {
    out.push([`--${generalPrefix}highlight-${kebab(k)}`, v]);
  }
  // 标注软底（AI 标注正文用）：与 highlight 分开发，两者刻意不共用值 ——「机器淡、人工重」。
  for (const [k, v] of Object.entries(tokens.highlightSoft[theme])) {
    out.push([`--${generalPrefix}highlight-soft-${kebab(k)}`, v]);
  }
  for (const [k, v] of Object.entries(tokens.shadow[theme])) out.push([`--${generalPrefix}shadow-${kebab(k)}`, v]);
  return out;
}

/** 与主题无关的标尺部分（两套主题共用）。 */
function scaleVars(generalPrefix) {
  const out = [];
  for (const [k, v] of Object.entries(tokens.space)) out.push([`--${generalPrefix}space-${kebab(k)}`, px(v)]);
  for (const [k, v] of Object.entries(tokens.radius)) out.push([`--${generalPrefix}radius-${kebab(k)}`, px(v)]);
  for (const [k, v] of Object.entries(tokens.font)) out.push([`--${generalPrefix}font-${kebab(k)}`, px(v)]);
  for (const [k, v] of Object.entries(tokens.line)) out.push([`--${generalPrefix}line-${kebab(k)}`, String(v)]);
  for (const [k, v] of Object.entries(tokens.weight)) out.push([`--${generalPrefix}font-weight-${kebab(k)}`, String(v)]);
  for (const [k, v] of Object.entries(tokens.dur)) out.push([`--${generalPrefix}dur-${kebab(k)}`, `${v}ms`]);
  for (const [k, v] of Object.entries(tokens.ease)) {
    if (k.startsWith("_")) continue;
    out.push([`--${generalPrefix}ease-${kebab(k)}`, v]);
  }
  out.push([`--${generalPrefix}size-touch-min`, px(tokens.size.touchMin)]);
  for (const [k, v] of Object.entries(tokens.fontStack)) {
    out.push([`--${generalPrefix}font-family-${kebab(k)}`, v]);
  }
  return out;
}

const renderVars = (vars, indent = "  ") => vars.map(([name, value]) => `${indent}${name}: ${value};`).join("\n");

const WEB = { colorPrefix: "color", generalPrefix: "" };
const ADMIN = { colorPrefix: "kg", generalPrefix: "kg-" };

// 后台是 Tabler 覆盖：键名去掉 --tblr- 前缀后 → 映射到令牌名
const TABLER_MAP = {
  primary: "brand",
  "body-color": "ink",
  muted: "mut",
  "border-color": "line",
  "bg-surface": "surface",
  light: "surface-alt",
  danger: "danger",
  success: "success",
  warning: "warning",
};

function banner(target) {
  return [
    `/* 自动生成，请勿手改：packages/design-tokens/generate.mjs → ${target} */`,
    `/* SOURCE_SHA256:${SOURCE_SHA256} */`,
    `/* 规范 docs/design/design-system-v3.md · ${tokens.meta.version} · ${tokens.meta.updated} */`,
  ].join("\n");
}

function webCss() {
  return [
    banner(tokens.audit.webGenerated),
    "",
    "/* 浅色：暖纸底 */",
    ":root {",
    "  color-scheme: light;",
    renderVars(themeVars("light", WEB)),
    renderVars(scaleVars(WEB.generalPrefix)),
    "}",
    "",
    "/* 深色：深暖灰（独立取值，非反色） */",
    '[data-theme="dark"] {',
    "  color-scheme: dark;",
    renderVars(themeVars("dark", WEB)),
    "}",
    "",
  ].join("\n");
}

function adminCss() {
  const tblr = tokens.audit.tblrOverrides
    .map((name) => `  ${name}: var(--kg-${TABLER_MAP[name.replace(/^--tblr-/, "")]});`)
    .join("\n");

  return [
    banner(tokens.audit.adminGenerated),
    "",
    "/* 必须置于 Tabler CDN <link> 之后：既有类名自动换肤，布局零改动 */",
    ":root {",
    "  color-scheme: light;",
    renderVars(themeVars("light", ADMIN)),
    renderVars(scaleVars(ADMIN.generalPrefix)),
    "",
    "  /* —— 覆盖 Tabler 变量，使既有类名换肤 —— */",
    tblr,
    "}",
    "",
  ].join("\n");
}

const targets = [
  [tokens.audit.webGenerated, webCss()],
  [tokens.audit.adminGenerated, adminCss()],
];

let stale = 0;
for (const [rel, content] of targets) {
  const abs = join(REPO, rel);
  if (CHECK) {
    let current = "";
    try {
      current = readFileSync(abs, "utf8");
    } catch {
      current = "";
    }
    if (current !== content) {
      stale += 1;
      console.error(`✗ 产物与源不一致（需重跑生成器）：${rel}`);
    } else {
      console.log(`✓ ${rel}`);
    }
  } else {
    writeFileSync(abs, content, "utf8");
    console.log(`写入 ${rel}`);
  }
}

if (CHECK) {
  if (stale > 0) {
    console.error(`\n共 ${stale} 个产物过期。跑：pnpm --filter @kaogong/design-tokens generate`);
    process.exit(1);
  }
  console.log("\n产物与 tokens.json 一致。");
} else {
  console.log(`\n源指纹 SOURCE_SHA256:${SOURCE_SHA256}`);
}
