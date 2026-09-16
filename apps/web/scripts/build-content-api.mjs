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
//   digest / summary / practice / cards / policy-lines / archive 保持原样（Web 端不做清洗）。
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { getArchive, listArchiveSummary, listArchiveTotals } from "../src/lib/archive.ts";
import {
  getDigest,
  getPracticeSet,
  getSummary,
  listArchiveArticles,
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

// —— 1b) 政策档案正文：与日更文章**共用 `articles/` 同一个 id 空间** ——
//
// 为什么不分目录（如 `archive/articles/`）：Web 端的 `/read/<id>/` 就是**一条路由**，
// 日更与档案正文拼在同一个 id 空间里（见 `read/[id].astro` 的 getStaticPaths）。
// 客户端若分两处取，`ArchiveItem.readId` 就得先知道自己是哪一类，多一个分类判断、
// 多一个出错面；同目录则 `Endpoints.articleUrl(readId)` 直接可用。
//
// 代价是必须**保证零冲突**——已由下方自校验硬门禁（日更 ∩ 档案 = ∅），
// 不是"实测没撞上"的口头结论。
const archiveArticles = listArchiveArticles();
for (const article of archiveArticles) {
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

// —— 3b) 政策档案：索引 + 逐月台账 ——
//
// 与 days 的关系：`days` 是「今天有什么」，档案是**按月成台账的历史存量**，两者不重叠。
// 所以档案有自己的一份索引（`archive/index.json`），客户端进档案页先取它；
// 而首页只需要三个数，那三个数直接放进 manifest（见下），省一次请求。
//
// 逐月台账原样透出 `getArchive()` 的 items —— 它已经补齐了 `readId`
// （按同目录 `article-*.json` 的 url 对齐），客户端拿到即可判断"能不能站内读"。
const archiveRows = listArchiveSummary();
const archiveTotals = listArchiveTotals();
const archiveMonthDocs = new Map();
for (const row of archiveRows) {
  const doc = getArchive(row.month);
  if (!doc) continue; // listArchiveSummary 已按"archive.json 存在"过滤，这里只是收窄类型
  archiveMonthDocs.set(row.month, doc);
  emit(`archive/${row.month}.json`, doc);
}
emit(
  "archive/index.json",
  { generatedAt: new Date().toISOString(), months: archiveRows, totals: archiveTotals },
  { pretty: true },
);

// —— 4) 清单：客户端的内容发现入口 ——
const manifest = {
  generatedAt: new Date().toISOString(),
  latestDate: days[0]?.date ?? null,
  days,
  cardCount: cards.length,
  policyLineCount: policyLines.length,
  // 首页「政策档案」入口卡用这三个数；完整月份行在 archive/index.json。
  archive: {
    months: archiveTotals.months,
    files: archiveTotals.files,
    core: archiveTotals.core,
  },
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

// —— 政策档案门禁 ——
// 这几条不是"格式检查"，每一条都对应一个**已经会打到用户身上**的故障：
// 前四条错了 → 档案页数字与内容对不上；后三条错了 → 点「查看原文」进 404 或标题变样。

// (1) 日更正文与档案正文共用 `articles/` 同一 id 空间（对齐 Web 端 `/read/<id>/` 单路由）。
//     撞 id 会让其中一篇被覆盖 —— 这是**静默丢内容**，必须拦在构建期。
const dailyIds = new Set(articles.map((a) => a.id));
const archiveIds = new Set(archiveArticles.map((a) => a.id));
const idCollisions = [...archiveIds].filter((id) => dailyIds.has(id));
if (idCollisions.length > 0) {
  failures.push(`日更与档案正文 id 冲突（会互相覆盖）：${idCollisions.slice(0, 3).join("、")}`);
}

// (2) 月份倒序：客户端侧边栏与首页入口卡都直接按数组顺序渲染，不排序。
for (let i = 1; i < archiveRows.length; i += 1) {
  if (archiveRows[i - 1].month <= archiveRows[i].month) {
    failures.push(`archive 月份未按倒序：${archiveRows[i - 1].month} → ${archiveRows[i].month}`);
  }
}

// (3) 全馆合计与逐月汇总必须同源。首页三个数与档案页侧边栏各算一套 → 用户会看到两个答案。
const sumCount = archiveRows.reduce((n, r) => n + r.count, 0);
const sumHigh = archiveRows.reduce((n, r) => n + r.high, 0);
if (archiveTotals.months !== archiveRows.length) {
  failures.push(`totals.months=${archiveTotals.months} 与月份数 ${archiveRows.length} 不一致`);
}
if (archiveTotals.files !== sumCount) {
  failures.push(`totals.files=${archiveTotals.files} 与逐月合计 ${sumCount} 不一致`);
}
if (archiveTotals.core !== sumHigh) {
  failures.push(`totals.core=${archiveTotals.core} 与逐月核心合计 ${sumHigh} 不一致`);
}
if (archiveTotals.firstMonth !== (archiveRows[archiveRows.length - 1]?.month ?? "")) {
  failures.push(`totals.firstMonth=${archiveTotals.firstMonth} 与最早月份不符`);
}
if (archiveTotals.lastMonth !== (archiveRows[0]?.month ?? "")) {
  failures.push(`totals.lastMonth=${archiveTotals.lastMonth} 与最新月份不符`);
}

// (4) manifest 里的三个数就是 totals 的投影（首页靠它渲染，不额外请求）。投影错了同样对不上。
if (
  manifest.archive.months !== archiveTotals.months ||
  manifest.archive.files !== archiveTotals.files ||
  manifest.archive.core !== archiveTotals.core
) {
  failures.push("manifest.archive 与 archive/index.json 的 totals 不一致");
}

// (5)(6)(7) 逐月台账内部自洽 + 条目级可路由性。
for (const row of archiveRows) {
  const doc = archiveMonthDocs.get(row.month);
  if (!doc) {
    failures.push(`${row.month} 缺少台账文件`);
    continue;
  }
  const items = doc.items ?? [];
  const tally = { count: items.length, high: 0, medium: 0, low: 0 };
  for (const it of items) {
    if (it.importance === "高") tally.high += 1;
    else if (it.importance === "中") tally.medium += 1;
    else if (it.importance === "低") tally.low += 1;
    else failures.push(`${row.month} 出现未知分级：${it.importance}`);
  }
  for (const key of ["count", "high", "medium", "low"]) {
    if (doc[key] !== tally[key]) failures.push(`${row.month} 的 ${key}=${doc[key]} 与条目统计 ${tally[key]} 不一致`);
  }
  // 索引行只带 count / high（medium / low 可由 count - high 推出，不重复放）
  for (const key of ["count", "high"]) {
    if (row[key] !== tally[key]) failures.push(`${row.month} 索引行 ${key}=${row[key]} 与条目统计 ${tally[key]} 不一致`);
  }

  const seenUrls = new Set();
  for (const it of items) {
    if (!it.url || !it.title || !it.date || !it.lib || !it.topic) {
      failures.push(`${row.month} 存在字段缺失的档案条目：${it.url || it.title || "（无 url 无标题）"}`);
      continue;
    }
    // url 是 readId 对齐与客户端反查的键，月内重复会让两条指向同一篇
    if (seenUrls.has(it.url)) failures.push(`${row.month} 月内 url 重复：${it.url}`);
    seenUrls.add(it.url);

    // readId 与 hasBody 必须一致，且 readId 必须真有正文文件 ——
    // 「有正文但 readId 空」= 用户被迫跳外链；「无正文但 readId 有值」= 点进去 404。
    const routable = it.readId !== "" && archiveIds.has(it.readId);
    if (routable !== Boolean(it.hasBody)) {
      failures.push(`${row.month} 的 readId/hasBody 不一致（readId=${it.readId || "空"} hasBody=${it.hasBody}）`);
    }
  }
}

if (failures.length > 0) {
  console.error("[kaogong] 内容分发层自校验失败：");
  for (const f of failures) console.error(`          - ${f}`);
  process.exit(1);
}

console.log(
  `[kaogong] 内容分发层已生成 → ${OUT_DIR}：` +
    `${articles.length} 篇日更 + ${archiveArticles.length} 篇档案正文 · ${days.length} 个内容日 · ` +
    `${cards.length} 张卡片 · ${policyLines.length} 条主线 · ` +
    `档案 ${archiveTotals.months} 个月/${archiveTotals.files} 份（核心 ${archiveTotals.core}） · ` +
    `清理 ${pruned} 个陈旧文件`,
);
if (dates.length === 0) {
  console.warn("[kaogong] 警告：content/ 下没有任何日期目录，分发产物为空清单。");
}
if (archiveRows.length === 0) {
  console.warn("[kaogong] 警告：content/archive/ 下没有月份台账，客户端档案页将为空。");
}
