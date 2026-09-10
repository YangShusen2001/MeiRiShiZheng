import { describe, expect, it } from "vitest";
import { latestNonEmptyDigest, listPolicyLines, unescapeArticle, unescapeHtmlEntities } from "./content";
import type { ClippedArticle, DailyDigest } from "@kaogong/contracts";

function article(partial: Partial<ClippedArticle> = {}): ClippedArticle {
  return {
    id: "abc123",
    date: "2026-08-13",
    title: "标题",
    source: "人民网",
    url: "https://example.com/n1",
    pubDate: "2026-08-13",
    fetchedAt: "2026-08-13T00:00:00+00:00",
    status: "ok",
    paragraphs: [],
    keySentences: [],
    ...partial,
  };
}

describe("unescapeHtmlEntities", () => {
  it("解码段首缩进实体并去掉它们", () => {
    expect(unescapeHtmlEntities("&emsp;&emsp;正文第一段")).toBe("正文第一段");
  });

  it("解码不换行空格和中文引号实体", () => {
    expect(unescapeHtmlEntities("记者&nbsp;说&ldquo;好&rdquo;")).toBe("记者 说“好”");
  });

  it("解码数字实体", () => {
    expect(unescapeHtmlEntities("&#160;甲&#x2014;乙")).toBe("甲—乙");
  });
});

describe("unescapeArticle", () => {
  it("解码标题、段落和金句里的 HTML 实体", () => {
    const cleaned = unescapeArticle(article({
      title: "网传&ldquo;名单&rdquo;",
      paragraphs: ["&emsp;&emsp;第一段&nbsp;正文"],
      keySentences: ["&ldquo;金句&rdquo;"],
    }));
    expect(cleaned.title).toBe("网传“名单”");
    expect(cleaned.paragraphs).toEqual(["第一段 正文"]);
    expect(cleaned.keySentences).toEqual(["“金句”"]);
    expect(cleaned.url).toBe("https://example.com/n1");
  });
});

describe("latestNonEmptyDigest", () => {
  const digest = (date: string, sectionCount: number): DailyDigest => ({
    date,
    title: `日报 ${date}`,
    sections: Array.from({ length: sectionCount }, (_, i) => ({
      id: `s${i}`,
      title: `栏目${i}`,
      items: [],
    })),
  });

  it("跳过最新的空日报，回退到最近的非空日报", () => {
    const digests = [digest("2026-08-16", 0), digest("2026-08-15", 2), digest("2026-08-14", 3)];
    expect(latestNonEmptyDigest(digests)?.date).toBe("2026-08-15");
  });

  it("全部为空时回退到第一个，空列表返回 undefined", () => {
    expect(latestNonEmptyDigest([digest("2026-08-16", 0)])?.date).toBe("2026-08-16");
    expect(latestNonEmptyDigest([])).toBeUndefined();
  });
});

describe("listPolicyLines", () => {
  it("读取 content/policy-lines.json 并返回全部主线（含激活状态与窗口）", () => {
    const lines = listPolicyLines();
    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) {
      expect(line.id).toMatch(/^[a-z0-9-]+$/);
      expect(["active", "retiring", "archived"]).toContain(line.status);
      expect(line.window.start).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    }
  });
});
