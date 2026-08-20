// 考点卡片复习路由：间隔重复调度（ts-fsrs）+ D1 状态持久化。
// 卡片内容（题目/答案）不经过本路由——前端从 content/cards 构建产物取，本路由只管理"复习状态"。
import { and, eq } from "drizzle-orm";
import { Hono } from "hono";
import { reviewGradeSchema, type ReviewCardState, type ReviewGradeResponse } from "@kaogong/contracts";
import { createEmptyCard, fsrs, Rating, type Card, type CardInput } from "ts-fsrs";
import type { AppConfig, DB } from "../app";
import { reviewCards } from "../db/schema";
import { resolveOwnerId } from "../lib/identity";
import { badInput, fail } from "../lib/http";

// 4 档自评 → ts-fsrs Rating（again=1, hard=2, good=3, easy=4）
const GRADE = {
  again: Rating.Again,
  hard: Rating.Hard,
  good: Rating.Good,
  easy: Rating.Easy,
} as const;

// 默认参数调度器（fsrs() 内部已套 generatorParameters()）
const scheduler = fsrs();

/** Card 序列化：Date 字段转 unix 毫秒存 JSON。 */
function serializeCard(card: Card): string {
  return JSON.stringify({
    ...card,
    due: card.due.getTime(),
    last_review: card.last_review ? card.last_review.getTime() : null,
  });
}

/** 反序列化：毫秒转回 Date，得到合法的 CardInput。 */
function deserializeCard(json: string): CardInput {
  const obj = JSON.parse(json) as Record<string, unknown>;
  return {
    ...obj,
    due: new Date(obj.due as number),
    last_review: obj.last_review == null ? null : new Date(obj.last_review as number),
    state: obj.state as CardInput["state"],
  } as CardInput;
}

export function reviewRoutes(db: DB, _config: AppConfig) {
  const r = new Hono();

  // 返回该 owner 所有卡的复习状态（前端据此算到期卡 + 每日新卡 ≤5）
  r.get("/state", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const rows = await db.select().from(reviewCards).where(eq(reviewCards.ownerId, owner)).all();
    const cards: ReviewCardState[] = rows.map((row) => ({
      cardId: row.cardId,
      dueAt: row.dueAt,
      reviewCount: row.reviewCount,
      lastReviewAt: row.lastReviewAt,
    }));
    return c.json({ ok: true, data: { cards } });
  });

  // 提交一张卡的自评，用 ts-fsrs 算下次到期
  r.post("/grade", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = reviewGradeSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const { cardId, rating } = parsed.data;
    const grade = GRADE[rating];
    const now = new Date();

    const existing = await db.select().from(reviewCards)
      .where(and(eq(reviewCards.ownerId, owner), eq(reviewCards.cardId, cardId)))
      .get();

    let nextCard: Card;
    let reviewCount: number;
    if (existing) {
      const cardInput = deserializeCard(existing.fsrsState);
      nextCard = scheduler.next(cardInput, now, grade).card;
      reviewCount = existing.reviewCount + 1;
      await db.update(reviewCards)
        .set({
          fsrsState: serializeCard(nextCard),
          dueAt: nextCard.due.getTime(),
          reviewCount,
          lastReviewAt: now.getTime(),
        })
        .where(and(eq(reviewCards.ownerId, owner), eq(reviewCards.cardId, cardId)))
        .run();
    } else {
      nextCard = scheduler.next(createEmptyCard(now), now, grade).card;
      reviewCount = 1;
      await db.insert(reviewCards).values({
        ownerId: owner,
        cardId,
        fsrsState: serializeCard(nextCard),
        dueAt: nextCard.due.getTime(),
        reviewCount,
        lastReviewAt: now.getTime(),
        createdAt: now.getTime(),
      }).run();
    }

    const data: ReviewGradeResponse = { dueAt: nextCard.due.getTime(), reviewCount };
    return c.json({ ok: true, data });
  });

  return r;
}
