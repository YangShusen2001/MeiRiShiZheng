import { Hono, type Context } from "hono";
import { explainRequestSchema, termAskRequestSchema } from "@kaogong/contracts";
import type { AppConfig, DB } from "../app";
import { answerTermQuestion, explainText, suggestTermQuestions } from "../lib/deepseek";
import { getDeviceId } from "../lib/device";
import { diagnosticError, errorType } from "../lib/diagnostics";
import { badInput, fail } from "../lib/http";
import { sessionUserId } from "./auth";
import { consumeInviteQuota, getInviteQuotaState } from "./invite";

/** 轻量级每设备限流：最多 10 次/分钟。生产可替换为 Cloudflare ratelimit binding。 */
interface RateBucket {
  count: number;
  resetAt: number;
}

const RATE_LIMIT = 10;
const RATE_WINDOW = 60_000;

const buckets = new Map<string, RateBucket>();

export function checkRateLimit(key: string): boolean {
  const now = Date.now();
  const b = buckets.get(key);
  if (!b || now >= b.resetAt) {
    buckets.set(key, { count: 1, resetAt: now + RATE_WINDOW });
    return true;
  }
  if (b.count >= RATE_LIMIT) return false;
  b.count += 1;
  return true;
}

/** 权限门禁（只读，不扣减）：登录用户不限次；匿名用户需已激活邀请码且有剩余额度。 */
async function checkExplainAccess(c: Context, db: DB, dev: string): Promise<"user" | "quota" | "no_activation" | "exhausted"> {
  const userId = await sessionUserId(c, db);
  if (userId) return "user";
  const state = await getInviteQuotaState(db, dev);
  if (state === "no_activation") return "no_activation";
  if (state === "exhausted") return "exhausted";
  return "quota";
}

function explainAccessError(c: Context, access: "no_activation" | "exhausted"): Response {
  return access === "no_activation"
    ? fail(c, 403, "INVITE_REQUIRED", "AI 解析需要登录或填写邀请码")
    : fail(c, 403, "QUOTA_EXHAUSTED", "邀请码额度已用完，请登录或联系管理员获取新邀请码");
}

export function explainRoutes(db: DB, config: AppConfig) {
  const r = new Hono();

  r.post("/", async (c) => {
    const dev = getDeviceId(c);
    if (!dev) return fail(c, 400, "DEVICE_REQUIRED", "缺少设备标识");
    if (!checkRateLimit(`explain:${dev}`)) {
      c.header("Retry-After", String(RATE_WINDOW / 1000));
      return fail(c, 429, "RATE_LIMITED", "请求过于频繁，请稍后再试");
    }
    // 权限门禁先只读校验（不扣减），确认 AI 可用后再扣减，避免「未配置 key」时白白扣次数。
    const access = await checkExplainAccess(c, db, dev);
    if (access === "no_activation" || access === "exhausted") return explainAccessError(c, access);
    const key = config.deepseekKey;
    if (!key) return fail(c, 503, "AI_UNAVAILABLE", "未配置 DeepSeek API Key");
    if (access === "quota") await consumeInviteQuota(db, dev);
    let body: Record<string, unknown> = {};
    try { body = await c.req.json(); } catch { body = {}; }
    const parsed = explainRequestSchema.safeParse(body);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    try {
      const explanation = await explainText(parsed.data.text, key);
      return c.json({ ok: true, data: { explanation } });
    } catch (error) {
      diagnosticError({ event: "ai.explain.failed", errorType: errorType(error) });
      return fail(c, 502, "AI_ERROR", "AI 解释失败");
    }
  });

  // 术语追问（收藏页「术语解析」）：无 question → 生成建议问题；有 question → Markdown 回答。
  r.post("/term/ask", async (c) => {
    const dev = getDeviceId(c);
    if (!dev) return fail(c, 400, "DEVICE_REQUIRED", "缺少设备标识");
    if (!checkRateLimit(`explain:${dev}`)) {
      c.header("Retry-After", String(RATE_WINDOW / 1000));
      return fail(c, 429, "RATE_LIMITED", "请求过于频繁，请稍后再试");
    }
    const access = await checkExplainAccess(c, db, dev);
    if (access === "no_activation" || access === "exhausted") return explainAccessError(c, access);
    const key = config.deepseekKey;
    if (!key) return fail(c, 503, "AI_UNAVAILABLE", "未配置 DeepSeek API Key");
    if (access === "quota") await consumeInviteQuota(db, dev);
    let raw: unknown = {};
    try { raw = await c.req.json(); } catch { raw = {}; }
    const parsed = termAskRequestSchema.safeParse(raw);
    if (!parsed.success) return badInput(c, parsed.error.issues[0]?.message ?? "参数非法");
    const { term, explanation, question } = parsed.data;
    try {
      if (question) {
        const answer = await answerTermQuestion(term, explanation, question, key);
        return c.json({ ok: true, data: { suggestions: [], answer } });
      }
      const suggestions = await suggestTermQuestions(term, explanation, key);
      return c.json({ ok: true, data: { suggestions, answer: undefined } });
    } catch (error) {
      diagnosticError({ event: "ai.termask.failed", errorType: errorType(error) });
      return fail(c, 502, "AI_ERROR", "AI 追问失败");
    }
  });

  return r;
}
