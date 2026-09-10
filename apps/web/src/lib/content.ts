// 内容加载器：构建时用 Node 直接读仓库根 content/ 目录。
// 类型来自 @kaogong/contracts（单一事实源），不在此重复定义——否则会漂移。
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { CardDeck, ClippedArticle, DailyDigest, PolicyLine, PracticeSet, ReviewCard, TodaySummary } from "@kaogong/contracts";

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
  DigestItem,
  DigestSection,
  PolicyLine,
  PracticeSet,
  Question,
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

/** 列出所有考点卡片（content/cards/*.json，按文件名排序后拼接）。 */
export function listCards(): ReviewCard[] {
  const cardsDir = join(CONTENT_DIR, "cards");
  if (!existsSync(cardsDir)) return [];
  return readdirSync(cardsDir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .flatMap((f) => loadJson<CardDeck>(join(cardsDir, f))?.cards ?? []);
}

/** 列出全部政策主线（content/policy-lines.json，人工维护；文件缺失返回 []）。 */
export function listPolicyLines(): PolicyLine[] {
  return loadJson<{ lines: PolicyLine[] }>(join(CONTENT_DIR, "policy-lines.json"))?.lines ?? [];
}
