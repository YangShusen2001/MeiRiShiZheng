import { describe, expect, it } from "vitest";
import { DEVICE, headers, json, makeApp, readJson } from "./helpers";

interface GradeData { dueAt: number; reviewCount: number }
interface StateData { cards: Array<{ cardId: string; dueAt: number; reviewCount: number; lastReviewAt: number | null }> }

describe("review cards (spaced repetition)", () => {
  it("requires identity", async () => {
    const app = makeApp();
    const res = await app.request("/api/review/state");
    expect(res.status).toBe(400);
    const body = await readJson(res);
    expect(body.error?.code).toBe("IDENTITY_REQUIRED");
  });

  it("grades a new card and schedules it in the future", async () => {
    const app = makeApp();
    const res = await app.request("/api/review/grade", json("POST", { cardId: "15w-loc-001", rating: "good" }));
    expect(res.status).toBe(200);
    const body = await readJson<GradeData>(res);
    expect(body.ok).toBe(true);
    expect(body.data.reviewCount).toBe(1);
    expect(body.data.dueAt).toBeGreaterThan(Date.now());
  });

  it("increments review count and brings due closer on 'again' vs 'good'", async () => {
    const app = makeApp();
    const good = await readJson<GradeData>(
      await app.request("/api/review/grade", json("POST", { cardId: "c1", rating: "good" })),
    );
    const again = await readJson<GradeData>(
      await app.request("/api/review/grade", json("POST", { cardId: "c1", rating: "again" })),
    );
    expect(again.data.reviewCount).toBe(2);
    // again（忘了）的到期时间应不晚于 good（会了）
    expect(again.data.dueAt).toBeLessThanOrEqual(good.data.dueAt);
  });

  it("isolates review state per device", async () => {
    const app = makeApp();
    await app.request("/api/review/grade", json("POST", { cardId: "c1", rating: "good" }, DEVICE));
    const other = await readJson<StateData>(
      await app.request("/api/review/state", { headers: headers("other-device") }),
    );
    expect(other.data.cards).toEqual([]);
  });

  it("returns known card states", async () => {
    const app = makeApp();
    await app.request("/api/review/grade", json("POST", { cardId: "c1", rating: "good" }));
    const state = await readJson<StateData>(
      await app.request("/api/review/state", { headers: headers(DEVICE) }),
    );
    expect(state.data.cards).toHaveLength(1);
    expect(state.data.cards[0]).toMatchObject({ cardId: "c1", reviewCount: 1 });
    expect(state.data.cards[0].lastReviewAt).toBeTypeOf("number");
  });

  it("rejects invalid rating", async () => {
    const app = makeApp();
    const res = await app.request("/api/review/grade", json("POST", { cardId: "c1", rating: "bad" }));
    expect(res.status).toBe(400);
  });
});
