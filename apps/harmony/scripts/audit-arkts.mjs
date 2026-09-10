#!/usr/bin/env node
// ArkTS 静态自检：把「本仓库约定的硬约束」变成可执行的检查。
//
// 用法：node apps/harmony/scripts/audit-arkts.mjs
//
// 为什么要它：项目里有几条纪律靠人记不住——
//   · 页面不得出现硬编码色值/字号/间距（视觉唯一事实源是 theme/Tokens.ets）
//   · 不得使用 any/unknown（ArkTS 硬性限制）
//   · 令牌已由常量改为方法，漏改会静默失效
// 这些都是"编译期不一定报错、但会让设计体系悄悄崩掉"的问题，必须脚本化。
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { dirname, join, relative, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ETS_ROOT = join(HERE, "..", "entry/src/main/ets");
const REPO_ROOT = join(HERE, "..", "..", "..");

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

const files = collect(ETS_ROOT);
const issues = [];
let importCount = 0;

for (const file of files) {
  const rel = relative(REPO_ROOT, file).replace(/\\/g, "/");
  const source = readFileSync(file, "utf-8");
  const isTokens = file.endsWith("Tokens.ets");

  // 1) 相对导入必须可达
  for (const m of source.matchAll(/from\s+'(\.[^']+)'/g)) {
    importCount++;
    const base = normalize(join(dirname(file), m[1]));
    if (!existsSync(`${base}.ets`) && !existsSync(`${base}.ts`)) {
      issues.push(`${rel}: 无法解析导入 ${m[1]}`);
    }
  }

  // 2) ArkTS 禁用 any / unknown
  for (const kw of ["any", "unknown"]) {
    if (new RegExp(`:\\s*${kw}\\b`).test(source)) {
      issues.push(`${rel}: 使用了禁止类型 ${kw}`);
    }
  }

  // 3) 导入符号必须被使用（按本地名匹配，兼容 as 别名）
  for (const local of importedNames(source)) {
    const hits = source.split(new RegExp(`\\b${local}\\b`)).length - 1;
    if (hits < 2) issues.push(`${rel}: 导入未使用 ${local}`);
  }

  // 4) @Builder 必须被引用
  for (const m of source.matchAll(/@Builder\s+([A-Za-z_][A-Za-z0-9_]*)/g)) {
    const hits = source.split(new RegExp(`\\b${m[1]}\\b`)).length - 1;
    if (hits < 2) issues.push(`${rel}: @Builder ${m[1]} 定义后未被引用`);
  }

  if (isTokens) continue;

  // 5) 硬编码色值只允许出现在 Tokens.ets
  for (const m of source.matchAll(/#[0-9A-Fa-f]{6,8}/g)) {
    issues.push(`${rel}: 硬编码色值 ${m[0]}（应改用 theme/Tokens.ets 的令牌）`);
  }

  // 6) 令牌已改为方法，残留的常量式引用会静默失效
  for (const m of source.matchAll(/\b(KColor|KFont|KLine)\.[A-Z_]{2,}\b(?!\()/g)) {
    issues.push(`${rel}: 旧式令牌引用 ${m[0]}（应为方法调用 ${m[0]}()）`);
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
