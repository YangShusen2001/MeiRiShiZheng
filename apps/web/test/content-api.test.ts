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
import type { ContentManifest, ReviewCard, PolicyLine } from "@kaogong/contracts";
import { listArticles, listCards, listPolicyLines } from "../src/lib/content";

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
