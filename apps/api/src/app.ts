// Hono 应用工厂：注入 drizzle 实例（生产传 D1，测试传 better-sqlite3）
import { Hono } from "hono";
import { cors } from "hono/cors";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { DrizzleD1Database } from "drizzle-orm/d1";
import * as schema from "./db/schema";
import { favoritesRoutes } from "./routes/favorites";
import { highlightsRoutes } from "./routes/highlights";
import { practiceRoutes } from "./routes/practice";
import { explainRoutes } from "./routes/explain";
import { inviteRoutes } from "./routes/invite";
import { authRoutes } from "./routes/auth";
import { profileRoutes } from "./routes/profile";
import type { MailProvider } from "./lib/mail";
import type { NewsletterMailProvider } from "./lib/newsletter-mail-provider";
import { processNewsletterBatch, type NewsletterBatchResult } from "./lib/newsletter";
import { newsletterRoutes, subscriptionRoutes } from "./routes/subscription";
import { webhookRoutes } from "./routes/webhooks";
import { reviewRoutes } from "./routes/review";

export type DB = BetterSQLite3Database<typeof schema> | DrizzleD1Database<typeof schema>;

export interface AppConfig {
  deepseekKey?: string;
  authSecret?: string;
  /** 允许跨源的 Origin 白名单（如 Pages 域名）；未配置则不发送 CORS 头。 */
  allowedOrigins?: string[];
  verificationMailProvider?: MailProvider;
  newsletterMailProvider?: NewsletterMailProvider;
  secureCookies?: boolean;
  jobSecret?: string;
  publicApiUrl?: string;
  resendWebhookSecret?: string;
}

export async function processScheduledNewsletter(db: DB, config: AppConfig): Promise<NewsletterBatchResult> {
  const result = await processNewsletterBatch(db, config);
  if (result.kind === "skipped") {
    console.warn(JSON.stringify({ event: "newsletter.schedule.skipped", reason: result.reason }));
  }
  return result;
}

export function createApp(db: DB, config: AppConfig = {}) {
  const app = new Hono();
  const origins = config.allowedOrigins ?? [];
  app.use(
    "/api/*",
    cors({
      // 白名单非空时只允许白名单内 origin；空时不回送 ACAO 头（拒绝跨站）。
      origin: (requestOrigin) =>
        origins.length && requestOrigin && origins.includes(requestOrigin) ? requestOrigin : null,
      credentials: true,
      allowMethods: ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
      // Cookie 供原生客户端（HarmonyOS）手工携带会话令牌；浏览器同站请求本就不需要它出现在这里。
      allowHeaders: ["Content-Type", "X-Device-Id", "Authorization", "Cookie"],
      maxAge: 86400,
    }),
  );
  app.get("/api/ping", (c) => c.json({ ok: true, data: "pong" }));
  app.route("/api/auth", authRoutes(db, config));
  app.route("/api/profile", profileRoutes(db, config));
  app.route("/api/favorites", favoritesRoutes(db, config));
  app.route("/api/highlights", highlightsRoutes(db, config));
  app.route("/api/practice", practiceRoutes(db, config));
  app.route("/api/explain", explainRoutes(db, config));
  app.route("/api/invite", inviteRoutes(db, config));
  app.route("/api/subscription", subscriptionRoutes(db, config));
  app.route("/api/newsletter", newsletterRoutes(db, config));
  app.route("/api/webhooks", webhookRoutes(db, config));
  app.route("/api/review", reviewRoutes(db, config));
  return app;
}
