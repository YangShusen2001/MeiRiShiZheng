/**
 * 云端端点配置。
 *
 * 开发期直连已部署服务（不在本地起 wrangler / astro）：
 * - 内容：Cloudflare Pages 静态站。`/content/*` 由 `apps/web/scripts/build-content-api.mjs`
 *   在构建期从仓库根 `content/` 生成，随 Pages 部署上线。
 * - 用户数据：Cloudflare Worker（Hono + D1）。
 *
 * 注意：`/content/*` 是 Phase 0 新增的分发层，**需要一次 Pages 部署才会在线上出现**。
 * 若尚未部署，首页会显示明确错误态而不是白屏。
 */
export class Endpoints {
  /** 内容站（Cloudflare Pages）。 */
  static readonly CONTENT_BASE: string = 'https://www.meirishizheng.cn';

  /** 用户数据 API（Cloudflare Worker）。 */
  static readonly API_BASE: string = 'https://api.meirishizheng.cn';

  static manifestUrl(): string {
    return `${Endpoints.CONTENT_BASE}/content/manifest.json`;
  }

  static articleUrl(articleId: string): string {
    return `${Endpoints.CONTENT_BASE}/content/articles/${articleId}.json`;
  }

  static digestUrl(date: string): string {
    return `${Endpoints.CONTENT_BASE}/content/${date}/digest.json`;
  }

  static summaryUrl(date: string): string {
    return `${Endpoints.CONTENT_BASE}/content/${date}/summary.json`;
  }

  /**
   * 跨日考点卡片（`content/cards/*.json` 合并产物）。
   * 是复习功能的题库来源——**与文章级 `aiCards` 不是同一条来源**，
   * 二者合并是内容侧的待办。
   */
  static cardsUrl(): string {
    return `${Endpoints.CONTENT_BASE}/content/cards.json`;
  }

  /**
   * AI 解析（Worker 侧 DeepSeek）。
   * 需带 `X-Device-Id` 头；服务端有配额与限流（匿名需邀请码，10 次/分钟）。
   */
  static explainUrl(): string {
    return `${Endpoints.API_BASE}/api/explain`;
  }

  /**
   * 术语追问。同一套配额与限流（匿名需邀请码，10 次/分钟）。
   * - 只传 `term` + `explanation`：返回**建议问题**（最多 3 条）；
   * - 再传 `question`：返回该问题的回答。
   */
  static termAskUrl(): string {
    return `${Endpoints.API_BASE}/api/explain/term/ask`;
  }

  /**
   * 收藏（跨端同步）。
   * 契约里 `favoriteKindSchema` 本来就有 `term`——术语是一等类型，
   * 不是硬塞进荧光笔的高亮模型。
   */
  static favoritesUrl(): string {
    return `${Endpoints.API_BASE}/api/favorites`;
  }

  /**
   * 邀请码激活。匿名用户以此获得 AI 解析额度（身份用 `X-Device-Id`）。
   * 响应：`{ ok: true, data: { active, remaining, code } }`。
   */
  static inviteActivateUrl(): string {
    return `${Endpoints.API_BASE}/api/invite/activate`;
  }
}
