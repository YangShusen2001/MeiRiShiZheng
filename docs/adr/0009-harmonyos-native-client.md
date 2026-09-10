# ADR 0009：新增 HarmonyOS 原生客户端（复用现有 Worker，不改后端架构）

- 状态：**提议中**（待用户拍板）
- 关联：`0004`（当前产品架构）、`0008`（转向精选+记忆）、`0012`（Web 内容显示构建契约）、`docs/tasks/0027-harmonyos-native-client.md`
- 日期：2026-09-11

## 背景

用户要求「再开发一版鸿蒙版本」。已确认三项约束：

| 项 | 结论 |
|---|---|
| 技术路线 | **纯原生 ArkTS 重写**（不走 WebView 壳） |
| 后端 | **复用现有 Cloudflare Worker + D1**，不新建服务 |
| 环境 | 已有 DevEco Studio（本机可构建鸿蒙） |

### 现状事实（已核对源码）

1. **前端是纯静态站**：`apps/web/astro.config.mjs` 为 `output: "static"`，内容由 `apps/web/src/lib/content.ts` **在构建时**用 Node 读仓库根 `content/` 目录，烤进 HTML。
2. **内容 JSON 没有任何对外 HTTP 通道**。`content/` 是构建期文件系统输入，不是被服务的资源。**这是鸿蒙原生端的头号阻塞项**——原生端拿不到 `digest.json` / `article-*.json`。
3. **用户数据后端齐备**：`apps/api/src/app.ts` 已挂载 `/api/{auth,profile,favorites,highlights,practice,explain,invite,subscription,newsletter,webhooks,review}`，统一响应外壳 `{ ok, data, error }`，匿名身份走 `X-Device-Id` 头，登录态走 `kaogong_session` Cookie（`HttpOnly + Secure + SameSite=Lax`）。
4. **契约单一事实源已存在**：`packages/contracts/src/content.ts`（领域模型）+ `api.ts`（zod schema）；跨语言权威是 `content/schema/*.json`。鸿蒙端**必须复用这套字段定义，不得另立**。
5. **部署链路是本地手推**：`astro build` → `wrangler pages deploy dist`（见 `docs/deployment.md` §3、§7）。无 GitHub Actions 参与内容发布。

### 冲突点

`README` 与 ADR 0004 声明「静态内容读取零后端」。鸿蒙端要拿内容，**必然**需要一个内容分发通道。此处有三条候选路线（见「决策」）。

## 决策

### 1. 内容通道：构建期生成静态 JSON，**不新增基础设施**

新增构建脚本 `apps/web/scripts/build-content-api.mjs`，把仓库根 `content/` 产出到
`apps/web/public/content/`，随 `astro build` → Pages 部署一起上线，鸿蒙端直接 GET：

```text
https://<站点域>/content/manifest.json        # 清单：内容发现唯一入口（日期 / 文章 id / 卡片 / 主线）
https://<站点域>/content/policy-lines.json
https://<站点域>/content/cards.json
https://<站点域>/content/articles/{id}.json   # 扁平，对齐 Web 端 getArticle(id) 与 /read/{id}
https://<站点域>/content/{date}/digest.json
https://<站点域>/content/{date}/summary.json
https://<站点域>/content/{date}/practice.json
https://<站点域>/content/{date}/picks.json    # 存在时才有（策展槽位，见 ADR 0008）
```

文章路径取**扁平** `/articles/{id}.json` 而非 `/content/{date}/article-{id}.json`：
Web 端阅读入口是 `/read/{id}`（id 驱动，见 `lib/content.ts:132`），扁平路径让客户端不必先查日期，
也避免同一份文章 JSON 在产物里出现两次。

#### 为什么用脚本，而不是 Astro 路由端点

最初方案是 Astro 预渲染端点（`src/pages/content/**`）。实施时改为脚本，理由有三：

1. **可复用清洗逻辑且零重复**：`src/lib/content.ts` 的 `unescapeArticle` 负责把旧数据里的
   `&emsp;` / `&nbsp;` 等 HTML 实体清掉（实测 62 处，分布 7 篇文章）。Web 端渲染的是清洗后的文本，
   原生端必须拿到同一份，否则页面上会直接显示实体字面量。脚本用
   **Node ≥22.18 的原生 TS 类型剥离**直接 `import "../src/lib/content.ts"`，
   与 Web 端共用同一个函数，不存在两套实现漂移。
2. **路由复杂度更低**：扁平文章路径 + 逐日路径混用时，Astro 动态段（`[date]` / rest 参数）
   与静态段的优先级需要实测确认；脚本直接按目录结构写文件，URL 与源目录一一对应，没有猜测。
3. **可独立验证**：脚本只读 `content/`、写 `public/`，不依赖 `node_modules`，可单独运行并自校验。

脚本内置**自校验**（清单倒序、有 digest 必有文章、卡片与主线字段完整），不合法即 `exit 1`，
另配 `apps/web/test/content-api.test.ts` 对真实产物做断言（含「不把 `.bak` 备份带入产物」）。

方案比对：

| 候选 | 评价 |
|---|---|
| **构建期静态产物**（选定） | ✅ 单一事实源、零新增基础设施、天然跟着每日部署走；代价：内容是「构建时快照」 |
| Astro 预渲染端点 | ⚠️ 同样零基础设施，但清洗逻辑需跨模块复用、动态路由形状需实测；实施中改选上一行 |
| Worker `/api/content/*` 读 D1/R2 | ❌ 需新增存储与 pipeline 改动，违反「不为预期规模引入基础设施」 |
| 内容打进 HAP | ❌ 与「每日更新」根本冲突 |

**红线**：不新增 R2、不改 D1 表结构、不改 pipeline。本方案是纯 Web 侧增量。

### 2. 客户端身份与会话

- 匿名身份：鸿蒙端生成 UUID 存 `Preferences`，等价于 `apps/web/src/lib/device.ts` 的 `getOrCreateDeviceId`，请求带 `X-Device-Id`。
- 登录态：**沿用 `kaogong_session` Cookie**。原生端从 `/api/auth/email/verify` 的 `Set-Cookie` 提取 token 自行持久化，后续请求手动带 `Cookie` 头。理由：不改后端、不动现有 Web 会话语义。
  - 前置小改：Worker CORS 的 `allowHeaders` 增加 `Cookie`（原生请求无 Origin，实际不触发预检，但补齐以防中间层拦截）。
- **不引入** Bearer token 双轨制（除非实测发现 Cookie 路径在鸿蒙 HTTP 客户端不可行——那就回退到新增 `/api/auth/native/token`，并另开 ADR）。

### 3. 工程位置与边界

- 鸿蒙工程置于独立目录 **`apps/harmony/`**，与 `apps/web`、`apps/api` 平级，互不污染。
- 鸿蒙端**只读内容、只经 Worker 读写用户数据**；不得直连 D1、不得绕过 Worker。
- 契约变化一律先改 `packages/contracts`，再由两端各自消费。

### 4. 目标平台

- 首版**只做手机竖屏**，目标设备 nova 14 Pro（麒麟 8020）。
- API 版本对齐用户现有环境（DevEco Studio 26.0.0 Beta1 → API 26）；实际以 Phase 1 开工时本机 SDK 为准并回填本节。

## 不做什么

- ❌ 不做 WebView 壳/混合渲染（用户已明确否决）。
- ❌ 不新增基础设施（无 R2、无新 D1 表、无新 Worker 服务）。
- ❌ 不重写 pipeline，不动内容生产链路。
- ❌ 不做 embedding / 推荐系统（延续 ADR 0008）。
- ❌ 首版不做平板/折叠屏「一多」适配、不做多端流转。
- ❌ 首版不做上架/备案（先本地真机验证）。
- ❌ 不做 AI 解析的开源刷量（额度滥用风险，Phase 2 再议准入）。

## 后果

- Web 站新增 `/content/*` 静态产物：`apps/web/public/content/` 内容随构建进入 Pages，产物体积增加
  （实测当前仓库 195 篇文章 / 7 个内容日 ≈ 1.8 MB）。该目录已加入 `.gitignore`，不入库；
  `content/20*/` 的版权与体积约束不变。
- **构建要求 Node ≥ 22.18**：脚本依赖原生 TS 类型剥离导入 `src/lib/content.ts`。
  低于该版本时脚本会打印明确错误并 `exit 1`，不会静默产出坏产物。
- `packages/contracts` 新增 `ContentManifest` / `ContentManifestDay`：原生端的内容发现契约。
  它们描述的是**构建产物**而非 pipeline 产出，因此不加入 `content/schema/*.json`。
- 内容更新节奏 = 部署节奏：鸿蒙端看到的最新内容 = 最近一次 Pages 部署。若要求「不部署即更新」，需另立 ADR。
- 鸿蒙端与 Web 端共用同一套领域模型，**字段漂移风险由 `packages/contracts` 收敛**。
- 客户端须复刻 Web 端的一条渲染规则：`aiSummary` 与 `aiAnnotations` **仅在 `aiStatus === "ok"` 时使用**
  （见 `apps/web/src/pages/read/[id].astro:10-11`），否则显示原文。
