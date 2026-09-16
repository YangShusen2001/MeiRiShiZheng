// 内容分发层（原生客户端内容通道）的构建产物断言。
//
// 目的：`public/content/**` 是鸿蒙端唯一的取数入口，字段错了客户端就白屏。
// 这里跑一次真实生成脚本（输出到临时目录），再对产物做结构与语义断言，
// 而不是只检查「脚本没抛异常」。
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import type {
  ContentArchiveIndex,
  ContentArchiveMonth,
  ContentManifest,
  PolicyLine,
  ReviewCard,
} from "@kaogong/contracts";
import { getArchive, listArchiveSummary, listArchiveTotals } from "../src/lib/archive";
import { listArchiveArticles, listArticles, listCards, listPolicyLines } from "../src/lib/content";

const SCRIPT = fileURLToPath(new URL("../scripts/build-content-api.mjs", import.meta.url));

/** 与 lib/content.ts 的 NAMED_ENTITIES 对齐：这些实体若残留，说明清洗没生效。 */
const ENTITY_PATTERN = /&(#x[0-9a-fA-F]+|#\d+|amp|lt|gt|quot|nbsp|emsp|ensp|thinsp|mdash|ndash|ldquo|rdquo|lsquo|rsquo|hellip);/g;

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf-8")) as T;
}

function allFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const p = join(dir, entry.name);
    return entry.isDirectory() ? allFiles(p) : [p];
  });
}

let outDir = "";
let manifest: ContentManifest;

beforeAll(() => {
  outDir = mkdtempSync(join(tmpdir(), "kaogong-content-api-"));
  execFileSync(process.execPath, [SCRIPT], {
    env: { ...process.env, KAOGONG_CONTENT_API_OUT: outDir },
    stdio: "pipe",
  });
  manifest = readJson<ContentManifest>(join(outDir, "manifest.json"));
}, 120_000);

afterAll(() => {
  if (outDir) rmSync(outDir, { recursive: true, force: true });
});

describe("内容分发层产物", () => {
  it("产出清单且字段齐备", () => {
    expect(manifest.latestDate).toBe(manifest.days[0]?.date ?? null);
    expect(manifest.days.length).toBeGreaterThan(0);
    for (const day of manifest.days) {
      expect(day.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Array.isArray(day.articles)).toBe(true);
      for (const article of day.articles) {
        expect(typeof article.id).toBe("string");
        expect(article.url).toMatch(/^https?:\/\//);
        expect(typeof article.aiStatus).toBe("string");
      }
      expect(typeof day.hasDigest).toBe("boolean");
      expect(typeof day.hasSummary).toBe("boolean");
      expect(typeof day.hasPractice).toBe("boolean");
      expect(typeof day.hasPicks).toBe("boolean");
    }
  });

  it("内容日按倒序排列（最新在前）", () => {
    const dates = manifest.days.map((d) => d.date);
    expect(dates).toEqual([...dates].sort().reverse());
  });

  it("文章集合与 Web 站 read/[id] 预渲染集合一致", () => {
    const webIds = listArticles().map((a) => a.id).sort();
    const manifestIds = manifest.days.flatMap((d) => d.articles.map((a) => a.id)).sort();
    expect(manifestIds).toEqual(webIds);
    for (const id of webIds) {
      expect(existsSync(join(outDir, "articles", `${id}.json`))).toBe(true);
    }
    // 清单里每条 id 都指向真实文件，客户端不会拿到 404
    for (const id of manifestIds) {
      expect(existsSync(join(outDir, "articles", `${id}.json`))).toBe(true);
    }
  });

  it("清单摘要里的原文链接可唯一反查文章 id（客户端首页跳转依赖这个映射）", () => {
    const byUrl = new Map<string, string>();
    for (const day of manifest.days) {
      for (const article of day.articles) {
        const seen = byUrl.get(article.url);
        if (seen !== undefined) {
          expect(seen).toBe(article.id);
        }
        byUrl.set(article.url, article.id);
      }
    }
    // 摘要字段与文章正文必须一致，否则首页链接会指向错误文章
    for (const day of manifest.days) {
      for (const article of day.articles) {
        const raw = readJson<{ title: string; url: string }>(join(outDir, "articles", `${article.id}.json`));
        expect(article.title).toBe(raw.title);
        expect(article.url).toBe(raw.url);
      }
    }
  });

  it("文章正文已按 Web 端同一逻辑清洗，无 HTML 实体残留", () => {
    for (const article of listArticles()) {
      const raw = readFileSync(join(outDir, "articles", `${article.id}.json`), "utf-8");
      expect(raw.match(ENTITY_PATTERN), `文章 ${article.id} 残留实体`).toBeNull();
    }
  });

  it("有 digest 的内容日必然带文章，反之亦然", () => {
    for (const day of manifest.days) {
      expect(day.articles.length > 0).toBe(day.hasDigest);
    }
  });

  it("逐日内容与跨日内容都按声明产出", () => {
    for (const day of manifest.days) {
      expect(existsSync(join(outDir, day.date, "digest.json"))).toBe(day.hasDigest);
      expect(existsSync(join(outDir, day.date, "summary.json"))).toBe(day.hasSummary);
      expect(existsSync(join(outDir, day.date, "practice.json"))).toBe(day.hasPractice);
      expect(existsSync(join(outDir, day.date, "picks.json"))).toBe(day.hasPicks);
    }
  });

  it("卡片与政策主线完整透出", () => {
    const cards = readJson<ReviewCard[]>(join(outDir, "cards.json"));
    const lines = readJson<PolicyLine[]>(join(outDir, "policy-lines.json"));
    expect(cards.map((c) => c.id)).toEqual(listCards().map((c) => c.id));
    expect(lines.map((l) => l.id)).toEqual(listPolicyLines().map((l) => l.id));
    expect(manifest.cardCount).toBe(cards.length);
    expect(manifest.policyLineCount).toBe(lines.length);
  });

  it("不把 .bak 备份等非发布文件带入产物", () => {
    const leaked = allFiles(outDir).filter((p) => p.endsWith(".bak"));
    expect(leaked).toEqual([]);
  });
});

/**
 * 政策档案通道（2026-09-15 新增）。
 *
 * 背景：Web 端的 `/policy/` 从 `content/archive/` 构建期读取，而分发层原先**完全没有档案**——
 * 鸿蒙端物理上取不到，三端在「政策档案」这一屏上是不通的。
 * 这组断言盯的是"客户端能不能真的把档案页渲染出来"，不是"文件写出来了"。
 */
describe("政策档案分发产物", () => {
  const index = () => readJson<ContentArchiveIndex>(join(outDir, "archive", "index.json"));

  it("产出索引，月份倒序且与逐月合计同源", () => {
    const idx = index();
    expect(idx.months.length).toBeGreaterThan(0);
    const months = idx.months.map((r) => r.month);
    expect(months).toEqual([...months].sort().reverse());
    expect(idx.totals.months).toBe(idx.months.length);
    expect(idx.totals.files).toBe(idx.months.reduce((n, r) => n + r.count, 0));
    expect(idx.totals.core).toBe(idx.months.reduce((n, r) => n + r.high, 0));
    expect(idx.totals.firstMonth).toBe(months[months.length - 1]);
    expect(idx.totals.lastMonth).toBe(months[0]);
    // 与 Web 端侧边栏读的是同一份数据源，不允许各算一套
    expect(idx.months).toEqual(listArchiveSummary());
    expect(idx.totals).toEqual(listArchiveTotals());
  });

  it("清单里的档案规模与索引一致（首页入口卡不额外发请求）", () => {
    const idx = index();
    expect(manifest.archive).toEqual({
      months: idx.totals.months,
      files: idx.totals.files,
      core: idx.totals.core,
    });
  });

  it("逐月台账存在，且计数与条目实际分布一致", () => {
    const idx = index();
    for (const row of idx.months) {
      const path = join(outDir, "archive", `${row.month}.json`);
      expect(existsSync(path), `${row.month} 缺台账文件`).toBe(true);
      const doc = readJson<ContentArchiveMonth>(path);
      expect(doc.month).toBe(row.month);
      const tally = {
        count: doc.items.length,
        high: doc.items.filter((i) => i.importance === "高").length,
        medium: doc.items.filter((i) => i.importance === "中").length,
        low: doc.items.filter((i) => i.importance === "低").length,
      };
      expect({ count: doc.count, high: doc.high, medium: doc.medium, low: doc.low }).toEqual(tally);
      expect({ count: row.count, high: row.high }).toEqual({ count: tally.count, high: tally.high });
      // 分级只有三档，出现第四种说明数据脏了（客户端会渲染出一个没有样式的标签）
      expect(tally.count).toBe(tally.high + tally.medium + tally.low);
      // 与 Web 端月份页拿到的 doc 完全一致
      expect(doc).toEqual(getArchive(row.month));
    }
  });

  it("每条档案条目的 readId 都指向真实正文文件（客户端点进去不会 404）", () => {
    const idx = index();
    let routable = 0;
    for (const row of idx.months) {
      const doc = readJson<ContentArchiveMonth>(join(outDir, "archive", `${row.month}.json`));
      for (const it of doc.items) {
        expect(it.url).toMatch(/^https?:\/\//);
        expect(it.title.length).toBeGreaterThan(0);
        expect(it.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        expect(it.importance === "高" || it.importance === "中" || it.importance === "低").toBe(true);
        // hasBody 与 readId 必须同进同退：一边为真另一边为空 = 要么被迫跳外链、要么点进 404
        expect(it.readId !== "").toBe(it.hasBody);
        if (it.readId !== "") {
          expect(existsSync(join(outDir, "articles", `${it.readId}.json`))).toBe(true);
          routable += 1;
        }
      }
      // url 是客户端反查与收藏的键，月内重复会让两条指向同一篇
      const urls = doc.items.map((i) => i.url);
      expect(new Set(urls).size).toBe(urls.length);
    }
    expect(routable).toBeGreaterThan(0);
  });

  it("档案正文与日更正文共用 id 空间但不冲突（撞 id 会静默丢内容）", () => {
    const dailyIds = new Set(listArticles().map((a) => a.id));
    const archiveIds = listArchiveArticles().map((a) => a.id);
    expect(archiveIds.filter((id) => dailyIds.has(id))).toEqual([]);
    expect(new Set(archiveIds).size).toBe(archiveIds.length);
    for (const id of archiveIds) {
      expect(existsSync(join(outDir, "articles", `${id}.json`))).toBe(true);
    }
  });

  it("档案正文同样按 Web 端逻辑清洗，无 HTML 实体残留", () => {
    for (const article of listArchiveArticles()) {
      const raw = readFileSync(join(outDir, "articles", `${article.id}.json`), "utf-8");
      expect(raw.match(ENTITY_PATTERN), `档案正文 ${article.id} 残留实体`).toBeNull();
    }
  });
});
