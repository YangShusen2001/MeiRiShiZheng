// 账号数据导出与注销（第二批 B3）。用 authenticatedContext 拿真实会话 ——
// 注销要求登录态，device 身份不允许注销。
import { describe, expect, it } from "vitest";
import type { AccountExport, Favorite } from "@kaogong/contracts";
import { favorites, sessions, users, wrongQuestions } from "../src/db/schema";
import { headers, readJson } from "./helpers";
import { authenticatedContext } from "./newsletter-test-helpers";

const wrongInput = {
  question: "题干",
  options: ["A", "B", "C", "D"],
  answer: 0,
  chosen: 1,
  analysis: "解析",
};

describe("账号数据导出与注销", () => {
  it("导出把该账号的各表原样带出", async () => {
    const { app, cookie } = await authenticatedContext();
    const auth = { ...headers(), cookie };
    const post = (body: unknown) => ({
      method: "POST",
      headers: { ...headers(), "content-type": "application/json", cookie },
      body: JSON.stringify(body),
    });

    await app.request("/api/favorites", post({ url: "https://example.com/a", title: "标题", kind: "article" }));
    await app.request("/api/practice", post({ date: "2026-09-15", correct: 0, total: 1, wrong: [wrongInput] }));

    const res = await app.request("/api/account/export", { headers: auth });
    expect(res.status).toBe(200);
    const data = (await readJson<AccountExport>(res)).data;
    expect(data.profile?.email).toBe("123456@qq.com");
    expect(data.owner).toBeTypeOf("string");
    expect(data.exportedAt).toBeTypeOf("number");
    expect(data.favorites).toHaveLength(1);
    expect(data.favorites[0]?.title).toBe("标题");
    expect(data.practice).toHaveLength(1);
    expect(data.wrongQuestions).toHaveLength(1);
  });

  it("注销必须原样传确认词 —— 传别的会被拒，且数据原封不动", async () => {
    const { app, cookie } = await authenticatedContext();
    await app.request("/api/favorites", {
      method: "POST",
      headers: { ...headers(), "content-type": "application/json", cookie },
      body: JSON.stringify({ url: "https://example.com/a", title: "标题", kind: "article" }),
    });

    for (const bad of [{ confirm: "注销" }, { confirm: "delete" }, {}]) {
      const res = await app.request("/api/account", {
        method: "DELETE",
        headers: { ...headers(), "content-type": "application/json", cookie },
        body: JSON.stringify(bad),
      });
      expect(res.status, JSON.stringify(bad)).toBe(400);
    }

    const still = await app.request("/api/favorites", { headers: { ...headers(), cookie } });
    expect((await readJson<Favorite[]>(still)).data).toHaveLength(1);
  });

  it("确认词正确时连根清空：账号 / 会话 / 各 owner 维度的数据", async () => {
    const { app, db, cookie } = await authenticatedContext();
    const post = (body: unknown) => ({
      method: "POST",
      headers: { ...headers(), "content-type": "application/json", cookie },
      body: JSON.stringify(body),
    });
    await app.request("/api/favorites", post({ url: "https://example.com/a", title: "标题", kind: "article" }));
    await app.request("/api/practice", post({ date: "2026-09-15", correct: 0, total: 1, wrong: [wrongInput] }));
    await app.request("/api/notifications", post({ dailyEnabled: true }));
    expect(await db.select().from(users).all()).toHaveLength(1);
    expect(await db.select().from(sessions).all()).toHaveLength(1);

    const res = await app.request("/api/account", {
      method: "DELETE",
      headers: { ...headers(), "content-type": "application/json", cookie },
      body: JSON.stringify({ confirm: "注销账号" }),
    });
    expect((await readJson<null>(res)).ok).toBe(true);

    // 直接查库：账号、会话、以及 owner 维度的收藏/错题都得没
    expect(await db.select().from(users).all()).toHaveLength(0);
    expect(await db.select().from(sessions).all()).toHaveLength(0);
    expect(await db.select().from(favorites).all()).toHaveLength(0);
    expect(await db.select().from(wrongQuestions).all()).toHaveLength(0);
  });

  it("未登录（只有设备身份）不能注销", async () => {
    const { app } = await authenticatedContext();
    // 不带 cookie，只有 x-device-id
    const res = await app.request("/api/account", {
      method: "DELETE",
      headers: { ...headers(), "content-type": "application/json" },
      body: JSON.stringify({ confirm: "注销账号" }),
    });
    expect(res.status).toBe(401);
  });
});
