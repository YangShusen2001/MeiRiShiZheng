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
  hasBody: boolean;
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

export function getArchive(month: string): ArchiveMonth | null {
  const p = join(ARCHIVE_DIR, month, "archive.json");
  if (!existsSync(p)) return null;
  const doc = JSON.parse(readFileSync(p, "utf-8")) as ArchiveMonth;
  return { ...doc, items: doc.items ?? [] };
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
