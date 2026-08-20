// 内容契约：Python 管道产出 → Astro 消费的领域模型。
// 字段名与结构对照原项目真实数据（data/每日材料/*.md、data/原文/*/*.json）提炼，
// 是“管道”与“前端”之间唯一的接口定义。
//
// ⚠️ 跨语言权威契约是 content/schema/*.json（JSON Schema）：
// Python 管道据此校验产出（pipeline/tests/test_content_schema.py）。
// 本文件的 TS 类型必须与其保持字段一致；后续会用“从 JSON Schema 生成 TS 类型”
// 或“一致性测试”消除手工同步（见 ADR 0001）。

export type AiStatus = "pending" | "ok" | "error";

export type AiAnnotationType = "viewpoint" | "exam_point" | "term";

/** AI 在一段原文中的只读标注；start/end 为段落内左闭右开字符偏移。 */
export interface AiAnnotation {
  id: string;
  paragraphIndex: number;
  start: number;
  end: number;
  text: string;
  type: AiAnnotationType;
  /** 仅 term 使用，目标 30-80 个中文字符；生成失败时省略。 */
  explanation?: string;
}

/** 剪藏原文（对应原 data/原文/{date}/*.json）。 */
export interface ClippedArticle {
  /** 原文短 id，如 "14588442ca"。 */
  id: string;
  /** 所属日期，ISO 字符串 "2026-08-12"。 */
  date: string;
  title: string;
  /** 来源，如 "南方网"。 */
  source: string;
  /** 原文链接。 */
  url: string;
  /** 原文发布日期，可能为空字符串。 */
  pubDate: string;
  /** 抓取时间，ISO8601。 */
  fetchedAt: string;
  status: "ok" | "error";
  /** 正文段落。 */
  paragraphs: string[];
  /** 金句摘录。 */
  keySentences: string[];
  /** 历史内容可缺少；新 Pipeline 产物必须明确写入处理状态。 */
  aiStatus?: AiStatus;
  /** 首页概括目标 80-120 字，发布允许范围 60-150 字。 */
  aiSummary?: string;
  /** AI 只读标注，不得写入用户 highlights 数据。 */
  aiAnnotations?: AiAnnotation[];
  aiModel?: string;
  aiPromptVersion?: string;
  aiGeneratedAt?: string;
  /** paragraphs 规范化文本的 SHA-256 十六进制值。 */
  sourceTextHash?: string;
  /** aiStatus=error 时必填，最多 500 字符。 */
  aiError?: string;
  aiQuality?: { locationErrors: number };
}

/** 日报里的单条新闻。 */
export interface DigestItem {
  /** 条目标题。 */
  title: string;
  /** 日期短写，如 "08-12"。 */
  date: string;
  /** 原文链接。 */
  sourceUrl: string;
  /** 摘要（可选，政策解读/地区/南方时评等栏目有）。 */
  summary?: string;
  /** 金句摘录（可选）。 */
  quotes?: string[];
}

/** 日报的一个栏目，如 "全国时政要闻" / "申论精读"。 */
export interface DigestSection {
  /** 栏目 slug，如 "national" / "essay"。 */
  id: string;
  /** 栏目名。 */
  title: string;
  items: DigestItem[];
}

/** 一份每日日报（对应原 data/每日材料/{date}.md）。 */
export interface DailyDigest {
  /** "2026-08-12"。 */
  date: string;
  /** "每日日报 · 2026-08-12（周三）"。 */
  title: string;
  sections: DigestSection[];
}

/** 每日一练里的一道 4 选 1 客观题（管道产出 → 前端消费）。 */
export interface Question {
  id: string;
  /** 题干。 */
  q: string;
  /** 恰好 4 个选项。 */
  options: string[];
  /** 正确选项下标 0-3。 */
  answer: number;
  /** 解析（说明材料依据）。 */
  analysis: string;
  /** 主题词，如 "健康中国" / "科技" / "民生"。 */
  topic: string;
}

/** 一天的每日一练题集。 */
export interface PracticeSet {
  date: string;
  total: number;
  /** 题目来源（如 "2026-08-12.md"），与 practice.schema.json 的 source 字段对齐。 */
  source?: string;
  questions: Question[];
}

/** 今日速览：一句话总结 + 关键词（供首页横幅/海报）。 */
export interface TodaySummary {
  date: string;
  summary: string;
  keywords: string[];
}

/** 一张考点卡片（策展静态内容，一问一答，对应 content/cards/*.json）。 */
export interface ReviewCard {
  /** 全局唯一卡片 id。 */
  id: string;
  /** 正面问题（主动回忆）。 */
  question: string;
  /** 反面答案。 */
  answer: string;
  /** 标签，如 定位/目标/数字。 */
  tags: string[];
}

/** 一组考点卡片。 */
export interface CardDeck {
  /** 卡组所属政策/文件，如「十五五规划建议」。 */
  policy: string;
  cards: ReviewCard[];
}
