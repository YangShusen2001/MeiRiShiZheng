// 内容加载器：构建时用 Node 直接读仓库根 content/ 目录。
// 类型来自 @kaogong/contracts（单一事实源），不在此重复定义——否则会漂移。
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { CardDeck, ClippedArticle, DailyDigest, DailyPicks, DailyReport, PolicyLine, PracticeSet, ReviewCard, TodaySummary } from "@kaogong/contracts";

export type {
  AiAnnotation,
  AiAnnotationType,
  AiRelation,
  AiRelationKind,
  AiRelationPoint,
  AiStatus,
  CardDeck,
  ClippedArticle,
  DailyDigest,
  DailyPicks,
  DailyReport,
  DigestItem,
  DigestSection,
  PicksSlots,
  PolicyLine,
  PracticeSet,
  Question,
  ReportCuration,
  ReviewCard,
  TodaySummary,
} from "@kaogong/contracts";

// 从 apps/web/src/lib/content.ts 上溯 4 层到仓库根，再进 content/
const CONTENT_DIR = fileURLToPath(new URL("../../../../content/", import.meta.url));

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  nbsp: " ",
  emsp: " ",
  ensp: " ",
  thinsp: " ",
  mdash: "—",
  ndash: "–",
  ldquo: "“",
  rdquo: "”",
  lsquo: "‘",
  rsquo: "’",
  hellip: "…",
};

/** 解码常见 HTML 实体并压空白，消化已入库正文里的 `&emsp;` / `&nbsp;`。 */
export function unescapeHtmlEntities(value: string): string {
  const decoded = value.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-zA-Z][a-zA-Z0-9]+);/g, (raw, body: string) => {
    if (body.startsWith("#")) {
      const code = body.startsWith("#x") || body.startsWith("#X")
        ? Number.parseInt(body.slice(2), 16)
        : Number.parseInt(body.slice(1), 10);
      if (!Number.isFinite(code) || code < 0 || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return raw;
      return String.fromCodePoint(code);
    }
    return NAMED_ENTITIES[body.toLowerCase()] ?? raw;
  });
  return decoded.replace(/[\u00a0\u2002\u2003\u2009\u3000]/g, " ").replace(/\s+/g, " ").trim();
}

/** 构建时清洗已入库文章，避免旧 JSON 仍带着字面量实体。 */
export function unescapeArticle(article: ClippedArticle): ClippedArticle {
  return {
    ...article,
    title: unescapeHtmlEntities(article.title),
    paragraphs: article.paragraphs.map(unescapeHtmlEntities),
    keySentences: article.keySentences.map(unescapeHtmlEntities),
  };
}

function loadJson<T>(p: string): T | null {
  if (!existsSync(p)) return null;
  return JSON.parse(readFileSync(p, "utf-8")) as T;
}

function loadArticle(p: string): ClippedArticle | null {
  const article = loadJson<ClippedArticle>(p);
  return article ? unescapeArticle(article) : null;
}

/** content/ 下有效的日期目录（YYYY-MM-DD），跳过文件（policy-lines.json 等）与非日期目录。 */
function dateDirs(): string[] {
  if (!existsSync(CONTENT_DIR)) return [];
  return readdirSync(CONTENT_DIR).filter(
    (entry) => /^\d{4}-\d{2}-\d{2}$/.test(entry) && statSync(join(CONTENT_DIR, entry)).isDirectory(),
  );
}

/** 全部内容日期，按倒序（最新在前）。内容分发清单据此生成。 */
export function listContentDates(): string[] {
  return dateDirs().sort().reverse();
}

/** 列出所有已生成的日报，按日期倒序。 */
export function listDigests(): DailyDigest[] {
  return dateDirs()
    .filter((d) => existsSync(join(CONTENT_DIR, d, "digest.json")))
    .sort()
    .reverse()
    .map((d) => loadJson<DailyDigest>(join(CONTENT_DIR, d, "digest.json"))!)
    .filter(Boolean);
}

/** 按日期取一份日报，不存在返回 null。 */
export function getDigest(date: string): DailyDigest | null {
  return loadJson<DailyDigest>(join(CONTENT_DIR, date, "digest.json"));
}

/** 取最近的「非空」日报（sections 非空），避免失败日的空日报成为首页“最新一期”。 */
export function latestNonEmptyDigest(digests: DailyDigest[]): DailyDigest | undefined {
  return digests.find((d) => d.sections.length > 0) ?? digests[0];
}

/** 列出所有每日一练题集，按日期倒序。 */
export function listPracticeSets(): PracticeSet[] {
  return dateDirs()
    .filter((d) => existsSync(join(CONTENT_DIR, d, "practice.json")))
    .sort()
    .reverse()
    .map((d) => loadJson<PracticeSet>(join(CONTENT_DIR, d, "practice.json"))!)
    .filter(Boolean);
}

/** 按日期取一份每日一练题集，不存在返回 null。 */
export function getPracticeSet(date: string): PracticeSet | null {
  return loadJson<PracticeSet>(join(CONTENT_DIR, date, "practice.json"));
}

/** 按日期取今日速览（一句话 + 关键词），不存在返回 null。 */
export function getSummary(date: string): TodaySummary | null {
  return loadJson<TodaySummary>(join(CONTENT_DIR, date, "summary.json"));
}

/** 按日期取选材定稿（精选 id 清单 + 槽位），不存在返回 null（sparse/失败日会缺）。 */
export function getPicks(date: string): DailyPicks | null {
  return loadJson<DailyPicks>(join(CONTENT_DIR, date, "picks.json"));
}

/**
 * 按日期取管道质量报告（content/_reports/<date>.json）。
 * 与 dateDirs() 不同源：报告存在独立的 _reports 目录，不随内容日走。
 */
export function getReport(date: string): DailyReport | null {
  return loadJson<DailyReport>(join(CONTENT_DIR, "_reports", `${date}.json`));
}

/** 按文章 id 取剪藏原文（全文），不存在返回 null。 */
export function getArticle(id: string): ClippedArticle | null {
  for (const d of dateDirs()) {
    const p = join(CONTENT_DIR, d, `article-${id}.json`);
    if (existsSync(p)) return loadArticle(p);
  }
  return null;
}

/** 列出所有剪藏原文。 */
export function listArticles(): ClippedArticle[] {
  const out: ClippedArticle[] = [];
  for (const d of dateDirs()) {
    for (const f of readdirSync(join(CONTENT_DIR, d))) {
      if (f.startsWith("article-") && f.endsWith(".json")) {
        const a = loadArticle(join(CONTENT_DIR, d, f));
        if (a) out.push(a);
      }
    }
  }
  return out;
}

/** 剥掉抓取残留的来源后缀（「…的通知_国务院部门文件」）。仅作清单缺失时的兜底。 */
function stripArchiveTitleSuffix(title: string): string {
  return title.replace(/_(国务院部门文件|国务院文件|中国政府网|国家发展改革委)$/, "").trim();
}

/**
 * 列出**政策档案正文**（`content/archive/<YYYY-MM>/article-*.json`）。
 *
 * 与 `listArticles()` 同构——政策正文的字段就是 `ClippedArticle` 的形状，
 * 所以它**直接走 `/read/<id>/` 阅读页**，不另建一套渲染。
 * 正文原先是 gitignore 的（"站点只用 gist、不渲染正文"），该前提已被
 * 「档案页的查看原文改指站内」推翻，2026-09-15 起入库。
 *
 * 两点以文件/清单为准，避免出现「点进去 404」或「标题变样」：
 * 1. **id 用文件名**——`/read/<id>/` 是按 `article-<id>.json` 解析的，
 *    万一内容里的 `id` 与文件名不一致，用内容值会让页面 404；
 * 2. **标题用清单**（同目录 archive.json，按 url 对齐）——正文标题带着
 *    抓取残留的来源后缀，清单里是策展后的干净标题；同一屏从档案页点进
 *    阅读页，标题不该变样。清单缺该 url 时才退回剥后缀。
 *
 * id 由 `scripts/fetch-archive.py` 生成 = `md5(url)[:10]`（确定性），
 * 与剪藏文章 id 实测零冲突（241 篇 ↔ 1137 篇，交集为空）。
 */
export function listArchiveArticles(): ClippedArticle[] {
  const archiveDir = join(CONTENT_DIR, "archive");
  if (!existsSync(archiveDir)) return [];
  const out: ClippedArticle[] = [];
  for (const month of readdirSync(archiveDir).filter((m) => /^\d{4}-\d{2}$/.test(m)).sort()) {
    const dir = join(archiveDir, month);
    if (!statSync(dir).isDirectory()) continue;
    const cleanTitle = new Map<string, string>();
    const monthDoc = loadJson<{ items?: Array<{ url: string; title: string }> }>(join(dir, "archive.json"));
    for (const it of monthDoc?.items ?? []) cleanTitle.set(it.url, it.title);

    for (const f of readdirSync(dir)) {
      if (!f.startsWith("article-") || !f.endsWith(".json")) continue;
      const a = loadArticle(join(dir, f));
      if (!a) continue;
      out.push({
        ...a,
        id: f.slice("article-".length, -".json".length),
        title: cleanTitle.get(a.url) ?? stripArchiveTitleSuffix(a.title),
      });
    }
  }
  return out;
}

/**
 * 列出所有考点卡片。
 *
 * **两个来源，缺一不可**：
 * 1. `content/cards/*.json`——人工策展的卡组（无出处）；
 * 2. **各日文章里的 `aiCards`**——管道从原文提炼，带 `anchor`（出处文章 + 段落）。
 *
 * 只读前者会让管道产出的卡片永远到不了端上；而 `anchor` 是"卡片能回到原文"
 * 的唯一来源，所以必须并入。按 id 去重（人工卡优先）。
 */
export function listCards(): ReviewCard[] {
  const deckCards = listDeckCards();
  const seen = new Set(deckCards.map((card) => card.id));
  const articleCards: ReviewCard[] = [];
  for (const entry of safeReaddir(CONTENT_DIR)) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(entry)) {
      continue;
    }
    for (const file of safeReaddir(join(CONTENT_DIR, entry))) {
      if (!file.startsWith("article-") || !file.endsWith(".json")) {
        continue;
      }
      const article = loadJson<ClippedArticle>(join(CONTENT_DIR, entry, file));
      // 渲染门控：AI 未成功的文章，其卡片同样不可用（与端上一致）
      if (!article || article.aiStatus !== "ok") {
        continue;
      }
      for (const card of article.aiCards ?? []) {
        if (seen.has(card.id)) {
          continue;
        }
        seen.add(card.id);
        articleCards.push(card);
      }
    }
  }
  return [...deckCards, ...articleCards];
}

/** 人工策展卡组（content/cards/*.json，按文件名排序后拼接）。 */
function listDeckCards(): ReviewCard[] {
  const cardsDir = join(CONTENT_DIR, "cards");
  if (!existsSync(cardsDir)) return [];
  return readdirSync(cardsDir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .flatMap((f) => loadJson<CardDeck>(join(cardsDir, f))?.cards ?? []);
}

/** 目录读不到时返回空数组（内容目录在不同环境下形态不一致，不该让构建炸掉）。 */
function safeReaddir(dir: string): string[] {
  try {
    return readdirSync(dir);
  } catch {
    return [];
  }
}

/** 列出全部政策主线（content/policy-lines.json，人工维护；文件缺失返回 []）。 */
export function listPolicyLines(): PolicyLine[] {
  return loadJson<{ lines: PolicyLine[] }>(join(CONTENT_DIR, "policy-lines.json"))?.lines ?? [];
}
