import { expect, test, type Page } from "@playwright/test";
import { stubAnonymousSession } from "./helpers";

const explanation = "这一政策术语强调跨部门协同配置资源，以制度衔接提升公共治理的整体效能。";

async function serveArticleWithAi(page: Page) {
  await page.route("**/read/14588442ca/", async (route) => {
    const response = await route.fetch();
    let body = await response.text();
    body = body.replace('data-ai-status="legacy"', 'data-ai-status="ok"');
    body = body.replace(
      /(<script type="application\/json" id="ai-annotations">).*?(<\/script>)/,
      `$1${JSON.stringify([
        { id: "v1", paragraphIndex: 0, start: 0, end: 8, text: "从7月29日下午", type: "viewpoint" },
        { id: "e1", paragraphIndex: 0, start: 4, end: 12, text: "9日下午发现险情", type: "exam_point" },
        { id: "t1", paragraphIndex: 0, start: 8, end: 12, text: "发现险情", type: "term", explanation },
      ])}$2`,
    );
    await route.fulfill({ response, body });
  });
}

test("阅读模式切换展示三类 AI 标注并支持术语 hover/focus", async ({ page }) => {
  await stubAnonymousSession(page);
  await serveArticleWithAi(page);
  await page.route("**/api/highlights/paragraphs/*", (route) => route.fulfill({ json: {
    ok: true,
    data: [{
      paragraphIndex: 0,
      version: 1,
      highlights: [{
        id: "user-1",
        articleId: "14588442ca",
        paragraphIndex: 0,
        text: "下午发现",
        note: "",
        styles: ["green"],
        start: 6,
        end: 10,
        createdAt: Date.now(),
      }],
    }],
  } }));
  await page.route("**/api/highlights/paragraph", async (route) => {
    const body = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true, data: { version: 2, highlights: body.spans.map((span: object, index: number) => ({
      id: `user-${index + 2}`,
      articleId: body.articleId,
      paragraphIndex: body.paragraphIndex,
      createdAt: Date.now(),
      ...span,
    })) } } });
  });
  await page.goto("/read/14588442ca/");

  const article = page.locator("#article");
  await expect(page.getByRole("button", { name: "AI 标注模式" })).toBeEnabled();
  await expect(article.locator(".ai-viewpoint")).toHaveCount(0);
  await page.getByRole("button", { name: "AI 标注模式" }).click();
  await expect(article).toHaveAttribute("data-mode", "ai");
  await expect(article.locator(".ai-viewpoint").first()).toBeVisible();
  await expect(article.locator(".ai-exam-point").first()).toBeVisible();
  const term = article.locator(".ai-term[data-explanation]").first();
  await expect(term).toHaveAttribute("data-explanation", explanation);
  await term.hover();
  await expect.poll(() => term.evaluate((element) => getComputedStyle(element, "::after").visibility)).toBe("visible");
  await page.locator(".rd-title").hover();
  await expect.poll(() => term.evaluate((element) => getComputedStyle(element, "::after").visibility)).toBe("hidden");
  await term.focus();
  await expect(term).toBeFocused();
  await expect.poll(() => term.evaluate((element) => getComputedStyle(element, "::after").visibility)).toBe("visible");
  await page.getByRole("button", { name: "原文模式" }).focus();
  await expect.poll(() => term.evaluate((element) => getComputedStyle(element, "::after").visibility)).toBe("hidden");

  const overlap = article.locator("mark.hl-green.ai-term").first();
  await overlap.click();
  await page.getByRole("button", { name: "移除全部" }).click();
  await expect(article.locator(".ai-term").first()).toBeVisible();
  await page.getByRole("button", { name: "原文模式" }).click();
  await expect(article.locator(".ai-viewpoint")).toHaveCount(0);
  await expect(article.locator("mark.hl-green")).toHaveCount(1);
});

test("历史文章降级为原文且移动端无横向溢出", async ({ page }) => {
  await stubAnonymousSession(page);
  await page.route("**/api/highlights/paragraphs/*", (route) => route.fulfill({ json: { ok: true, data: [] } }));
  await page.goto("/read/14588442ca/");
  await expect(page.getByRole("button", { name: "AI 标注模式" })).toBeDisabled();
  await expect(page.locator("#ai-mode-status")).toContainText("暂时没有 AI 标注");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("首页文章卡片包含标题、来源、分类和摘要降级", async ({ page }) => {
  await stubAnonymousSession(page);
  await page.goto("/");
  const card = page.locator(".article-card").first();
  await expect(card.locator("h4")).not.toBeEmpty();
  await expect(card.locator(".article-card__meta span")).toHaveCount(2);
  await expect(card.locator("p")).not.toBeEmpty();
  await expect(card.locator("small")).toContainText(/AI 概括|内容提示/);
});
