import { and, desc, eq, isNull } from "drizzle-orm";
import { DrizzleD1Database } from "drizzle-orm/d1";
import { Hono } from "hono";
import { deleteCookie, getCookie, setCookie } from "hono/cookie";
import { emailCodeRequestSchema, emailCodeVerifySchema } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import { emailVerificationCodes, sessions, users } from "../db/schema";
import { accountMergeStatements, type PreparedSql } from "../lib/account-merge";
import { constantEqual, randomCode, randomToken, sha256 } from "../lib/auth";
import { getDeviceId } from "../lib/device";
import { badInput, fail } from "../lib/http";
import { diagnosticError, diagnosticInfo, diagnosticWarn, errorType } from "../lib/diagnostics";

export const SESSION_COOKIE = "kaogong_session";
const CODE_TTL = 10 * 60_000;
const SESSION_TTL = 30 * 24 * 60 * 60_000;

type D1Client = {
  readonly batch: (statements: D1PreparedStatement[]) => Promise<D1Result<unknown>[]>;
  readonly prepare: (query: string) => D1PreparedStatement;
};

type SQLiteClient = {
  readonly prepare: (query: string) => {
    readonly run: (...params: (number | string)[]) => { readonly changes: number | bigint };
  };
  readonly transaction: <T>(operation: () => T) => () => T;
};

type AtomicResult = { readonly changes: number | bigint };

function hasD1Client(value: object): value is { readonly $client: D1Client } {
  return "$client" in value;
}

function hasSQLiteClient(value: object): value is { readonly $client: SQLiteClient } {
  return "$client" in value;
}

async function atomicBatch(db: DB, statements: readonly PreparedSql[]): Promise<readonly AtomicResult[]> {
  if (db instanceof DrizzleD1Database) {
    if (!hasD1Client(db)) throw new TypeError("D1 client is unavailable");
    const results = await db.$client.batch(statements.map(({ query, params }) => db.$client.prepare(query).bind(...params)));
    return results.map((result) => ({ changes: result.meta.changes }));
  }
  if (!hasSQLiteClient(db)) throw new TypeError("SQLite client is unavailable");
  const run = db.$client.transaction(() => statements.map(({ query, params }) => {
    const result = db.$client.prepare(query).run(...params);
    return { changes: result.changes };
  }));
  return run();
}

export async function sessionUserId(c: { req: { raw: Request } }, db: DB): Promise<string | null> {
  const token = getCookie(c as never, SESSION_COOKIE);
  if (!token) return null;
  const hash = await sha256(token);
  const now = Date.now();
  const session = await db.select().from(sessions).where(eq(sessions.tokenHash, hash)).get();
  if (!session) return null;
  if (session.revokedAt !== null) return null;
  if (session.expiresAt <= now) {
    diagnosticInfo({ event: "auth.session.expired" });
    return null;
  }
  return session.userId;
}

export function authRoutes(db: DB, config: AppConfig) {
  const r = new Hono();
  r.post("/email/code", async (c) => {
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = emailCodeRequestSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const email = parsed.data.email;
    const now = Date.now();
    const deviceId = c.req.header("x-device-id") ?? "unknown";
    const ip = c.req.header("cf-connecting-ip") ?? c.req.header("x-forwarded-for") ?? "unknown";
    const ipHash = await sha256(ip);
    const provider = config.verificationMailProvider;
    if (!provider || !config.authSecret) {
      diagnosticWarn({ event: "auth.code.suppressed", reason: "configuration" });
    } else {
      const code = randomCode();
      const recordId = crypto.randomUUID();
      const claimResult = await atomicBatch(db, [{
        query: `INSERT INTO email_verification_codes
            (id, email, code_hash, expires_at, attempts, consumed_at, consume_token, ip_hash, device_id, created_at)
          SELECT ?, ?, ?, ?, 0, ?, NULL, ?, ?, ?
          WHERE NOT EXISTS (
            SELECT 1 FROM email_verification_codes WHERE email = ? AND created_at > ?
          )
          AND (SELECT count(*) FROM email_verification_codes WHERE ip_hash = ? AND created_at > ?) < 20
          AND (SELECT count(*) FROM email_verification_codes WHERE device_id = ? AND created_at > ?) < 10`,
        params: [
          recordId, email, await sha256(`${email}:${code}:${config.authSecret}`), now + CODE_TTL,
          now, ipHash, deviceId, now, email, now - 60_000, ipHash, now - 60 * 60_000,
          deviceId, now - 60 * 60_000,
        ],
      }]);
      if (claimResult[0]?.changes === 1) {
        try {
          await provider.send({
            to: email, subject: "时政小助手登录验证码",
            text: `你的验证码是 ${code}，10 分钟内有效。请勿转发给他人。`,
            html: `<p>你的验证码是 <strong>${code}</strong>，10 分钟内有效。请勿转发给他人。</p>`,
          });
          await db.update(emailVerificationCodes).set({ consumedAt: null })
            .where(eq(emailVerificationCodes.id, recordId)).run();
        } catch (error) {
          try {
            await db.delete(emailVerificationCodes).where(eq(emailVerificationCodes.id, recordId)).run();
          } catch (cleanupError) {
            diagnosticError({ event: "auth.provider.failed", errorType: errorType(cleanupError) });
          }
          diagnosticError({ event: "auth.provider.failed", errorType: errorType(error) });
        }
      }
    }
    return c.json({ ok: true, data: { message: "如果邮箱有效，验证码将发送到该地址" } });
  });

  r.post("/email/verify", async (c) => {
    if (!config.authSecret) return fail(c, 503, "AUTH_UNAVAILABLE", "认证服务未配置");
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = emailCodeVerifySchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const { email, code } = parsed.data;
    const now = Date.now();
    const record = await db.select().from(emailVerificationCodes).where(eq(emailVerificationCodes.email, email))
      .orderBy(desc(emailVerificationCodes.createdAt)).get();
    const expected = await sha256(`${email}:${code}:${config.authSecret}`);
    const codeMatches = record ? constantEqual(record.codeHash, expected) : false;
    if (!record || !codeMatches) {
      if (record) await atomicBatch(db, [{
        query: `UPDATE email_verification_codes SET attempts = attempts + 1
          WHERE id = ? AND consumed_at IS NULL AND expires_at > ? AND attempts < 5 AND code_hash <> ?`,
        params: [record.id, now, expected],
      }]);
      return fail(c, 401, "CODE_INVALID", "验证码无效或已过期");
    }
    let user = await db.select().from(users).where(eq(users.email, email)).get();
    user ??= await db.select().from(users).where(eq(users.username, email)).get();
    const userId = user?.id ?? crypto.randomUUID();
    const userOwnerId = `user:${userId}`;
    const consumeToken = crypto.randomUUID();
    const token = randomToken();
    const deviceId = getDeviceId(c);
    const ownsClaim = "EXISTS (SELECT 1 FROM email_verification_codes WHERE consume_token = ?)";
    const targetExists = "EXISTS (SELECT 1 FROM users WHERE id = ? AND email = ?)";
    const statements: PreparedSql[] = [
      {
        query: `UPDATE email_verification_codes SET consumed_at = ?, consume_token = ?
          WHERE id = ? AND consumed_at IS NULL AND expires_at > ? AND attempts < 5 AND code_hash = ?`,
        params: [now, consumeToken, record.id, now, expected],
      },
      ...(user ? [{
        query: `UPDATE users SET email = ?
          WHERE id = ? AND username = ? AND email <> ? AND ${ownsClaim}
            AND NOT EXISTS (SELECT 1 FROM users WHERE email = ? AND id <> ?)`,
        params: [email, userId, email, email, consumeToken, email, userId],
      }] : []),
      {
        query: `INSERT INTO users (id, username, password_hash, salt, email, name, avatar, created_at)
          SELECT ?, ?, 'email-code-only', 'email-code-only', ?, '', '😀', ?
          WHERE ${ownsClaim} AND NOT EXISTS (SELECT 1 FROM users WHERE id = ?)`,
        params: [userId, email, email, now, consumeToken, userId],
      },
      ...(deviceId ? accountMergeStatements({ consumeToken, deviceId, email, userId, userOwnerId }) : []),
      {
        query: `INSERT INTO sessions (id, user_id, token_hash, expires_at, revoked_at, created_at)
          SELECT ?, ?, ?, ?, NULL, ? WHERE ${ownsClaim} AND ${targetExists}`,
        params: [crypto.randomUUID(), userId, await sha256(token), now + SESSION_TTL, now, consumeToken, userId, email],
      },
      {
        query: `UPDATE email_verification_codes SET consumed_at = NULL, consume_token = NULL
          WHERE consume_token = ? AND NOT ${targetExists}`,
        params: [consumeToken, userId, email],
      },
    ];
    const results = await atomicBatch(db, statements);
    if (results[0]?.changes !== 1) return fail(c, 401, "CODE_INVALID", "验证码无效或已过期");
    if (results.at(-1)?.changes === 1) return fail(c, 500, "USER_CREATE_FAILED", "用户创建失败");
    user = await db.select().from(users).where(and(eq(users.id, userId), eq(users.email, email))).get();
    if (!user) return fail(c, 500, "USER_CREATE_FAILED", "用户创建失败");
    diagnosticInfo({ event: "auth.session.created" });
    setCookie(c, SESSION_COOKIE, token, {
      httpOnly: true, secure: config.secureCookies !== false, sameSite: "Lax",
      path: "/", maxAge: SESSION_TTL / 1000,
    });
    return c.json({ ok: true, data: { user: { id: user.id, email: user.email, avatar: user.avatar } } });
  });

  r.get("/session", async (c) => {
    const id = await sessionUserId(c, db);
    if (!id) return fail(c, 401, "AUTH_REQUIRED", "未登录");
    const user = await db.select().from(users).where(eq(users.id, id)).get();
    if (!user) return fail(c, 401, "AUTH_REQUIRED", "用户不存在");
    // avatar 一并回传：顶栏头像要用用户自己挑的那一格，而不是邮箱哈希兜底
    return c.json({ ok: true, data: { id: user.id, email: user.email, avatar: user.avatar } });
  });

  r.post("/logout", async (c) => {
    const token = getCookie(c, SESSION_COOKIE);
    if (token) {
      const revoked = await db.update(sessions).set({ revokedAt: Date.now() }).where(and(
        eq(sessions.tokenHash, await sha256(token)), isNull(sessions.revokedAt),
      )).returning().all();
      if (revoked.length === 1) diagnosticInfo({ event: "auth.session.revoked" });
    }
    deleteCookie(c, SESSION_COOKIE, { path: "/" });
    return c.json({ ok: true, data: null });
  });
  return r;
}
