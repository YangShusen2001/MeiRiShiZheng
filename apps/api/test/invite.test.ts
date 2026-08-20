import type { AdminInviteCode, InviteStatus } from "@kaogong/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEVICE, headers, json, makeApp, makeContext, readJson } from "./helpers";
import { inviteActivations, inviteCodes } from "../src/db/schema";

afterEach(() => vi.unstubAllGlobals());

const JOB = "job-secret";

function makeInviteApp() {
  return makeApp({ jobSecret: JOB, deepseekKey: "k" });
}

async function generateCode(app: ReturnType<typeof makeApp>): Promise<string> {
  const res = await app.request("/api/invite/admin/invite-codes", {
    method: "POST",
    headers: { "x-job-secret": JOB },
  });
  expect(res.status).toBe(200);
  return (await readJson<AdminInviteCode>(res)).data.code;
}

function stubDeepseek() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(
        JSON.stringify({ choices: [{ message: { content: "解释内容" } }] }),
        { headers: { "content-type": "application/json" } },
      ),
    ),
  );
}

describe("invite codes", () => {
  it("生成邀请码需要 job secret，成功返回 100 次", async () => {
    const app = makeInviteApp();
    const unauth = await app.request("/api/invite/admin/invite-codes", { method: "POST" });
    expect(unauth.status).toBe(401);

    const ok = await app.request("/api/invite/admin/invite-codes", { method: "POST", headers: { "x-job-secret": JOB } });
    expect(ok.status).toBe(200);
    const data = (await readJson<AdminInviteCode>(ok)).data;
    expect(data.remaining).toBe(100);
    expect(data.total).toBe(100);
    expect(data.code).toMatch(/^[A-Z0-9]{12}$/);
  });

  it("激活邀请码并返回剩余次数；无效码返回 404", async () => {
    const app = makeInviteApp();
    const code = await generateCode(app);
    const act = await app.request("/api/invite/activate", json("POST", { code }));
    expect(act.status).toBe(200);
    expect((await readJson<InviteStatus>(act)).data).toMatchObject({ active: true, remaining: 100, code });

    const missing = await app.request("/api/invite/activate", json("POST", { code: "ZZZZZZZZZZZZ" }));
    expect(missing.status).toBe(404);
  });

  it("状态：未激活 active=false，激活后 active=true", async () => {
    const app = makeInviteApp();
    const before = await app.request("/api/invite/status", { headers: headers() });
    expect((await readJson<InviteStatus>(before)).data).toMatchObject({ active: false, remaining: 0, code: "" });

    const code = await generateCode(app);
    await app.request("/api/invite/activate", json("POST", { code }));
    const after = await app.request("/api/invite/status", { headers: headers() });
    expect((await readJson<InviteStatus>(after)).data.active).toBe(true);
  });
});

describe("explain 权限门禁", () => {
  it("未登录且未激活邀请码返回 403 INVITE_REQUIRED", async () => {
    const app = makeInviteApp();
    stubDeepseek();
    const res = await app.request("/api/explain", json("POST", { text: "高质量发展" }));
    expect(res.status).toBe(403);
    expect((await readJson(res)).error?.code).toBe("INVITE_REQUIRED");
  });

  it("激活邀请码后 explain 成功并扣减剩余次数", async () => {
    const app = makeInviteApp();
    stubDeepseek();
    const code = await generateCode(app);
    await app.request("/api/invite/activate", json("POST", { code }));

    const res = await app.request("/api/explain", json("POST", { text: "高质量发展" }));
    expect(res.status).toBe(200);

    const status = await app.request("/api/invite/status", { headers: headers() });
    expect((await readJson<InviteStatus>(status)).data.remaining).toBe(99);
  });

  it("额度耗尽返回 403 QUOTA_EXHAUSTED", async () => {
    const { app, db } = makeContext({ jobSecret: JOB, deepseekKey: "k" });
    stubDeepseek();
    await db.insert(inviteCodes).values({ code: "EXHAUSTED123", remaining: 0, total: 100, createdAt: Date.now() }).run();
    await db.insert(inviteActivations).values({ ownerId: `device:${DEVICE}`, code: "EXHAUSTED123", activatedAt: Date.now() }).run();

    const res = await app.request("/api/explain", json("POST", { text: "高质量发展" }));
    expect(res.status).toBe(403);
    expect((await readJson(res)).error?.code).toBe("QUOTA_EXHAUSTED");
  });

  it("登录用户不限次，无需邀请码", async () => {
    const sent: string[] = [];
    const app = makeApp({
      authSecret: "test-secret",
      secureCookies: false,
      verificationMailProvider: { async send(m) { sent.push(m.text); return {}; } },
      deepseekKey: "k",
    });
    stubDeepseek();

    await app.request("/api/auth/email/code", json("POST", { email: "123456@qq.com" }));
    const code = sent.at(-1)?.match(/\b(\d{6})\b/)?.[1];
    expect(code).toMatch(/^\d{6}$/);
    const verified = await app.request("/api/auth/email/verify", json("POST", { email: "123456@qq.com", code }));
    const cookie = verified.headers.get("set-cookie")?.split(";")[0] ?? "";

    const res = await app.request("/api/explain", {
      method: "POST",
      headers: { ...headers(), cookie, "content-type": "application/json" },
      body: JSON.stringify({ text: "高质量发展" }),
    });
    expect(res.status).toBe(200);
  });
});

describe("术语追问 /api/explain/term/ask", () => {
  it("未激活邀请码返回 403 INVITE_REQUIRED", async () => {
    const app = makeInviteApp();
    const res = await app.request("/api/explain/term/ask", json("POST", { term: "六张网" }));
    expect(res.status).toBe(403);
  });

  it("激活邀请码后可生成 3 个建议问题", async () => {
    const app = makeInviteApp();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ choices: [{ message: { content: '{"suggestions":["为什么要设置六张网，而不是七张网？","六张网分别指哪些？","六张网如何服务广东高质量发展？"]}' } }] }),
      { headers: { "content-type": "application/json" } },
    )));
    const code = await generateCode(app);
    await app.request("/api/invite/activate", json("POST", { code }));

    const res = await app.request("/api/explain/term/ask", json("POST", { term: "六张网", explanation: "广东基础设施体系" }));
    expect(res.status).toBe(200);
    expect((await readJson<{ suggestions: string[] }>(res)).data.suggestions).toHaveLength(3);
  });

  it("携带 question 时返回 Markdown 回答", async () => {
    const app = makeInviteApp();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ choices: [{ message: { content: "## 为什么是六张网\n\n六张网是广东交通、水利、能源等基础设施网络的统称。" } }] }),
      { headers: { "content-type": "application/json" } },
    )));
    const code = await generateCode(app);
    await app.request("/api/invite/activate", json("POST", { code }));

    const res = await app.request("/api/explain/term/ask", json("POST", { term: "六张网", question: "为什么是六张网而不是七张网？" }));
    expect(res.status).toBe(200);
    expect((await readJson<{ answer: string }>(res)).data.answer).toContain("六张网");
  });
});
