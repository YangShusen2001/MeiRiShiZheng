import { and, desc, eq } from "drizzle-orm";
import { Hono } from "hono";
import { favoriteCreateSchema, type Favorite, type FavoriteKind } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import { favorites } from "../db/schema";
import { resolveOwnerId } from "../lib/identity";
import { badInput, fail } from "../lib/http";

function toFavorite(row: typeof favorites.$inferSelect): Favorite {
  return {
    id: row.id,
    url: row.url,
    title: row.title,
    source: row.source,
    note: row.note,
    kind: row.kind as FavoriteKind,
    quote: row.quote,
    termText: row.termText,
    termExplanation: row.termExplanation,
    articleId: row.articleId,
    createdAt: row.createdAt,
  };
}

export function favoritesRoutes(db: DB, config: AppConfig) {
  const r = new Hono();

  r.get("/", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    // ?url= 过滤（收藏速度优化 2026-08-20）：阅读页只需该文章的收藏状态，
    // 避免每篇文章全量拉取收藏列表；不传 url 时返回全部（收藏页用）。
    const url = c.req.query("url");
    const conds = [eq(favorites.ownerId, owner)];
    if (url) conds.push(eq(favorites.url, url));
    const rows = await db.select().from(favorites)
      .where(and(...conds))
      .orderBy(desc(favorites.createdAt)).all();
    return c.json({ ok: true, data: rows.map(toFavorite) });
  });

  r.post("/", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = favoriteCreateSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const { url, title, source, note, kind, quote, termText, termExplanation, articleId } = parsed.data;
    // 幂等键：金句按 (owner, url, quote)，术语按 (owner, url, term_text)，文章按 (owner, url)。
    const normalizedQuote = kind === "quote" ? quote : "";
    const normalizedTerm = kind === "term" ? termText : "";
    const existing = await db.select().from(favorites).where(and(
      eq(favorites.ownerId, owner),
      eq(favorites.url, url),
      eq(favorites.kind, kind),
      eq(favorites.quote, normalizedQuote),
      eq(favorites.termText, normalizedTerm),
    )).get();
    if (existing) {
      return c.json({ ok: true, data: toFavorite(existing) }, 200);
    }
    const row = {
      id: crypto.randomUUID(),
      ownerId: owner,
      url,
      title,
      source: source ?? "",
      note: note ?? "",
      kind,
      quote: normalizedQuote,
      termText: normalizedTerm,
      termExplanation: kind === "term" ? termExplanation : "",
      articleId: kind === "term" ? articleId : "",
      createdAt: Date.now(),
    };
    await db.insert(favorites).values(row).run();
    return c.json({ ok: true, data: toFavorite(row) }, 201);
  });

  r.delete("/:id", async (c) => {
    const owner = await resolveOwnerId(c, db);
    if (!owner) return fail(c, 400, "IDENTITY_REQUIRED", "缺少身份标识");
    const id = c.req.param("id");
    await db.delete(favorites).where(and(eq(favorites.id, id), eq(favorites.ownerId, owner))).run();
    return c.json({ ok: true, data: null });
  });

  return r;
}
