// 数据库 schema（唯一权威）：收藏 / 划线 / 每日一练 / 用户。
// owner_id 使用 user:<id> / device:<id> 域前缀隔离登录用户和匿名设备数据。
import { sql } from "drizzle-orm";
import { index, integer, primaryKey, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const favorites = sqliteTable("favorites", {
  id: text("id").primaryKey(),
  ownerId: text("owner_id").notNull(),
  url: text("url").notNull(),
  title: text("title").notNull(),
  source: text("source").notNull().default(""),
  note: text("note").notNull().default(""),
  kind: text("kind").notNull().default("article"),
  quote: text("quote").notNull().default(""),
  termText: text("term_text").notNull().default(""),       // 术语收藏：术语文本
  termExplanation: text("term_explanation").notNull().default(""), // 术语收藏：AI 释义
  articleId: text("article_id").notNull().default(""),     // 术语收藏：来源文章阅读页 id
  createdAt: integer("created_at").notNull(), // unix 毫秒
});

export const highlights = sqliteTable("highlights", {
  id: text("id").primaryKey(),
  ownerId: text("owner_id").notNull(),
  articleId: text("article_id").notNull(),
  text: text("text").notNull(),
  note: text("note").notNull().default(""),
  styles: text("styles").notNull().default("[]"), // JSON 数组，如 '["green","underline"]'
  paragraphIndex: integer("paragraph_index").notNull().default(0), // 段落序号
  startOffset: integer("start_offset").notNull().default(0), // 段落内起始偏移（含）
  endOffset: integer("end_offset").notNull().default(0), // 段落内结束偏移（不含）
  createdAt: integer("created_at").notNull(), // unix 毫秒
}, (t) => ({
  ownerArticleParagraph: index("highlights_owner_article_paragraph_idx").on(t.ownerId, t.articleId, t.paragraphIndex),
}));

export const highlightParagraphs = sqliteTable("highlight_paragraphs", {
  ownerId: text("owner_id").notNull(),
  articleId: text("article_id").notNull(),
  paragraphIndex: integer("paragraph_index").notNull(),
  version: integer("version").notNull().default(0),
  spans: text("spans").notNull().default("[]"),
  updatedAt: integer("updated_at").notNull(),
}, (t) => ({
  pk: primaryKey({ columns: [t.ownerId, t.articleId, t.paragraphIndex] }),
}));

// 每日一练：每个归属每天一条（复合主键），重复提交即覆盖
export const practice = sqliteTable(
  "practice",
  {
    ownerId: text("owner_id").notNull(),
    date: text("date").notNull(), // "YYYY-MM-DD"
    correct: integer("correct").notNull(),
    total: integer("total").notNull(),
  },
  (t) => ({
    pk: primaryKey({ columns: [t.ownerId, t.date] }),
  }),
);

// 错题本：每日一练答错的题（可单独删除）
export const wrongQuestions = sqliteTable(
  "wrong_questions",
  {
    id: text("id").primaryKey(),
    ownerId: text("owner_id").notNull(),
    date: text("date").notNull(), // "YYYY-MM-DD"
    question: text("question").notNull(),
    options: text("options").notNull(), // JSON 数组
    answer: integer("answer").notNull(),
    chosen: integer("chosen").notNull(),
    analysis: text("analysis").notNull(),
    createdAt: integer("created_at").notNull(),
  },
  (t) => ({
    ownerIdx: index("wrong_questions_owner_idx").on(t.ownerId),
  }),
);

// 考点卡片复习状态：每个归属每张卡一条（复合主键），调度状态序列化在 fsrs_state 里
export const reviewCards = sqliteTable(
  "review_cards",
  {
    ownerId: text("owner_id").notNull(),
    cardId: text("card_id").notNull(),
    // ts-fsrs Card 序列化 JSON（due/last_review 为 unix 毫秒）
    fsrsState: text("fsrs_state").notNull(),
    dueAt: integer("due_at").notNull(), // 下次到期 unix 毫秒（冗余，便于查询）
    reviewCount: integer("review_count").notNull().default(0),
    lastReviewAt: integer("last_review_at"), // unix 毫秒，可为 null
    createdAt: integer("created_at").notNull(), // unix 毫秒
  },
  (t) => ({
    pk: primaryKey({ columns: [t.ownerId, t.cardId] }),
    ownerDue: index("review_cards_owner_due_idx").on(t.ownerId, t.dueAt),
  }),
);

// 用户：用户名 + PBKDF2 哈希密码（永不存明文）+ 个人资料
export const users = sqliteTable("users", {
  id: text("id").primaryKey(),
  username: text("username").notNull().unique(),
  passwordHash: text("password_hash").notNull(),
  salt: text("salt").notNull(),
  email: text("email").notNull().default(""),
  name: text("name").notNull().default(""),
  avatar: text("avatar").notNull().default(""),
  createdAt: integer("created_at").notNull(), // unix 毫秒
}, (t) => ({
  verifiedEmail: uniqueIndex("users_verified_email_unique").on(t.email).where(sql`${t.email} <> ''`),
}));

export const emailVerificationCodes = sqliteTable("email_verification_codes", {
  id: text("id").primaryKey(),
  email: text("email").notNull(),
  codeHash: text("code_hash").notNull(),
  expiresAt: integer("expires_at").notNull(),
  attempts: integer("attempts").notNull().default(0),
  consumedAt: integer("consumed_at"),
  consumeToken: text("consume_token"),
  ipHash: text("ip_hash").notNull(),
  deviceId: text("device_id").notNull(),
  createdAt: integer("created_at").notNull(),
}, (t) => ({
  emailCreated: index("verification_email_created_idx").on(t.email, t.createdAt),
  ipCreated: index("verification_ip_created_idx").on(t.ipHash, t.createdAt),
  deviceCreated: index("verification_device_created_idx").on(t.deviceId, t.createdAt),
}));

export const sessions = sqliteTable("sessions", {
  id: text("id").primaryKey(),
  userId: text("user_id").notNull(),
  tokenHash: text("token_hash").notNull().unique(),
  expiresAt: integer("expires_at").notNull(),
  revokedAt: integer("revoked_at"),
  createdAt: integer("created_at").notNull(),
});

export const subscriptions = sqliteTable("subscriptions", {
  userId: text("user_id").primaryKey(),
  status: text("status").notNull().default("unsubscribed"),
  subscribedAt: integer("subscribed_at"),
  unsubscribedAt: integer("unsubscribed_at"),
  unsubscribeTokenHash: text("unsubscribe_token_hash"),
  unsubscribeTokenNonce: text("unsubscribe_token_nonce"),
  suppressionReason: text("suppression_reason"),
  suppressedAt: integer("suppressed_at"),
  suppressionProviderMessageId: text("suppression_provider_message_id"),
  updatedAt: integer("updated_at").notNull(),
});

export const newsletterIssues = sqliteTable("newsletter_issues", {
  id: text("id").primaryKey(),
  issueDate: text("issue_date").notNull().unique(),
  subject: text("subject").notNull(),
  textContent: text("text_content").notNull(),
  status: text("status").notNull().default("draft"),
  createdAt: integer("created_at").notNull(),
});

export const mailDeliveries = sqliteTable("mail_deliveries", {
  id: text("id").primaryKey(),
  issueId: text("issue_id").notNull(),
  userId: text("user_id").notNull(),
  recipient: text("recipient").notNull(),
  status: text("status").notNull().default("pending"),
  attempts: integer("attempts").notNull().default(0),
  lastError: text("last_error").notNull().default(""),
  nextAttemptAt: integer("next_attempt_at").notNull().default(0),
  leaseToken: text("lease_token"),
  leaseExpiresAt: integer("lease_expires_at"),
  sentAt: integer("sent_at"),
  providerMessageId: text("provider_message_id"),
  providerEvent: text("provider_event"),
  providerEventAt: integer("provider_event_at"),
  lastReconciledAt: integer("last_reconciled_at"),
  reconcileAttempts: integer("reconcile_attempts").notNull().default(0),
  nextReconcileAt: integer("next_reconcile_at").notNull().default(0),
  createdAt: integer("created_at").notNull(),
}, (t) => ({
  issueUser: uniqueIndex("mail_issue_user_idx").on(t.issueId, t.userId),
  providerMessage: uniqueIndex("mail_provider_message_idx").on(t.providerMessageId),
}));

export const resendWebhookEvents = sqliteTable("resend_webhook_events", {
  svixId: text("svix_id").primaryKey(),
  providerMessageId: text("provider_message_id").notNull(),
  eventType: text("event_type").notNull(),
  suppressionReason: text("suppression_reason"),
  eventAt: integer("event_at").notNull(),
  processedAt: integer("processed_at").notNull(),
}, (t) => ({ providerMessage: index("resend_webhook_provider_idx").on(t.providerMessageId) }));

// AI 解释邀请码（共享码）：一个码的 remaining 为全局共享额度；total 恒为 100。
export const inviteCodes = sqliteTable("invite_codes", {
  code: text("code").primaryKey(),
  remaining: integer("remaining").notNull(),
  total: integer("total").notNull(),
  createdAt: integer("created_at").notNull(), // unix 毫秒
});

// 邀请码激活记录：owner 为 user:<id> 或 device:<id>，一个 owner 只能激活一个码（可换码）。
export const inviteActivations = sqliteTable("invite_activations", {
  ownerId: text("owner_id").primaryKey(),
  code: text("code").notNull(),
  activatedAt: integer("activated_at").notNull(),
}, (t) => ({
  codeIdx: index("invite_activations_code_idx").on(t.code),
}));
