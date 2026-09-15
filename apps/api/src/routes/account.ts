import { eq } from "drizzle-orm";
import { Hono } from "hono";
import { accountDeleteSchema } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import {
  favorites,
  highlightParagraphs,
  highlights,
  inviteActivations,
  mailDeliveries,
  notificationSettings,
  practice,
  reviewCards,
  sessions,
  subscriptions,
  users,
  wrongQuestions,
} from "../db/schema";
import { getDeviceId } from "../lib/device";
import { badInput, fail } from "../lib/http";
import { sessionUserId } from "./auth";

/**
 * 账号数据与注销（画布 25 / 3:2073「数据与隐私」）。
 *
 * 导出：把该 owner 的各表原样带出（`owner_id` 维度的 + `user_id` 维度的），结构不收紧 ——
 *       以后多一张表不该变成契约破坏性变更。
 * 注销：**不可逆**，必须原样传确认词「注销账号」。
 *
 * ⚠️ 数据分两种归属：`owner_id`（`user:<id>` 或当前设备 id）与 `user_id`。
 *    注销时两种都要清 —— 只删 `owner_id` 会留下会话、订阅与邮件投递记录，
 *    只删 `user_id` 会留下收藏、划线、错题。当前设备维度的数据也一起清：
 *    请求就是这台设备发的，未登录时产生的数据同样属于这个人。
 */
export function accountRoutes(db: DB, config: AppConfig) {
  const r = new Hono();

  r.get("/export", async (c) => {
    const userId = await sessionUserId(c, db);
    const device = getDeviceId(c);
    const owner = userId ? `user:${userId}` : device;
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");

    const [fav, hl, hlp, pr, wq, rc, ns] = await Promise.all([
      db.select().from(favorites).where(eq(favorites.ownerId, owner)).all(),
      db.select().from(highlights).where(eq(highlights.ownerId, owner)).all(),
      db.select().from(highlightParagraphs).where(eq(highlightParagraphs.ownerId, owner)).all(),
      db.select().from(practice).where(eq(practice.ownerId, owner)).all(),
      db.select().from(wrongQuestions).where(eq(wrongQuestions.ownerId, owner)).all(),
      db.select().from(reviewCards).where(eq(reviewCards.ownerId, owner)).all(),
      db.select().from(notificationSettings).where(eq(notificationSettings.ownerId, owner)).get(),
    ]);

    const user = userId ? await db.select().from(users).where(eq(users.id, userId)).get() : null;
    const sub = userId ? await db.select().from(subscriptions).where(eq(subscriptions.userId, userId)).get() : null;

    return c.json({
      ok: true,
      data: {
        exportedAt: Date.now(),
        owner,
        profile: user
          ? { name: user.name, email: user.email, avatar: user.avatar, createdAt: user.createdAt }
          : null,
        subscription: sub ? { status: sub.status, subscribedAt: sub.subscribedAt } : null,
        notifications: ns ?? null,
        favorites: fav,
        highlights: hl,
        highlightParagraphs: hlp,
        practice: pr,
        wrongQuestions: wq,
        reviewCards: rc,
      },
    });
  });

  r.delete("/", async (c) => {
    const userId = await sessionUserId(c, db);
    if (!userId) return fail(c, 401, "AUTH_REQUIRED", "请先登录再注销账号");

    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = accountDeleteSchema.safeParse(raw);
    if (!parsed.success) {
      return badInput(c, "注销需要原样确认：请在请求体传 { confirm: \"注销账号\" }");
    }

    const userOwner = `user:${userId}`;
    const device = getDeviceId(c);
    const owners = device && device !== userOwner ? [userOwner, device] : [userOwner];

    // owner_id 维度
    for (const o of owners) {
      await db.delete(favorites).where(eq(favorites.ownerId, o)).run();
      await db.delete(highlightParagraphs).where(eq(highlightParagraphs.ownerId, o)).run();
      await db.delete(highlights).where(eq(highlights.ownerId, o)).run();
      await db.delete(practice).where(eq(practice.ownerId, o)).run();
      await db.delete(wrongQuestions).where(eq(wrongQuestions.ownerId, o)).run();
      await db.delete(reviewCards).where(eq(reviewCards.ownerId, o)).run();
      await db.delete(notificationSettings).where(eq(notificationSettings.ownerId, o)).run();
      await db.delete(inviteActivations).where(eq(inviteActivations.ownerId, o)).run();
    }
    // user_id 维度
    await db.delete(sessions).where(eq(sessions.userId, userId)).run();
    await db.delete(subscriptions).where(eq(subscriptions.userId, userId)).run();
    await db.delete(mailDeliveries).where(eq(mailDeliveries.userId, userId)).run();
    // 最后删账号本身：前面的语句都还能凭 user_id 找回归属，删早了就成孤儿数据
    await db.delete(users).where(eq(users.id, userId)).run();

    return c.json({ ok: true, data: null });
  });

  return r;
}
