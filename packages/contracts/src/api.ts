// API 契约：apps/web（前端）↔ apps/api（Worker）之间的 HTTP 接口约定。
//
// 用 zod 作为「单一事实源」：TS 类型从 schema 推导（z.infer），
// Worker 侧用同一个 schema 做运行时校验——类型与校验永不漂移。
import { z } from "zod";

// —— 统一响应外壳 ——
export const apiErrorSchema = z.object({
  /** 机器可读错误码，如 "DEVICE_REQUIRED" / "INVALID_INPUT"。 */
  code: z.string(),
  /** 给人看的提示。 */
  message: z.string(),
});
export type ApiError = z.infer<typeof apiErrorSchema>;

// —— 收藏 ——
export const favoriteKindSchema = z.enum(["article", "quote", "term"]);
export type FavoriteKind = z.infer<typeof favoriteKindSchema>;

export const favoriteSchema = z.object({
  id: z.string(),
  url: z.string(),
  title: z.string(),
  source: z.string(),
  note: z.string(),
  /** 收藏类型：article=整篇文章，quote=金句（存选中文本），term=AI 术语（存术语+释义）。 */
  kind: favoriteKindSchema,
  /** 金句文本，仅 kind=quote 使用；其余恒为空串。 */
  quote: z.string(),
  /** 术语文本，仅 kind=term 使用；其余恒为空串。 */
  termText: z.string(),
  /** 术语 AI 释义，仅 kind=term 使用。 */
  termExplanation: z.string(),
  /** 来源文章阅读页 id（kind=term 跳转用；无剪藏时为空串）。 */
  articleId: z.string(),
  createdAt: z.number(), // unix 毫秒
});
export type Favorite = z.infer<typeof favoriteSchema>;

export const favoriteCreateSchema = z.object({
  url: z.string().min(1).regex(/^https?:\/\//i, "url 必须以 http(s):// 开头"),
  title: z.string().min(1),
  source: z.string().optional(),
  note: z.string().optional(),
  kind: favoriteKindSchema.default("article"),
  quote: z.string().max(1000).default(""),
  termText: z.string().max(200).default(""),
  termExplanation: z.string().max(2000).default(""),
  articleId: z.string().max(40).default(""),
});
export type FavoriteCreate = z.input<typeof favoriteCreateSchema>;

// —— 划线 ——
export const highlightStyleSchema = z.enum(["yellow", "green", "underline", "bold"]);
export type HighlightStyle = z.infer<typeof highlightStyleSchema>;

export const highlightSchema = z.object({
  id: z.string(),
  articleId: z.string(),
  text: z.string(),
  note: z.string(),
  /** 叠加样式（可同时是荧光笔 + 下划线）。 */
  styles: z.array(highlightStyleSchema).min(1),
  /** 所属段落序号（对应文章的 paragraphs 下标）。 */
  paragraphIndex: z.number().int().min(0),
  /** 段落内起始字符偏移（含）。 */
  start: z.number().int().min(0),
  /** 段落内结束字符偏移（不含），必须大于 start。 */
  end: z.number().int().min(1),
  /** AI 解释（用户触发的解释，独立于 note），可选。 */
  explanation: z.string().optional(),
  createdAt: z.number(), // unix 毫秒
});
export type Highlight = z.infer<typeof highlightSchema>;

export const highlightSpanSchema = z.object({
  text: z.string().min(1).max(1000),
  note: z.string().max(2000).default(""),
  /** AI 解释（用户触发），独立于 note；缺省为空串。 */
  explanation: z.string().max(2000).default(""),
  styles: z.array(highlightStyleSchema).min(1).max(3),
  start: z.number().int().min(0),
  end: z.number().int().min(1),
}).refine((v) => v.start < v.end, { message: "划线区间无效（start 必须小于 end）" });
export type HighlightSpan = z.infer<typeof highlightSpanSchema>;

export const highlightParagraphReplaceSchema = z.object({
  articleId: z.string().min(1),
  paragraphIndex: z.number().int().min(0),
  baseVersion: z.number().int().min(0),
  spans: z.array(highlightSpanSchema).max(100),
});
export type HighlightParagraphReplace = z.infer<typeof highlightParagraphReplaceSchema>;

export const highlightParagraphResponseSchema = z.object({
  version: z.number().int().min(0),
  highlights: z.array(highlightSchema),
});
export type HighlightParagraphResponse = z.infer<typeof highlightParagraphResponseSchema>;

export const highlightParagraphListItemSchema = highlightParagraphResponseSchema.extend({
  paragraphIndex: z.number().int().min(0),
});
export type HighlightParagraphListItem = z.infer<typeof highlightParagraphListItemSchema>;

// —— 每日一练 ——
export const practiceRecordSchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/), // "YYYY-MM-DD"
  correct: z.number().int().min(0),
  total: z.number().int().min(1),
});
export type PracticeRecord = z.infer<typeof practiceRecordSchema>;

// —— 错题本 ——
export const wrongQuestionSchema = z.object({
  id: z.string(),
  date: z.string(),
  question: z.string(),
  options: z.array(z.string()),
  answer: z.number().int().min(0).max(3),
  chosen: z.number().int().min(0).max(3),
  analysis: z.string(),
});
export type WrongQuestion = z.infer<typeof wrongQuestionSchema>;

export const wrongQuestionInputSchema = z.object({
  question: z.string().min(1).max(500),
  options: z.array(z.string()).length(4),
  answer: z.number().int().min(0).max(3),
  chosen: z.number().int().min(0).max(3),
  analysis: z.string().max(500),
});
export type WrongQuestionInput = z.infer<typeof wrongQuestionInputSchema>;

/** 每日一练提交体：成绩 + 答错题（供错题本）。 */
export const practiceSubmitSchema = practiceRecordSchema.extend({
  wrong: z.array(wrongQuestionInputSchema).max(200).default([]),
});
export type PracticeSubmit = z.input<typeof practiceSubmitSchema>;

// —— 划线 AI 解释 ——
export const explainRequestSchema = z.object({
  text: z.string().min(1).max(500),
});
export type ExplainRequest = z.infer<typeof explainRequestSchema>;

export const explainResponseSchema = z.object({
  explanation: z.string(),
});
export type ExplainResponse = z.infer<typeof explainResponseSchema>;

// —— 术语追问（收藏页「术语解析」）——
export const termAskRequestSchema = z.object({
  term: z.string().trim().min(1).max(100),
  explanation: z.string().max(1000).optional().default(""),
  /** 用户自定义追问；缺省时只生成建议问题。 */
  question: z.string().trim().max(500).optional(),
});
export type TermAskRequest = z.input<typeof termAskRequestSchema>;

export const termAskResponseSchema = z.object({
  /** 按考点生成的建议问题（无 question 时返回，最多 3 条）。 */
  suggestions: z.array(z.string().min(1)).max(3).default([]),
  /** 用户追问的回答（Markdown）。 */
  answer: z.string().optional(),
});
export type TermAskResponse = z.infer<typeof termAskResponseSchema>;

// —— QQ 邮箱验证码鉴权 ——
export const qqEmailSchema = z.string().trim().toLowerCase()
  .regex(/^[1-9][0-9]{4,10}@qq\.com$/, "请输入有效的 QQ 邮箱");
export const emailCodeRequestSchema = z.object({ email: qqEmailSchema });
export type EmailCodeRequest = z.infer<typeof emailCodeRequestSchema>;
export const emailCodeVerifySchema = z.object({
  email: qqEmailSchema,
  code: z.string().regex(/^\d{6}$/, "验证码必须为 6 位数字"),
});
export type EmailCodeVerify = z.infer<typeof emailCodeVerifySchema>;

export const authUserSchema = z.object({
  id: z.string(),
  email: qqEmailSchema,
});
export type AuthUser = z.infer<typeof authUserSchema>;

export const authResponseSchema = z.object({
  user: authUserSchema,
});
export type AuthResponse = z.infer<typeof authResponseSchema>;

// —— 个人资料 ——
export const profileSchema = z.object({
  name: z.string(),
  email: qqEmailSchema,
  avatar: z.string(),
  subscribed: z.boolean(),
});
export type Profile = z.infer<typeof profileSchema>;

export const profileUpdateSchema = z.object({
  name: z.string().max(32).optional(),
  avatar: z.string().min(1).max(8).optional(),
});
export type ProfileUpdate = z.infer<typeof profileUpdateSchema>;

export const subscriptionSchema = z.object({ subscribed: z.boolean() });
export type Subscription = z.infer<typeof subscriptionSchema>;

export const subscriptionResponseSchema = z.object({
  subscribed: z.boolean(),
  deliveryAvailable: z.boolean(),
  suppressionReason: z.string().nullable(),
});
export type SubscriptionResponse = z.infer<typeof subscriptionResponseSchema>;

// —— AI 解释邀请码 ——
// 共享码：一个码有多条激活记录（owner = user:<id> 或 device:<id>），剩余次数为全局共享额度。
export const inviteActivateSchema = z.object({
  code: z.string().trim().min(1).max(64),
});
export type InviteActivate = z.input<typeof inviteActivateSchema>;

export const inviteStatusSchema = z.object({
  active: z.boolean(),
  remaining: z.number().int().min(0),
  /** 已激活的邀请码原文（未激活时为空串）。 */
  code: z.string(),
});
export type InviteStatus = z.infer<typeof inviteStatusSchema>;

export const adminInviteCodeSchema = z.object({
  code: z.string(),
  total: z.number().int().min(0),
  remaining: z.number().int().min(0),
  createdAt: z.number(),
});
export type AdminInviteCode = z.infer<typeof adminInviteCodeSchema>;

// —— 考点卡片复习（间隔重复）——
/** 4 档自评 → ts-fsrs Rating：again=1, hard=2, good=3, easy=4。 */
export const reviewRatingSchema = z.enum(["again", "hard", "good", "easy"]);
export type ReviewRating = z.infer<typeof reviewRatingSchema>;

/** 单张卡的复习状态（GET /api/review/state 返回）。 */
export const reviewCardStateSchema = z.object({
  cardId: z.string(),
  /** 下次到期时间，unix 毫秒。 */
  dueAt: z.number(),
  reviewCount: z.number().int().min(0),
  lastReviewAt: z.number().nullable(),
});
export type ReviewCardState = z.infer<typeof reviewCardStateSchema>;

export const reviewStateResponseSchema = z.object({
  cards: z.array(reviewCardStateSchema),
});
export type ReviewStateResponse = z.infer<typeof reviewStateResponseSchema>;

/** 提交一张卡的自评。 */
export const reviewGradeSchema = z.object({
  cardId: z.string().min(1).max(64),
  rating: reviewRatingSchema,
});
export type ReviewGrade = z.input<typeof reviewGradeSchema>;

export const reviewGradeResponseSchema = z.object({
  dueAt: z.number(),
  reviewCount: z.number().int().min(0),
});
export type ReviewGradeResponse = z.infer<typeof reviewGradeResponseSchema>;
