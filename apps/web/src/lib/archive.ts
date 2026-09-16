// 政策档案加载器：构建时读仓库根 content/archive/<YYYY-MM>/archive.json。
// 数据由 scripts/fetch-archive.py（抓取）+ scripts/curate-archive.py（AI 分层）产出。
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ARCHIVE_DIR = fileURLToPath(new URL("../../../../content/archive/", import.meta.url));

export type ArchiveImportance = "高" | "中" | "低";

export interface ArchiveItem {
  url: string;
  title: string;
  date: string;
  lib: string;
  importance: ArchiveImportance;
  topic: string;
  gist: string;
  /**
   * 关键数字（画布 3:382）：`·` 分隔的量化指标名，如「参保率 95% 以上 · 人均预期寿命 80 岁」。
   * 由 scripts/curate-archive.py 搭同一次 AI 调用产出；空串 = 该文件没有可量化指标。
   * 可选：2026-09-15 之前产出的档案没有这个字段，前端条件渲染（拿不到就不渲染）。
   */
  figures?: string;
  hasBody: boolean;
  /**
   * 该条目对应的**站内阅读页** id（`/read/<id>/`）；没有正文时为空串。
   *
   * 由 `getArchive()` 按同目录 `article-*.json` 的 url 对齐后填入——
   * 正文文件名就是 id（`fetch-archive.py` 用 `md5(url)[:10]` 生成），
   * 所以不需要读正文内容，扫文件名 + 一条 url 即可。
   *
   * ⚠️ 实测 `hasBody` 与正文文件存在性 **100% 一致**（1175 条 = 1137 有正文 + 38 无正文），
   * 但链接判断仍以本字段为准而不是 `hasBody`：文件才是路由能否成立的事实源。
   */
  readId: string;
}

export interface ArchiveMonth {
  month: string;
  count: number;
  high: number;
  medium: number;
  low: number;
  items: ArchiveItem[];
}

/** 全部可用月份，倒序（最新在前）。 */
export function listArchiveMonths(): string[] {
  if (!existsSync(ARCHIVE_DIR)) return [];
  return readdirSync(ARCHIVE_DIR)
    .filter((name) => /^\d{4}-\d{2}$/.test(name) && existsSync(join(ARCHIVE_DIR, name, "archive.json")))
    .sort()
    .reverse();
}

/** 月份摘要：供侧边栏标注每月文件数与核心数（不加载全部条目）。 */
export interface ArchiveSummary {
  month: string;
  count: number;
  high: number;
}

export function listArchiveSummary(): ArchiveSummary[] {
  return listArchiveMonths().map((month) => {
    const doc = getArchive(month);
    return {
      month,
      count: doc?.count ?? 0,
      high: doc?.high ?? 0,
    };
  });
}

/**
 * 某月的「官方 URL → 站内阅读页 id」索引。
 *
 * 只为**有正文**的条目存在（38 条 hasBody=false 的没有正文文件）。
 * 模块级缓存：`getArchive()` 会被首页月份卡、月页、详情页反复调用，
 * 不缓存就会把同一个月几十个正文文件反复解析。
 */
const readIndexCache = new Map<string, Map<string, string>>();

function monthReadIndex(month: string): Map<string, string> {
  const cached = readIndexCache.get(month);
  if (cached) return cached;
  const idx = new Map<string, string>();
  const dir = join(ARCHIVE_DIR, month);
  if (existsSync(dir)) {
    for (const f of readdirSync(dir)) {
      if (!f.startsWith("article-") || !f.endsWith(".json")) continue;
      try {
        const doc = JSON.parse(readFileSync(join(dir, f), "utf-8")) as { url?: string };
        // id 取**文件名**：路由 /read/<id>/ 就是按 article-<id>.json 解析的
        if (doc.url) idx.set(doc.url, f.slice("article-".length, -".json".length));
      } catch {
        /* 单个正文损坏不该让整月档案加载失败 */
      }
    }
  }
  readIndexCache.set(month, idx);
  return idx;
}

export function getArchive(month: string): ArchiveMonth | null {
  const p = join(ARCHIVE_DIR, month, "archive.json");
  if (!existsSync(p)) return null;
  const doc = JSON.parse(readFileSync(p, "utf-8")) as ArchiveMonth;
  const idx = monthReadIndex(month);
  return {
    ...doc,
    items: (doc.items ?? []).map((it) => ({ ...it, readId: idx.get(it.url) ?? "" })),
  };
}

/** 按年份分组（侧边栏用）：{ "2026": ["2026-09", "2026-08", ...] }。 */
export function groupArchiveMonths(months: string[]): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const m of months) {
    const year = m.slice(0, 4);
    (out[year] ??= []).push(m);
  }
  return out;
}

/** 摘要按年份分组（侧边栏标注每月统计用）。 */
export function groupArchiveSummary(rows: ArchiveSummary[]): Record<string, ArchiveSummary[]> {
  const out: Record<string, ArchiveSummary[]> = {};
  for (const r of rows) {
    (out[r.month.slice(0, 4)] ??= []).push(r);
  }
  return out;
}

/** 全馆合计（首页「政策档案入口」的一句话统计用）。 */
export interface ArchiveTotals {
  /** 最早月份 YYYY-MM；无数据时为空串。 */
  firstMonth: string;
  /** 最新月份 YYYY-MM；无数据时为空串。 */
  lastMonth: string;
  /** 月份总数。 */
  months: number;
  /** 文件总数。 */
  files: number;
  /** 核心考点（importance=高）总数。 */
  core: number;
}

/**
 * 汇总全部月份的合计数。
 * 刻意不新开扫描逻辑：复用 listArchiveSummary()（它已是侧边栏的数据源），
 * 保证首页统计与档案页侧边栏永远同源、不会各算一套。
 */
export function listArchiveTotals(): ArchiveTotals {
  const rows = listArchiveSummary(); // 倒序：最新在前
  return {
    firstMonth: rows[rows.length - 1]?.month ?? "",
    lastMonth: rows[0]?.month ?? "",
    months: rows.length,
    files: rows.reduce((sum, r) => sum + r.count, 0),
    core: rows.reduce((sum, r) => sum + r.high, 0),
  };
}

/** 首页月份卡（画布「政策档案入口」网格）。 */
export interface ArchiveMonthCard {
  month: string;
  count: number;
  high: number;
  /** 要点摘要：优先取「高」标题，不足再补中/低；最多 3 条。 */
  highlights: string[];
}

/**
 * 首页月份卡列表，最新在前，最多 limit 张。
 * 要点优先取核心文件——「核心考点」才是用户划过一眼时要看到的东西，
 * 拿最新几篇的标题反而全是杂项。
 */
export function listArchiveCards(limit: number): ArchiveMonthCard[] {
  return listArchiveSummary()
    .slice(0, limit)
    .map((row) => {
      const items = getArchive(row.month)?.items ?? [];
      const byCore = [...items].sort(
        (a, b) => (a.importance === "高" ? 0 : 1) - (b.importance === "高" ? 0 : 1),
      );
      return {
        month: row.month,
        count: row.count,
        high: row.high,
        highlights: byCore.slice(0, 3).map((it) => it.title),
      };
    });
}
