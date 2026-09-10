// 内容分发层：把仓库根 content/ 产出成一份原生客户端（HarmonyOS）可直接 HTTP 拉取的静态 JSON，
// 输出到 apps/web/public/content/，随 `astro build` → Pages 部署一起上线。
//
// 为什么是「构建期脚本」而不是 Astro 路由端点或 Worker 接口：
//   1. 不新增基础设施（不加 R2、不改 D1、不改 pipeline）——见 ADR 0009；
//   2. 复用 apps/web/src/lib/content.ts 的加载与清洗逻辑，避免两套语义漂移。
//      Node ≥22.18 原生支持类型剥离，可直接 import 该 .ts 模块，无需构建步骤；
//   3. 内容仍然是「构建时快照」，与现有静态站的一致。
//
// 对齐原则（重要）：本脚本产出的字段必须与 Web 端「实际消费」的完全一致——
//   文章经 unescapeArticle 清洗（Web 端 lib/content.ts 同样处理），
//   digest / summary / practice / cards / policy-lines 保持原样（Web 端不做清洗）。
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  getDigest,
  getPracticeSet,
  getSummary,
  listArticles,
  listCards,
  listContentDates,
  listPolicyLines,
} from "../src/lib/content.ts";

if (!process.features.typescript) {
  console.error("[kaogong] 生成内容分发层需要 Node ≥ 22.18（原生 TS 类型剥离）。");
  console.error(`          当前版本：${process.version}。请升级 Node 后重试。`);
  process.exit(1);
}

const CONTENT_DIR = fileURLToPath(new URL("../../../content/", import.meta.url));
// 输出目录可覆盖（测试写入临时目录，避免污染构建产物）。
const OUT_DIR = process.env.KAOGONG_CONTENT_API_OUT
  ? resolve(process.env.KAOGONG_CONTENT_API_OUT)
  : fileURLToPath(new URL("../public/content/", import.meta.url));

/** 本次写出的文件绝对路径，用于收尾时清理陈旧文件。 */
const written = new Set();

function emit(relativePath, value, { pretty = false } = {}) {
  const target = join(OUT_DIR, relativePath);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, pretty ? `${JSON.stringify(value, null, 2)}\n` : JSON.stringify(value), "utf-8");
  written.add(target);
}

/** 读取原始文件（不做清洗），文件缺失返回 null。 */
function readRaw(relativePath) {
  const p = join(CONTENT_DIR, relativePath);
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf-8"));
}

// —— 1) 文章：与 Web 端 `read/[id].astro` 的 getStaticPaths 同源（listArticles 已清洗）——
const articles = listArticles();
for (const article of articles) {
  emit(`articles/${article.id}.json`, article);
}

// —— 2) 逐日内容 ——
const dates = listContentDates();
const days = [];
for (const date of dates) {
  const digest = getDigest(date);
  const summary = getSummary(date);
  const practice = getPracticeSet(date);
  const picks = readRaw(`${date}/picks.json`);

  if (digest) emit(`${date}/digest.json`, digest);
  if (summary) emit(`${date}/summary.json`, summary);
  if (practice) emit(`${date}/practice.json`, practice);
  if (picks) emit(`${date}/picks.json`, picks);

  days.push({
    date,
    // 摘要足够客户端渲染卡片、并把日报条目的 sourceUrl 反查成文章 id，避免逐篇拉取全文。
    articles: articles
      .filter((a) => a.date === date)
      .map((a) => ({
        id: a.id,
        title: a.title,
        source: a.source,
        url: a.url,
        aiStatus: a.aiStatus ?? "unknown",
      })),
    hasDigest: Boolean(digest),
    hasSummary: Boolean(summary),
    hasPractice: Boolean(practice),
    hasPicks: Boolean(picks),
  });
}

// —— 3) 跨日内容 ——
const cards = listCards();
const policyLines = listPolicyLines();
emit("cards.json", cards);
emit("policy-lines.json", policyLines);

// —— 4) 清单：客户端的内容发现入口 ——
const manifest = {
  generatedAt: new Date().toISOString(),
  latestDate: days[0]?.date ?? null,
  days,
  cardCount: cards.length,
  policyLineCount: policyLines.length,
};
emit("manifest.json", manifest, { pretty: true });

// —— 5) 清理陈旧产物（内容被删除后，旧 JSON 不应继续留在部署产物里）——
let pruned = 0;
function prune(dir) {
  if (!existsSync(dir)) return;
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) {
      prune(p);
      if (readdirSync(p).length === 0) rmSync(p, { recursive: true, force: true });
    } else if (!written.has(p)) {
      rmSync(p, { force: true });
      pruned += 1;
    }
  }
}
prune(OUT_DIR);

// —— 6) 自校验：清单不合法就失败，避免把坏产物推上线 ——
const failures = [];
if (manifest.latestDate !== (days[0]?.date ?? null)) failures.push("latestDate 与 days[0] 不一致");
for (let i = 1; i < days.length; i += 1) {
  if (days[i - 1].date <= days[i].date) failures.push(`days 未按倒序：${days[i - 1].date} → ${days[i].date}`);
}
for (const day of days) {
  if (day.hasDigest && day.articles.length === 0) failures.push(`${day.date} 有 digest 但无文章`);
}
if (cards.some((c) => !c.id || !c.question || !c.answer)) failures.push("存在字段缺失的卡片");
if (policyLines.some((l) => !l.id || !l.name)) failures.push("存在字段缺失的政策主线");
if (failures.length > 0) {
  console.error("[kaogong] 内容分发层自校验失败：");
  for (const f of failures) console.error(`          - ${f}`);
  process.exit(1);
}

console.log(
  `[kaogong] 内容分发层已生成 → ${OUT_DIR}：` +
    `${articles.length} 篇文章 · ${days.length} 个内容日 · ${cards.length} 张卡片 · ` +
    `${policyLines.length} 条主线 · 清理 ${pruned} 个陈旧文件`,
);
if (dates.length === 0) {
  console.warn("[kaogong] 警告：content/ 下没有任何日期目录，分发产物为空清单。");
}
