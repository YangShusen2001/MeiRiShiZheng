#!/usr/bin/env node
// ArkTS 静态自检：把「本仓库约定的硬约束」变成可执行的检查。
//
// 用法：node apps/harmony/scripts/audit-arkts.mjs
//
// 为什么要它：项目里有几条纪律靠人记不住——
//   · 页面不得出现硬编码色值/字号/间距（视觉唯一事实源是 theme/Tokens.ets）
//   · 不得使用 any/unknown（ArkTS 硬性限制）
//   · 令牌已由常量改为方法，漏改会静默失效
//   · ArkTS 不支持字面量类型与 as const（arkts-no-as-const）
// 这些都是「编译期不一定报错、但会让设计体系悄悄崩掉」的问题，必须脚本化。
//
// ⚠️ 血的教训（2026-09-16）：规则 6 曾写成只匹配 `[A-Z_]{2,}`（旧常量式 `KColor.PRIMARY`）。
//    令牌改成方法后成员变 camelCase，**这条规则从此永不命中** —— 于是
//    `.borderColor(KColor.primary)`（漏写调用括号）一路漏到 DevEco 编译才炸。
//    **正则不会报错，只会静默不匹配。** 所以本脚本先跑「规则自检」：
//    每条正则规则都配正/负样本，跑之前先证明它还能命中。
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { dirname, join, relative, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ETS_ROOT = join(HERE, "..", "entry/src/main/ets");
const REPO_ROOT = join(HERE, "..", "..", "..");

/**
 * 规则正则集中定义 —— 既用于扫描，也用于开头的「规则自检」。
 * `hit` 必须命中，`miss` 必须不命中；任一不满足 ⇒ 该规则已不可信，直接失败。
 * 新增正则规则时**必须同时补一对样本**，否则规则会在某次重构后悄悄失效。
 */
const RULES = {
  legacyToken: {
    // 令牌已改为方法，漏写调用括号会静默失效（`.borderColor(KColor.primary)` 传的是函数引用）
    re: () => /\b(KColor|KFont|KLine)\.[A-Za-z_][A-Za-z0-9_]*\b(?!\s*\()/g,
    hit: ".borderColor(KColor.primary)",
    miss: ".borderColor(KColor.primary())",
  },
  anyUnknown: {
    re: () => /:\s*(any|unknown)\b/g,
    hit: "let x: any",
    miss: "let x: string",
  },
  hardcodedHex: {
    re: () => /#[0-9A-Fa-f]{6,8}/g,
    hit: ".fontColor('#4C795B')",
    miss: ".fontColor(KColor.primary())",
  },
  literalUnion: {
    re: () => /:\s*'[^']*'\s*\|\s*'[^']*'/g,
    hit: "importance: '高' | '中'",
    miss: "importance: string",
  },
  bareTier: {
    re: () => /'(高|中|低)'/g,
    hit: "this.tierTag(ArchiveTier.CORE, '高')",
    miss: "this.tierTag(ArchiveTier.CORE, label)",
  },
};

const deadRules = [];
for (const [name, spec] of Object.entries(RULES)) {
  const hits = spec.hit.match(spec.re());
  const misses = spec.miss.match(spec.re());
  if (!hits || hits.length === 0) {
    deadRules.push(`${name}: 正样本未命中 —— 规则已失效，会静默放过所有违规`);
  } else if (misses && misses.length > 0) {
    deadRules.push(`${name}: 负样本被误判为违规（命中 ${misses.join(" / ")}）—— 规则过宽，会产生假阳性`);
  }
}
if (deadRules.length > 0) {
  console.log("✗ 规则自检失败 —— 门禁本身已不可信，先修规则：");
  for (const d of deadRules) console.log(`  ${d}`);
  process.exit(1);
}

/** 递归收集 .ets（跳过构建产物）。 */
function collect(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === "build" || name === "oh_modules") continue;
      out.push(...collect(full));
    } else if (name.endsWith(".ets")) {
      out.push(full);
    }
  }
  return out;
}

/** 解析 `import { a as b, c } from '…'` 的本地名，供"未使用"检查使用。 */
function importedNames(source) {
  const names = [];
  for (const m of source.matchAll(/import\s*\{([^}]+)\}\s*from/g)) {
    for (const raw of m[1].split(",")) {
      const part = raw.trim();
      if (!part) continue;
      const asMatch = /^\S+\s+as\s+(\S+)$/.exec(part);
      names.push(asMatch ? asMatch[1] : part);
    }
  }
  return names;
}

/**
 * 剥掉注释后再做「代码里不该出现 X」的检查。
 * 不剥的话，**解释这条规则的注释本身会把检查打红** —— 而注释恰恰是最该写清楚规则的地方。
 *
 * ⚠️ `//` 必须排除 `://`：`static readonly BASE = 'https://…'` 这类行若被当成注释吃掉，
 *    同一行后面的真实代码就变成**盲区**（规则看不见 = 静默放过）。
 */
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

const files = collect(ETS_ROOT);
const issues = [];
let importCount = 0;

for (const file of files) {
  const rel = relative(REPO_ROOT, file).replace(/\\/g, "/");
  const source = readFileSync(file, "utf-8");
  const code = stripComments(source);
  const isTokens = file.endsWith("Tokens.ets");

  // 1) 相对导入必须可达（看原文：注释里的 import 示例不算数）
  for (const m of source.matchAll(/from\s+'(\.[^']+)'/g)) {
    importCount++;
    const base = normalize(join(dirname(file), m[1]));
    if (!existsSync(`${base}.ets`) && !existsSync(`${base}.ts`)) {
      issues.push(`${rel}: 无法解析导入 ${m[1]}`);
    }
  }

  // 2) ArkTS 禁用 any / unknown
  for (const m of code.matchAll(RULES.anyUnknown.re())) {
    issues.push(`${rel}: 使用了禁止类型 ${m[1]}`);
  }

  // 3) 导入符号必须被使用（按本地名匹配，兼容 as 别名）。
  //    只在**剥注释后的代码**里数 —— 只出现在注释里的导入实际就是未使用。
  for (const local of importedNames(source)) {
    const hits = code.split(new RegExp(`\\b${local}\\b`)).length - 1;
    if (hits < 2) issues.push(`${rel}: 导入未使用 ${local}`);
  }

  // 4) @Builder 必须被引用（同上：引用要落在真实代码里）
  for (const m of code.matchAll(/@Builder\s+([A-Za-z_][A-Za-z0-9_]*)/g)) {
    const hits = code.split(new RegExp(`\\b${m[1]}\\b`)).length - 1;
    if (hits < 2) issues.push(`${rel}: @Builder ${m[1]} 定义后未被引用`);
  }

  if (isTokens) continue;

  // 5) 硬编码色值只允许出现在 Tokens.ets
  for (const m of code.matchAll(RULES.hardcodedHex.re())) {
    issues.push(`${rel}: 硬编码色值 ${m[0]}（应改用 theme/Tokens.ets 的令牌）`);
  }

  // 6) 令牌已改为方法，残留的常量式引用（漏写括号）会静默失效。
  //    传的是 `() => string` 而不是颜色 —— 静态门禁是唯一能在本地拦住它的地方。
  for (const m of code.matchAll(RULES.legacyToken.re())) {
    issues.push(`${rel}: 令牌漏写调用括号 ${m[0]}（应为 ${m[0]}()）`);
  }

  // 7) ArkTS 不支持字面量类型（迁移指南规则 arkts-no-as-const：
  //    「ArkTS 不支持 as const 断言和字面量类型」）。
  //    这行代码在 .ts 里合法、在 .ets 里**编译不过**，而本地 CLI 不编译 —— 必须脚本化兜住。
  //    契约里的字面量联合（如 ContentArchiveImportance）在 ArkTS 侧一律退化为 string。
  for (const m of code.matchAll(RULES.literalUnion.re())) {
    issues.push(`${rel}: 字面量联合类型 ${m[0]}（ArkTS 不支持字面量类型，见 arkts-no-as-const）`);
  }

  // 8) 档案分级取值不得裸写。定义在 service/Archive.ets（ArchiveTier），
  //    色值映射在 theme/Tokens.ets —— 其余文件一律走常量，避免拼错一个汉字静默变色。
  if (!file.endsWith("Archive.ets")) {
    for (const m of code.matchAll(RULES.bareTier.re())) {
      issues.push(`${rel}: 裸写的档案分级 ${m[0]}（应改用 service/Archive.ets 的 ArchiveTier）`);
    }
  }
}

console.log(`扫描 ${files.length} 个 .ets 文件，${importCount} 个相对导入`);
if (issues.length === 0) {
  console.log("✓ 全部通过");
  process.exit(0);
}
console.log(`✗ 发现 ${issues.length} 个问题：`);
for (const issue of issues) console.log(`  ${issue}`);
process.exit(1);
