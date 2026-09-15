import { eq } from "drizzle-orm";
import { Hono } from "hono";
import { profileUpdateSchema, type Profile } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import { subscriptions, users } from "../db/schema";
import { sessionUserId } from "./auth";
import { badInput, fail } from "../lib/http";

function toProfile(row: typeof users.$inferSelect, subscribed: boolean): Profile {
  return {
    name: row.name,
    email: row.email,
    avatar: row.avatar,
    subscribed,
    // 个人中心账户行要显示「加入 YYYY-MM-DD」—— 列本来就在，只是没回传
    createdAt: row.createdAt,
  };
}

export function profileRoutes(db: DB, config: AppConfig) {
  const r = new Hono();
  const secret = config.authSecret ?? "";

  r.get("/", async (c) => {
    if (!secret) return fail(c, 503, "AUTH_UNAVAILABLE", "未配置 AUTH_SECRET");
    const id = await sessionUserId(c, db);
    if (!id) return fail(c, 401, "AUTH_REQUIRED", "未登录");
    const user = await db.select().from(users).where(eq(users.id, id)).get();
    if (!user) return fail(c, 401, "AUTH_REQUIRED", "用户不存在");
    const subscription = await db.select().from(subscriptions).where(eq(subscriptions.userId, id)).get();
    return c.json({ ok: true, data: toProfile(user, subscription?.status === "subscribed") });
  });

  r.post("/", async (c) => {
    if (!secret) return fail(c, 503, "AUTH_UNAVAILABLE", "未配置 AUTH_SECRET");
    const id = await sessionUserId(c, db);
    if (!id) return fail(c, 401, "AUTH_REQUIRED", "未登录");
    let raw: Record<string, unknown> = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = profileUpdateSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const updates: Record<string, unknown> = {};
    if (parsed.data.name !== undefined) updates.name = parsed.data.name;
    if (parsed.data.avatar !== undefined) updates.avatar = parsed.data.avatar;
    if (Object.keys(updates).length) {
      await db.update(users).set(updates).where(eq(users.id, id)).run();
    }
    const user = await db.select().from(users).where(eq(users.id, id)).get();
    if (!user) return fail(c, 401, "AUTH_REQUIRED", "用户不存在");
    const subscription = await db.select().from(subscriptions).where(eq(subscriptions.userId, id)).get();
    return c.json({ ok: true, data: toProfile(user, subscription?.status === "subscribed") });
  });

  return r;
}
