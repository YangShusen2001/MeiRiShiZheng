/**
 * `wcag.mjs` 的类型声明（与实现同目录，TS 会自动把 `.d.mts` 配到 `.mjs` 上）。
 *
 * 为什么不重写一份实现：对比度公式在本仓已有**两份**（`wcag.mjs` 给 JS 侧测试向量、
 * `scripts/audit-tokens.py` 给审计），规范正文明确要求「改任一侧两头跑」。
 * 规范页再抄第三份，就等于多一个会漂移的真相源 —— 所以这里只加类型。
 */
export function parseHex(hex: string): [number, number, number];
export function luminance(hex: string): number;
/** WCAG 2.1 对比度（比值，1–21） */
export function contrast(fg: string, bg: string): number;
export function round(value: number, digits?: number): number;
export function hue(hex: string): number;
/** 两个色相角之间的最短距离（度，0–180） */
export function hueDistance(a: number, b: number): number;
export function runVectors(vectors: unknown): { passed: number; failed: unknown[] };
