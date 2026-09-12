# 提案 0012：阅读权限调整 + AI 解析邀请码 + 云端 bug 修复

> 状态：已批准并实现。用户 2026-08 审核结论：**邀请码 = 共享码**（多人共用、全局共享 100 次额度）；登录用户 AI 解释**不限次**；旧服务端划线**放弃迁移**；收藏 / 每日一练 / 错题本**保持服务端**；绑定粒度**登录绑账号、未登录绑设备**。

## 1. 背景

用户反馈：部署到云端后出现 3 个功能问题，并提出 4 项新需求。

- 问题：AI 解析不可用、加粗不可用、错题加载失败。
- 需求：默认主题改护眼；默认选择「AI 标注模式」；查看 AI 解析等无需登录、划线保存在本地、只有「AI 解析」需要登录或邀请码（邀请码 = 100 次 AI 解析，后台生成并记录剩余次数）。

## 2. 调研结论

### 2.1 相关现状（代码定位）

| 功能 | 现状 | 关键文件 |
|---|---|---|
| AI 解释（划线选中→AI 解释） | `POST /api/explain`：仅需 `x-device-id` + 每设备限流 10 次/分 + `DEEPSEEK_API_KEY`，**无登录要求** | `apps/api/src/routes/explain.ts` |
| AI 速览 / AI 标注（查看 AI 解析） | 静态渲染，来自 `content/` 的 article JSON，**无登录要求（已公开）** | `apps/web/src/pages/read/[id].astro` |
| 划线 | **服务端存储**（`highlights` / `highlight_paragraphs` 表，owner = 登录用户或设备 id），前端走 `listHighlightParagraphs` / `replaceHighlightParagraph` | `apps/api/src/routes/highlights.ts`、`read/[id].astro` |
| 主题 | `light`（默认）/ `reading` / `green`（护眼），localStorage 记忆 | `apps/web/src/layouts/Base.astro` |
| AI 标注模式 | 按钮默认禁用、`setAiMode(false)`，需手动点开 | `read/[id].astro` |
| 错题本 | `wrong_questions` 表（**migration 0016**），`GET /api/practice/wrong` | `apps/api/src/routes/practice.ts` |

### 2.2 Bug 根因判断

1. **AI 解析不可用**：`explain.ts` 在 `config.deepseekKey` 为空时返回 503「未配置 DeepSeek API Key」。`DEEPSEEK_API_KEY` 是 **Worker secret**（不在 `wrangler.toml` 的 `[vars]` 里），需通过 `wrangler secret put DEEPSEEK_API_KEY` 或 Dashboard 注入。生产 Worker 很可能没配这个 secret（GitHub Actions 里那份 key 只用于「内容管道出题」，与 Worker 运行时无关）。**结论：运维配置缺失，非代码 bug。**
2. **错题加载失败**：`wrong_questions` 表由最新 migration **0016** 创建。若远程 D1 未执行 `wrangler d1 migrations apply kaogong-db --remote`（0016 之后），`GET /api/practice/wrong` 会因「no such table」返回 500 → 前端显示「错题加载失败」。**结论：D1 迁移未应用到远程，非代码 bug。**
3. **加粗不可用**：`mark.hl-bold { font-weight: 700 }` CSS 已存在，`HighlightStyle` 契约也含 `bold`，且 bold 与荧光笔/下划线走**同一条** `applyStyle → reconcileParagraph → 服务端保存` 路径。静态代码中未找到 bold 独有的缺陷；最可能是**服务端划线保存链路在云端不可用**（表未迁移/往返失败时 `highlightsLoaded` 恒为 false，所有划线动作被「划线仍在加载」拦截），或 bold 仅改字重、无背景，视觉上不易察觉被误判。**本次把划线改成本地存储后，bold 将走纯前端路径并补单测，一并解决与验证。**

> 注：AI 速览 / AI 标注（「查看 AI 解析」）当前**已是公开**（静态内容、无登录门），需求「所有人都能查看」无需改动，仅需确认。

## 3. 方案设计

### 3.1 默认主题 → 护眼

- `apps/web/src/layouts/Base.astro` 中主题默认值 `"light"` → `"green"`（两处：head 内提前应用脚本、主题切换按钮的初始索引）。
- 用户仍可手动切回默认/阅读主题，localStorage 记忆不变。

### 3.2 默认「AI 标注模式」

- `apps/web/src/pages/read/[id].astro`：当 `aiAvailable`（AI 标注存在且校验通过）时，默认 `setAiMode(true)`；AI 不可用时仍回原文模式（按钮禁用）。初始按钮态同步。

### 3.3 权限模型（目标）

| 功能 | 目标 |
|---|---|
| 查看 AI 速览 / AI 标注 | 公开（现状不变，确认即可） |
| 划线（荧光笔/下划线/加粗） | **本地 localStorage**（移除服务端读写） |
| AI 解释（划线选中→AI 解释） | **登录 或 邀请码**（登录不限次；未登录需激活邀请码，每码 100 次） |
| 收藏 / 每日一练 / 错题本 | 保持服务端（owner = 登录用户或设备 id），仅修错题迁移 |

### 3.4 划线本地化

- 用 `localStorage` 存「按 articleId + paragraphIndex 的 spans」结构（等价于 `highlightParagraphs`，但不含 version/owner）。
- 删除 `api.listHighlightParagraphs` / `api.replaceHighlightParagraph` 调用及 `highlightsLoaded`/版本冲突逻辑；保留纯函数 `applyStyle / buildSegments / readerSegmentsToHtml`（这些已是纯函数、有单测基础）。
- 用户此前在服务端的旧划线**不迁移**（本地从空开始，简单且避免双写）。
- 补 bold 渲染单测（确认 `hl-bold` 输出 + `font-weight` 生效）。

### 3.5 AI 解释邀请码

**模型（推荐，见第 6 节待确认）**：登录用户不限次；未登录用户需先「激活」一个邀请码（单码单绑），绑定到当前设备 id，之后每次 AI 解释从该码剩余次数扣 1，扣完需登录或换新码。

- **新表** `invite_codes`（migration 0017）：
  - `code`（text PK，随机码）、`remaining`（int，默认 100）、`total`（int，默认 100）、`owner_id`（text，可空，激活时写入设备/用户 id）、`created_at`（int）。
- **契约**（`packages/contracts/src/api.ts`）：
  - `inviteActivateSchema { code }`、`inviteStatusSchema { remaining, active }`、`adminInviteCodeSchema { code, total, remaining, ownerId, createdAt }`。
- **Worker 新路由**：
  - `POST /api/admin/invite-codes`（`x-job-secret` 鉴权）→ 生成一个 100 次邀请码，返回明文码（仅此一次）。
  - `GET /api/admin/invite-codes`（`x-job-secret`）→ 列出全部码及剩余次数（后台展示）。
  - `POST /api/invite/activate`（`{ code }`）→ 校验未绑定 → 绑定到当前 owner（登录用户 `user:*` 或设备 `device:*`）→ 返回 `{ remaining }`；已被他人绑定返回 409。
  - `GET /api/invite/status` → 返回当前 owner 的剩余次数（无则 `{ remaining: 0, active: false }`）。
  - `POST /api/explain` 改造：登录用户直接放行；否则查当前 owner 绑定的邀请码，`remaining > 0` 则扣减后放行，否则 402 `INVITE_REQUIRED` / `QUOTA_EXHAUSTED`。
- **前端**（阅读页）：
  - 点击「AI 解释」时：已登录 → 直接请求；未登录 → 先查 `/api/invite/status`，无额度则弹输入框填写邀请码 → `/api/invite/activate` → 成功后继续解释；显示「剩余 N 次」。
  - 邀请码存 localStorage，同设备复用。
- **后台（Python 审核服务）**：
  - 新增「邀请码」面板：生成 + 列表（含剩余次数）。
  - `server.py` 新增 `GET/POST /api/invite-codes` 代理，转发到生产 Worker 的 admin 接口（`x-job-secret` 鉴权）；需在审核服务环境配置 `JOB_SECRET`（复用已有的 `PUBLIC_API_BASE`，默认 `https://api.meirishizheng.cn`）。
  - `ui/index.html` 顶部导航加「🔑 邀请码」按钮 + 面板。

### 3.6 错题修复（运维）

- 执行 `cd apps/api && npx wrangler d1 migrations apply kaogong-db --remote`（应用 0016，以及本次新增的 0017）。
- 前端 `wrong.astro` 错误提示细化：区分「加载失败（网络/服务）」与「暂无错题」，避免误导。

## 4. 部署/运维清单（修复云端问题的必要步骤）

1. Worker secret 补齐：`DEEPSEEK_API_KEY`（AI 解释）、`AUTH_SECRET`、`JOB_SECRET`（邀请码后台鉴权）——`wrangler secret put` 或 Dashboard。
2. 远程 D1 迁移：`wrangler d1 migrations apply kaogong-db --remote`（0016 错题 + 0017 邀请码）。
3. 重新部署 Worker：`cd apps/api && npx wrangler deploy`。
4. 前端重新构建发布（`PUBLIC_API_BASE` 已指向 `https://api.meirishizheng.cn`）。

## 5. 测试计划

- API：邀请码生成/激活/重复激活/扣减/耗尽；explain 的「登录放行 / 邀请码放行 / 无额度拒绝」。
- Web：bold 渲染（`hl-bold` 输出 + 字重）、划线 localStorage 存取、默认护眼主题、默认 AI 标注模式。
- 全量门禁：`pnpm -r typecheck && pnpm -r test && pnpm -r build`。

## 6. 待确认（关键决策，审核时请一并答复）

1. **邀请码语义**：单码单绑（一个码激活后绑定到首个设备，100 次额度归它，推荐）还是共享码（多人共用一个码、共享 100 次）？本文按「单码单绑」设计。
2. **登录用户 AI 解释是否限次**：本文按「登录不限次」设计；是否需要给登录用户也设配额（如每日 N 次）？
3. **旧服务端划线**：是否放弃迁移、本地从空开始（推荐，简单）？
4. **收藏 / 每日一练 / 错题本**：保持服务端（本文假设）还是也要本地化？
5. **邀请码绑定粒度**：绑定「设备」（换设备/清缓存即失效）还是绑定「登录账号」（登录后跨设备可用）？本文按「登录绑账号、未登录绑设备」设计。

## 7. 影响范围

- 前端：`apps/web/src/layouts/Base.astro`、`apps/web/src/pages/read/[id].astro`、`apps/web/src/lib/api.ts`（可能）、`apps/web/src/pages/wrong.astro`、`apps/web/src/styles/global.css`（如有需要）。
- 契约：`packages/contracts/src/api.ts`。
- 后端：`apps/api/src/routes/explain.ts`、新增 `apps/api/src/routes/invite.ts`（或并入）、`apps/api/src/db/schema.ts`、`apps/api/drizzle/0017_*.sql`、`apps/api/src/app.ts`。
- 后台：`pipeline/src/kaogong/review/server.py`、`pipeline/src/kaogong/review/ui/index.html`。
- 文档：`docs/deployment.md`（补 secret + 迁移步骤）。
