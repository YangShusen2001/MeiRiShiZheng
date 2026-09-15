import { eq } from "drizzle-orm";
import { Hono } from "hono";
import { notificationSettingsUpdateSchema, type NotificationSettings } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import { notificationSettings } from "../db/schema";
import { resolveOwnerId } from "../lib/identity";
import { badInput, fail } from "../lib/http";

/**
 * 没设置过时的默认值：**全关**。
 * 提醒是打扰性能力，不主动替用户打开 —— 画布上那两行「开」是设计示意，不是默认值。
 */
const DEFAULTS: NotificationSettings = {
  dailyEnabled: false,
  dailyAt: "08:30",
  reviewEnabled: false,
  reviewAt: "09:00",
  quotaEnabled: false,
};

export function notificationRoutes(db: DB, config: AppConfig) {
  const r = new Hono();

  r.get("/", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const row = await db.select().from(notificationSettings)
      .where(eq(notificationSettings.ownerId, owner)).get();
    const data: NotificationSettings = row
      ? {
          dailyEnabled: row.dailyEnabled,
          dailyAt: row.dailyAt,
          reviewEnabled: row.reviewEnabled,
          reviewAt: row.reviewAt,
          quotaEnabled: row.quotaEnabled,
        }
      : DEFAULTS;
    return c.json({ ok: true, data });
  });

  /** 局部更新：没传的项保留原值（没有记录时落到 DEFAULTS）。 */
  r.post("/", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = notificationSettingsUpdateSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");

    const current = await db.select().from(notificationSettings)
      .where(eq(notificationSettings.ownerId, owner)).get();
    const next: NotificationSettings = {
      dailyEnabled: parsed.data.dailyEnabled ?? current?.dailyEnabled ?? DEFAULTS.dailyEnabled,
      dailyAt: parsed.data.dailyAt ?? current?.dailyAt ?? DEFAULTS.dailyAt,
      reviewEnabled: parsed.data.reviewEnabled ?? current?.reviewEnabled ?? DEFAULTS.reviewEnabled,
      reviewAt: parsed.data.reviewAt ?? current?.reviewAt ?? DEFAULTS.reviewAt,
      quotaEnabled: parsed.data.quotaEnabled ?? current?.quotaEnabled ?? DEFAULTS.quotaEnabled,
    };
    const now = Date.now();
    await db.insert(notificationSettings)
      .values({ ownerId: owner, ...next, updatedAt: now })
      .onConflictDoUpdate({ target: notificationSettings.ownerId, set: { ...next, updatedAt: now } })
      .run();
    return c.json({ ok: true, data: next });
  });

  return r;
}
