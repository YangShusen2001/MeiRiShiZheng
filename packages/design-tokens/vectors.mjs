#!/usr/bin/env node
/**
 * JS 侧的测试向量校验（与 scripts/audit-tokens.py 同一组向量、同一套阈值）。
 *
 * 这是「对比度公式双实现」的另一半：浏览器/彩蛋页用 wcag.mjs，审计脚本用 Python。
 * 任一侧改动导致结果不一致 → 这里或 Python 那边失败。
 *
 * 由 `pnpm -r test` 触发。
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { contrast, round, runVectors } from "./wcag.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const vectors = JSON.parse(readFileSync(join(HERE, "test-vectors.json"), "utf8"));
const result = runVectors(vectors);

if (!result.ok) {
  console.error(`✗ 测试向量未通过（共 ${result.checked} 项）：`);
  for (const f of result.failures) console.error(`  - ${f}`);
  process.exit(1);
}

console.log(`✓ 测试向量 ${result.checked} 项全部通过（JS 侧）`);
console.log(
  `  阈值 text≥${vectors.thresholds.text} · 非文本≥${vectors.thresholds.nonText} · 标注可见度≥${vectors.thresholds.highlightVisibility}`,
);
const sample = vectors.cases[0];
console.log(`  抽样：${sample.label} = ${round(contrast(sample.fg, sample.bg))}（记录值 ${sample.expect}）`);
