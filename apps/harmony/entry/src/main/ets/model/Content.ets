/**
 * 内容领域模型：与 `packages/contracts/src/content.ts` 一一对应。
 *
 * ⚠️ 契约纪律：字段名与可选性必须与 contracts 保持一致，不得在此另立字段。
 * 契约若变更，先改 `packages/contracts`，再同步本文件。
 */

/** 内容清单里的一天（构建产物，由 build-content-api.mjs 生成）。 */
export interface ContentManifestDay {
  date: string;
  articleIds: string[];
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
