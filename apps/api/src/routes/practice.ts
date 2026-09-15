import { and, eq, isNotNull, isNull } from "drizzle-orm";
import { Hono } from "hono";
import { practiceSubmitSchema, type PracticeRecord, type WrongQuestion } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import { practice, wrongQuestions } from "../db/schema";
import { resolveOwnerId } from "../lib/identity";
import { badInput, fail } from "../lib/http";

export function practiceRoutes(db: DB, config: AppConfig) {
  const r = new Hono();

  r.get("/", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const rows = await db.select().from(practice).where(eq(practice.ownerId, owner)).all();
    const data: PracticeRecord[] = rows.map(({ date, correct, total }) => ({ date, correct, total }));
    return c.json({ ok: true, data });
  });

  r.post("/", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = practiceSubmitSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const { date, correct, total, wrong } = parsed.data;
    // 同一归属同一天只留一条（复合主键 + onConflictDoUpdate）
    await db.insert(practice)
      .values({ ownerId: owner, date, correct, total })
      .onConflictDoUpdate({ target: [practice.ownerId, practice.date], set: { correct, total } })
      .run();
    // 错题覆盖式：同一天重做，先删旧错题再写新错题
    await db.delete(wrongQuestions)
      .where(and(eq(wrongQuestions.ownerId, owner), eq(wrongQuestions.date, date)))
      .run();
    for (const w of wrong) {
      await db.insert(wrongQuestions).values({
        id: crypto.randomUUID(),
        ownerId: owner,
        date,
        question: w.question,
        options: JSON.stringify(w.options),
        answer: w.answer,
        chosen: w.chosen,
        analysis: w.analysis,
        // 错因（画布 3:617）：题目侧预生成，没有就存 null，端上退回「你的 X → 正确 Y」
        traps: w.traps ? JSON.stringify(w.traps) : null,
        createdAt: Date.now(),
      }).run();
    }
    const data: PracticeRecord = { date, correct, total };
    return c.json({ ok: true, data });
  });

  // —— 错题本 / 已掌握 ——
  // 两个列表共用同一套行映射，区别只在 mastered_at 为 null（待复习）还是非 null（已掌握）

  /**
   * 库里的 traps 是 JSON 文本；坏值**不抛错**——退回 undefined，端上走降级渲染。
   * 错题本不该因为一行错因数据坏掉就整页打不开。
   */
  const parseTraps = (raw: string | null): string[] | undefined => {
    if (!raw) return undefined;
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (!Array.isArray(parsed) || parsed.length !== 4) return undefined;
      return parsed.map((v) => String(v ?? ""));
    } catch {
      return undefined;
    }
  };

  const toWrong = (row: typeof wrongQuestions.$inferSelect): WrongQuestion => {
    const base: WrongQuestion = {
      id: row.id,
      date: row.date,
      question: row.question,
      options: JSON.parse(row.options) as string[],
      answer: row.answer,
      chosen: row.chosen,
      analysis: row.analysis,
    };
    const traps = parseTraps(row.traps);
    return traps ? { ...base, traps } : base;
  };

  r.get("/wrong", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const rows = await db.select().from(wrongQuestions)
      .where(and(eq(wrongQuestions.ownerId, owner), isNull(wrongQuestions.masteredAt)))
      .all();
    return c.json({ ok: true, data: rows.map(toWrong) });
  });

  /**
   * 已掌握：点过「掌握 ✓」的题。
   * 2026-09-15 之前「掌握」是真删 —— 删完就查不回来，所以练习页的「已掌握」模式
   * 只能靠本机 localStorage 顶着（换设备就没了）。改成软删除后这个列表才有数据源。
   */
  r.get("/mastered", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const rows = await db.select().from(wrongQuestions)
      .where(and(eq(wrongQuestions.ownerId, owner), isNotNull(wrongQuestions.masteredAt)))
      .all();
    return c.json({ ok: true, data: rows.map(toWrong) });
  });

  // 「掌握 ✓」= 打上 mastered_at（软删除），不是真删 —— 真删会让「已掌握」永远是空的
  r.delete("/wrong/:id", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const id = c.req.param("id");
    await db.update(wrongQuestions)
      .set({ masteredAt: Date.now() })
      .where(and(eq(wrongQuestions.ownerId, owner), eq(wrongQuestions.id, id)))
      .run();
    return c.json({ ok: true, data: null });
  });

  return r;
}
