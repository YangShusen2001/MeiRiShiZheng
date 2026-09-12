import { expect, test, type Page, type Route } from "@playwright/test";

const ok = (data: unknown) => ({ ok: true, data });
const fail = (code: string, message: string) => ({ ok: false, data: null, error: { code, message } });

async function serveAnonymousSession(page: Page) {
  await page.route("**/api/auth/session", (route) => route.fulfill({
    status: 401,
    json: fail("AUTH_REQUIRED", "未登录"),
  }));
}

async function serveAuthenticatedSession(page: Page) {
  await page.route("**/api/auth/session", (route) => route.fulfill({
    json: ok({ id: "user-1", email: "123456@qq.com" }),
  }));
}

async function fulfillProfile(route: Route) {
  await route.fulfill({
    json: ok({ name: "小考", email: "123456@qq.com", avatar: "avatar-3", subscribed: false }),
  });
}

test("验证码登录展示请求状态并保留可重试错误", async ({ page }) => {
  await serveAnonymousSession(page);
  let releaseCodeRequest: (() => void) | undefined;
  const codeRequestReleased = new Promise<void>((resolve) => {
    releaseCodeRequest = resolve;
  });
  await page.route("**/api/auth/email/code", async (route) => {
    await codeRequestReleased;
    await route.fulfill({ json: ok({ message: "验证码已发送" }) });
  });
  await page.route("**/api/auth/email/verify", (route) => route.fulfill({
    status: 400,
    json: fail("CODE_INVALID", "验证码错误，请重试"),
  }));

  await page.goto("/login/");
  await expect(page.getByLabel("验证码")).toBeHidden();
  await page.getByLabel("QQ 邮箱").fill("123456@qq.com");
  await page.getByRole("button", { name: "发送验证码" }).click();
  const submit = page.getByRole("button", { name: "正在发送…" });
  await expect(submit).toBeDisabled();
  releaseCodeRequest?.();
  await expect(page.getByLabel("验证码")).toBeVisible();
  await expect(page.locator("#auth-status")).toContainText("验证码已发送");

  await page.getByLabel("验证码").fill("000000");
  await page.getByRole("button", { name: "验证并登录" }).click();
  await expect(page.getByRole("alert")).toContainText("验证码错误，请重试");
  await expect(page.getByRole("button", { name: "验证并登录" })).toBeEnabled();
});

test("移动端导航通过菜单按钮展开且不产生横向溢出", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await serveAnonymousSession(page);

  await page.goto("/login/");
  const menu = page.locator("#nav-toggle");
  await expect(menu).toBeVisible();
  await expect(menu).toHaveAccessibleName("打开菜单");
  await expect(page.getByRole("navigation")).toBeHidden();
  await menu.click();
  await expect(page.getByRole("navigation")).toBeVisible();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await expect(menu).toHaveAccessibleName("关闭菜单");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("个人资料保存与不可用的摘要订阅相互独立", async ({ page }) => {
  await serveAuthenticatedSession(page);
  let subscriptionPosts = 0;
  await page.route("**/api/profile", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { name: string; avatar: string };
      await route.fulfill({
        json: ok({ ...body, email: "123456@qq.com", subscribed: false }),
      });
      return;
    }
    await fulfillProfile(route);
  });
  await page.route("**/api/subscription", async (route) => {
    if (route.request().method() === "POST") subscriptionPosts += 1;
    await route.fulfill({ json: ok({ subscribed: false, deliveryAvailable: false }) });
  });

  await page.goto("/profile/");
  const subscription = page.getByLabel("订阅 QQ 邮箱通知");
  const selectedAvatar = page.locator(".avatar-opt.on");
  await expect(selectedAvatar).toHaveAttribute("aria-pressed", "true");
  await expect(subscription).toBeDisabled();
  await expect(page.getByText("摘要邮件暂不可用")).toBeVisible();

  await page.getByLabel("姓名").fill("新姓名");
  await page.getByRole("button", { name: "保存个人资料" }).click();
  await expect(page.locator("#p-msg")).toContainText("个人资料已保存");
  expect(subscriptionPosts).toBe(0);
});

test("投递不可用时仍允许现有订阅用户退订", async ({ page }) => {
  await serveAuthenticatedSession(page);
  await page.route("**/api/profile", fulfillProfile);
  await page.route("**/api/subscription", async (route) => {
    if (route.request().method() === "POST") {
      expect(route.request().postDataJSON()).toEqual({ subscribed: false });
      await route.fulfill({ json: ok({ subscribed: false, deliveryAvailable: false }) });
      return;
    }
    await route.fulfill({ json: ok({ subscribed: true, deliveryAvailable: false }) });
  });

  await page.goto("/profile/");
  const subscription = page.getByLabel("订阅 QQ 邮箱通知");
  await expect(subscription).toBeEnabled();
  await expect(subscription).toBeChecked();
  await subscription.uncheck();
  await page.getByRole("button", { name: "保存订阅设置" }).click();
  await expect(page.locator("#p-sub-msg")).toContainText("已退订每日摘要");
  await expect(page.locator("#p-sub-availability")).toContainText("恢复投递后才能订阅");
  await expect(subscription).toBeDisabled();
});

test("退出失败时保留当前会话并显示错误", async ({ page }) => {
  await serveAuthenticatedSession(page);
  await page.route("**/api/auth/logout", (route) => route.fulfill({
    status: 503,
    json: fail("AUTH_UNAVAILABLE", "退出失败，请重试"),
  }));

  await page.goto("/");
  const menu = page.locator("#nav-toggle");
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("button", { name: "退出" }).click();
  await expect(page.getByRole("button", { name: "退出" })).toBeEnabled();
  await expect(page.getByText("退出失败，请重试")).toBeVisible();
  await expect(page.getByRole("link", { name: "123456" })).toBeVisible();
});
