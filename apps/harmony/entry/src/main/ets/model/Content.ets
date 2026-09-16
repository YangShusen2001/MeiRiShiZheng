/**
 * 内容领域模型：与 `packages/contracts/src/content.ts` 一一对应。
 *
 * ⚠️ 契约纪律：
 * - **客户端消费的接口**（ContentManifest / ContentManifestDay / ContentManifestArticle /
 *   ContentArchiveScale / ContentArchiveItem / ContentArchiveMonth / ContentArchiveMonthRow /
 *   ContentArchiveTotals / ContentArchiveIndex / TodaySummary /
 *   DigestItem / DigestSection / DailyDigest / AiAnnotation）必须与 contracts **逐字段一致**，
 *   不得自行增删改。契约变更时先改 `packages/contracts`，再同步本文件。
 *   门禁：`apps/web/test/harmony-contract-parity.test.ts`。
 * - `ClippedArticle` 是 contracts 的**有意子集**：只声明客户端实际渲染所需字段
 *   （不声明 aiModel / aiPromptVersion / aiGeneratedAt / sourceTextHash / aiError /
 *   aiQuality / aiRelations / aiCards / policyLine / evergreen）。JSON 里的多余字段会被忽略。
 *   **政策档案正文也走这条形状** —— 分发层把档案正文与日更正文放在同一个 id 空间
 *   （`/content/articles/<id>.json`），所以这里不需要第二个接口。
 */

/** 清单里的一篇文章摘要：够渲染卡片，并能把日报条目的 sourceUrl 反查成文章 id。 */
export interface ContentManifestArticle {
  id: string;
  title: string;
  source: string;
  url: string;
  /** "ok" 表示该篇有可用的 AI 概括与标注；其余值客户端不得渲染 AI 内容。 */
  aiStatus: string;
}

/** 内容清单里的一天（构建产物，由 build-content-api.mjs 生成）。 */
export interface ContentManifestDay {
  date: string;
  articles: ContentManifestArticle[];
  hasDigest: boolean;
  hasSummary: boolean;
  hasPractice: boolean;
  hasPicks: boolean;
}

/** 内容分发清单：内容发现的唯一入口，避免客户端硬编码日期或文章 id。 */
export interface ContentManifest {
  generatedAt: string;
  latestDate: string | null;
  days: ContentManifestDay[];
  cardCount: number;
  policyLineCount: number;
  /** 政策档案规模：首页「政策档案」入口卡直接用它，不必再拉一次 archive/index.json。 */
  archive: ContentArchiveScale;
}

/** 政策档案规模（三个计数）。 */
export interface ContentArchiveScale {
  months: number;
  files: number;
  core: number;
}

/**
 * 政策档案台账里的一份文件。
 *
 * ⚠️ `importance` 在 contracts 里是字面量联合类型（"高" | "中" | "低"），
 * 这里**必须**是 `string` —— ArkTS 不支持字面量类型（迁移指南规则 `arkts-no-as-const`：
 * 「ArkTS 不支持 as const 断言和字面量类型」）。取值由 `ArchiveTier` 常量收口，
 * 不在页面里散落裸字符串。
 */
export interface ContentArchiveItem {
  url: string;
  title: string;
  date: string;
  lib: string;
  importance: string;
  topic: string;
  gist: string;
  /** 关键数字；2026-09-15 之前产出的档案没有该字段 → 条件渲染，不补空行。 */
  figures?: string;
  hasBody: boolean;
  /** 站内阅读页 id；空串 = 无正文，必须退到 `url` 官方外链。 */
  readId: string;
}

/** 一个月的政策档案台账。 */
export interface ContentArchiveMonth {
  month: string;
  count: number;
  high: number;
  medium: number;
  low: number;
  items: ContentArchiveItem[];
}

/** 月份摘要（索引里的一行）。`了解 · 细则` 份数 = count - high，不重复下发。 */
export interface ContentArchiveMonthRow {
  month: string;
  count: number;
  high: number;
}

/** 全馆合计（档案页页头统计）。 */
export interface ContentArchiveTotals {
  firstMonth: string;
  lastMonth: string;
  months: number;
  files: number;
  core: number;
}

/** 档案索引：进档案页先取它，再按需取某月。 */
export interface ContentArchiveIndex {
  generatedAt: string;
  /** 月份摘要，倒序（最新在前）。 */
  months: ContentArchiveMonthRow[];
  totals: ContentArchiveTotals;
}

/** 今日速览：一句话总结 + 关键词。 */
export interface TodaySummary {
  date: string;
  summary: string;
  keywords: string[];
}

/** 日报里的单条新闻。 */
export interface DigestItem {
  title: string;
  date: string;
  sourceUrl: string;
  summary?: string;
  quotes?: string[];
}

/** 日报的一个栏目。 */
export interface DigestSection {
  id: string;
  title: string;
  items: DigestItem[];
}

/** 一份每日日报。 */
export interface DailyDigest {
  date: string;
  title: string;
  sections: DigestSection[];
}

/** AI 只读标注；start/end 为段落内左闭右开字符偏移。 */
export interface AiAnnotation {
  id: string;
  paragraphIndex: number;
  start: number;
  end: number;
  text: string;
  /** viewpoint 观点 / exam_point 考点 / term 术语 / figure 数字指标。 */
  type: string;
  /** 仅 term 使用；生成失败时省略。 */
  explanation?: string;
}

/** 剪藏原文。 */
export interface ClippedArticle {
  id: string;
  date: string;
  title: string;
  source: string;
  url: string;
  pubDate: string;
  fetchedAt: string;
  status: string;
  paragraphs: string[];
  keySentences: string[];
  aiStatus?: string;
  aiSummary?: string;
  aiAnnotations?: AiAnnotation[];
}
