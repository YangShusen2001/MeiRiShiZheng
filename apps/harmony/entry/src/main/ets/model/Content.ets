/**
 * 内容领域模型：与 `packages/contracts/src/content.ts` 一一对应。
 *
 * ⚠️ 契约纪律：
 * - **客户端消费的接口**（ContentManifest / ContentManifestDay / TodaySummary /
 *   DigestItem / DigestSection / DailyDigest / AiAnnotation）必须与 contracts **逐字段一致**，
 *   不得自行增删改。契约变更时先改 `packages/contracts`，再同步本文件。
 * - `ClippedArticle` 是 contracts 的**有意子集**：只声明客户端实际渲染所需字段
 *   （不声明 aiModel / aiPromptVersion / aiGeneratedAt / sourceTextHash / aiError /
 *   aiQuality / aiRelations / aiCards / policyLine / evergreen）。JSON 里的多余字段会被忽略。
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
