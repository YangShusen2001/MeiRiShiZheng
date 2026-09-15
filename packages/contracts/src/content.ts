// 内容契约：Python 管道产出 → Astro 消费的领域模型。
// 字段名与结构对照原项目真实数据（data/每日材料/*.md、data/原文/*/*.json）提炼，
// 是“管道”与“前端”之间唯一的接口定义。
//
// ⚠️ 跨语言权威契约是 content/schema/*.json（JSON Schema）：
// Python 管道据此校验产出（pipeline/tests/test_content_schema.py）。
// 本文件的 TS 类型必须与其保持字段一致；后续会用“从 JSON Schema 生成 TS 类型”
// 或“一致性测试”消除手工同步（见 ADR 0001）。

export type AiStatus = "pending" | "ok" | "error";

/** 标注类型：viewpoint 观点 / exam_point 考点 / term 术语 / figure 数字指标（原文高亮，不生成卡片）。 */
export type AiAnnotationType = "viewpoint" | "exam_point" | "term" | "figure";

/** 关系簇类型：中心句与支撑点的关系（决策 0022 §5.1）。 */
export type AiRelationKind = "support" | "explain" | "example" | "contrast";

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

/** 关系标注（中心句→支撑点，即「箭头」）里的一个支撑点，引用已校验的标注 id。 */
export interface AiRelationPoint {
  annotationId: string;
  kind: AiRelationKind;
}

/**
 * 关系标注（中心句→支撑点）：AI 生成初稿，人工可修正。
 * 程序校验引用有效、不跨段、数量上限；跨字段校验在 Python 语义层（validate_article_ai）。
 */
export interface AiRelation {
  id: string;
  paragraphIndex: number;
  /** 中心句：引用同文章 aiAnnotations[].id。 */
  anchor: string;
  points: AiRelationPoint[];
  kind: AiRelationKind;
  /** 是否 AI 生成初稿。 */
  aiGenerated: boolean;
  /** 人工修正时间；晚于文章 aiGeneratedAt 时管道重跑不得覆盖（locked）。 */
  editedAt?: string;
  /** 人工修正者标识。 */
  editedBy?: string;
}

/** 活跃政策主线（人工维护，对应 content/policy-lines.json）。 */
export interface PolicyLine {
  /** 主线 slug，被文章/卡片的 policyLine 引用。 */
  id: string;
  name: string;
  status: "active" | "retiring" | "archived";
  window: { start: string; end?: string | null };
  /** 人工退休参考信号，仅提示不自动生效。 */
  retireHint?: string;
}

/** content/policy-lines.json 文件形状。 */
export interface PolicyLinesFile {
  lines: PolicyLine[];
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
  /** 关系标注（箭头）：AI 生成初稿，人工可修正；引用 aiAnnotations[].id。 */
  aiRelations?: AiRelation[];
  /** AI 提炼的考点卡片（待人工确认后发布；与 content/cards 的 ReviewCard 同构）。 */
  aiCards?: ReviewCard[];
  /** 归属的活跃主线 slug（policy-lines.json 的 id）；无归属省略。 */
  policyLine?: string;
  /** 是否可长期作为「补剧」素材（历史文章重提）；默认 false。 */
  evergreen?: boolean;
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
  /**
   * 一句话提示（指向材料依据或关键区分点，**不直接给出答案**）。
   *
   * 对应画布 3:608「查看提示」按钮展开的内容。可选：未生成时端上退回 `topic`
   * （如「本题考点：民族宗教」），不编造提示。
   */
  hint?: string;
  /**
   * 4 个选项各自的「典型误因」短标签，与 `options` 同下标；**正确项固定为空串**。
   *
   * 对应画布 3:617 错题行右侧的「错因：漏读题干」—— 端上取 `traps[chosen]`。
   * 画布上错题行只有一段文本、没有任何交互控件，所以这**不是**用户自己填的标注，
   * 而是题目侧预生成的「选这个选项的人通常错在哪」；运行期不做 AI 推断
   * （pipeline 是唯一 AI 入口，用户作答数据不出域）。
   *
   * 可选：未生成时端上退回「你的 X → 正确 Y」（真实有的信息），不编造错因。
   */
  traps?: string[];
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

/** 选材槽位（picks.schema.json 的 slots）。 */
export interface PicksSlots {
  /** 头版要闻（可脱离主线池）。 */
  headline: string | null;
  /** 申论精读 ≤2。 */
  essay: string[];
  /** 考点提炼。 */
  exam: string | null;
  /** 多样性补充。 */
  extra: string | null;
  /** 历史补剧（v2.1 §7.1 起不再写入，键保留兼容历史产物）。 */
  supplement?: string[];
  /** 宁缺勿滥标记：picked<2 时为 true，当日为合法 sparse 日。 */
  sparse?: boolean;
}

/** 每日选材定稿（content/<date>/picks.json，见 ADR 0008）。 */
export interface DailyPicks {
  /** YYYY-MM-DD。 */
  date: string;
  slots: PicksSlots;
  /** 最终精选 1-5 篇（picked=0 不落盘），顺序即头版优先。 */
  picked: string[];
  /** 文章 id → 主线归属（AI 评级结果；null=无归属）。 */
  assignments: Record<string, string | null>;
  /** 待人工审核名单（不进槽位）。 */
  needsHuman?: string[];
}

/** 每日管道质量报告里的选材段（content/_reports/<date>.json 的 curation）。 */
export interface ReportCuration {
  candidates: number;
  coarseKept: number;
  /** 最终入选篇数——首页「精选 N 篇」用它，与 picks.picked 长度一致。 */
  picked: number;
  slots?: Partial<Omit<PicksSlots, "essay">> & { essay?: string[] };
  needsHuman?: string[];
  cardsProduced?: number;
  relationsProduced?: number;
  /** 当日是否落盘 picks.json（false 即 curationErrors 含 picks_missing）。 */
  picksWritten?: boolean;
}

/**
 * 每日管道质量报告（content/_reports/<date>.json）。
 * 是「这天到底跑了什么」的唯一权威记录：抓取源数、候选数、密度/配额淘汰、选材结果。
 * 首页 Hero 的「N 源已检 · 精选 M 篇」直接取自 sourcesOk 与 curation.picked。
 */
export interface DailyReport {
  date: string;
  /** 抓取成功的源数。 */
  sourcesOk: number;
  sourceErrors?: { source?: string; reason?: string }[];
  /** 剪藏前候选篇数。 */
  candidates: number;
  /** 剪藏成功篇数。 */
  articles: number;
  aiOk: number;
  aiError: number;
  /** ok / sparse / degraded / failed，优先级 failed > degraded > sparse > ok。 */
  qualityStatus?: string;
  curation?: ReportCuration;
  curationErrors?: string[];
  fetch?: { candidatesRaw?: number };
  clip?: { clipped?: number };
}

/** 卡片↔精读锚定：卡片来源于哪篇文章哪一段（0022 阶段 2）。 */
export interface CardAnchor {
  /** 出处文章 id。 */
  articleId: string;
  /** 出处段落下标。 */
  paragraphIndex: number;
  /** 出处句子（跨段定位出错时的兜底文本）。 */
  sentence?: string;
}

/** 一张考点卡片（策展静态内容，一问一答，对应 content/cards/*.json）。 */
export interface ReviewCard {
  /** 全局唯一卡片 id。 */
  id: string;
  /** 正面问题（主动回忆）。 */
  question: string;
  /** 反面答案。 */
  answer: string;
  /**
   * 思路/逐项解析（可选）。
   * 只给对错等于白刷——答错时必须能知道为什么错，所以这是卡片的正式字段。
   */
  explain?: string;
  /** 标签，如 定位/目标/数字。 */
  tags: string[];
  /** 归属的主线 slug；缺省继承卡组 policyLine。 */
  policyLine?: string;
  /** 所属考点（结构化考点库阶段 2）。 */
  examPointId?: string;
  /** 卡片↔精读锚定。 */
  anchor?: CardAnchor;
}

/** 一组考点卡片。 */
export interface CardDeck {
  /** 卡组所属政策/文件，如「十五五规划建议」。 */
  policy: string;
  /** 整组卡归属的主线 slug；card 级 policyLine 可覆盖。 */
  policyLine?: string;
  cards: ReviewCard[];
}

/** 清单里的一篇文章摘要：足够客户端渲染卡片与反查定位，无需再逐篇拉取全文。 */
export interface ContentManifestArticle {
  id: string;
  title: string;
  source: string;
  /** 官方原文链接。日报条目的 `sourceUrl` 用它反查文章 id（与 Web 端 clipMap 同源逻辑）。 */
  url: string;
  /** "ok" 表示该篇有可用的 AI 概括与标注；其余值客户端不得渲染 AI 内容。 */
  aiStatus: string;
}

/**
 * 内容清单里的一天（原生客户端据此发现「哪天有哪些内容」，无需猜测 URL）。
 * 由 `apps/web/scripts/build-content-api.mjs` 生成。
 */
export interface ContentManifestDay {
  /** "2026-08-19"。 */
  date: string;
  /** 该日全部剪藏原文（已在 Web 站预渲染，与 `/read/{id}` 集合一致）。 */
  articles: ContentManifestArticle[];
  hasDigest: boolean;
  hasSummary: boolean;
  hasPractice: boolean;
  /** 是否有策展槽位产物 picks.json（见 ADR 0008）。 */
  hasPicks: boolean;
}

/**
 * 内容分发清单：原生客户端启动时先取它，再按需取具体内容。
 * 是「内容发现」的唯一入口，避免客户端硬编码日期或文章 id。
 */
export interface ContentManifest {
  /** 生成时间，ISO8601。 */
  generatedAt: string;
  /** 最新内容日期（`days[0].date`）；无任何内容时为 null。 */
  latestDate: string | null;
  /** 全部内容日，按日期倒序（最新在前）。 */
  days: ContentManifestDay[];
  /** 考点卡片总数。 */
  cardCount: number;
  /** 活跃政策主线总数。 */
  policyLineCount: number;
}
