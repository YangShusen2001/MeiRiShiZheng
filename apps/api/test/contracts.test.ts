// 契约守门：2026-09-15 补的三项 —— 收藏 kind 加 `policy`、session 带 `avatar`、Profile 带 `createdAt`。
//
// 为什么放在 apps/api/test 而不是 packages/contracts：
// contracts 包只有 typecheck、没有跑 vitest 的设施；而 api 是这份契约最直接的消费者 ——
// 它既用 `favoriteCreateSchema` 校验入参，又构造出 `AuthUser` / `Profile` 这两份出参。
import { describe, expect, it } from "vitest";
import {
  authUserSchema,
  favoriteCreateSchema,
  favoriteKindSchema,
  favoriteSchema,
  profileSchema,
} from "@kaogong/contracts";

describe("favoriteKindSchema（加 policy）", () => {
  it("接受四类，含 2026-09-15 新增的 policy", () => {
    for (const k of ["article", "quote", "term", "policy"]) {
      expect(favoriteKindSchema.safeParse(k).success, k).toBe(true);
    }
  });

  it("仍然拒绝未知类型", () => {
    expect(favoriteKindSchema.safeParse("video").success).toBe(false);
    expect(favoriteKindSchema.safeParse("").success).toBe(false);
  });

  it("favoriteCreateSchema 接受 kind=policy，且无关字段落到默认空串", () => {
    const parsed = favoriteCreateSchema.safeParse({
      url: "https://www.gov.cn/zhengce/zhengceku/202609/content_7080190.htm",
      title: "石油天然气发展「十五五」规划",
      kind: "policy",
    });
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.kind).toBe("policy");
      // policy 用不到金句/术语三项 —— 路由据此把它们写空，避免污染幂等键
      expect(parsed.data.quote).toBe("");
      expect(parsed.data.termText).toBe("");
      expect(parsed.data.articleId).toBe("");
    }
  });

  it("favoriteSchema 能完整描述一条政策收藏", () => {
    const parsed = favoriteSchema.safeParse({
      id: "f-policy-1",
      url: "https://www.gov.cn/zhengce/zhengceku/202609/content_7080736.htm",
      title: "全民医疗保障「十五五」规划",
      source: "政策档案",
      note: "",
      kind: "policy",
      quote: "",
      termText: "",
      termExplanation: "",
      articleId: "",
      createdAt: 1757000000000,
    });
    expect(parsed.success).toBe(true);
  });
});

describe("authUserSchema（加 avatar）", () => {
  it("回传 avatar", () => {
    const parsed = authUserSchema.safeParse({ id: "u1", email: "12345@qq.com", avatar: "avatar-3" });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.avatar).toBe("avatar-3");
  });

  it("老响应缺 avatar 时落到空串 —— 前端据此回退邮箱哈希，不会渲染出一个空头像", () => {
    const parsed = authUserSchema.safeParse({ id: "u1", email: "12345@qq.com" });
    expect(parsed.success).toBe(true);
    if (parsed.success) expect(parsed.data.avatar).toBe("");
  });
});

describe("profileSchema（加 createdAt）", () => {
  const base = { name: "树森", email: "12345@qq.com", avatar: "avatar-1", subscribed: true };

  it("带 createdAt 时通过", () => {
    expect(profileSchema.safeParse({ ...base, createdAt: 1757000000000 }).success).toBe(true);
  });

  it("缺 createdAt 时**不**通过 —— 账户行那句「加入 YYYY-MM-DD」不许退回硬编码", () => {
    expect(profileSchema.safeParse(base).success).toBe(false);
  });
});
