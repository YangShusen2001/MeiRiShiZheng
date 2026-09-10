# TASK-0027：HarmonyOS 原生客户端

## Status

in_progress — Phase 0 代码已完成并独立验证；待环境修复后跑全量门禁。Phase 1 未开工。

## Owner

待分配（超级架构师，用户验收）

## Dependencies

- `TASK-0012`（web 内容显示构建契约）——已完成
- `ADR 0009`（本任务架构依据）——待批准
- 用户环境：DevEco Studio（本机已具备）

## Goal

在**不新增基础设施、不改后端架构**的前提下，交付一个纯原生 HarmonyOS（ArkTS）客户端，复用现有 Cloudflare Worker + D1 与 `packages/contracts` 契约，让考生在鸿蒙设备上完成「读时政 → 看 AI 标注 → 收藏 / 划线 → 每日一练」的核心闭环。

先验证可行性（Phase 0 + Phase 1 MVP），确认后再推进账号与用户数据（Phase 2）。

---

## 关键事实（开工前必读，已核对源码）

| 事实 | 位置 | 对鸿蒙端的影响 |
|---|---|---|
| 前端 `output: "static"`，内容在**构建时**由 Node 读 `content/` | `apps/web/astro.config.mjs`、`src/lib/content.ts:28` | 内容 JSON 原本**无 HTTP 通道** → 已由 Phase 0 补上 |
| 旧数据含 HTML 实体（`&emsp;` 等 62 处 / 7 篇），Web 端构建时清洗 | `src/lib/content.ts:49-71` | 原生端必须取清洗后的同一份，否则显示实体字面量 |
| `aiSummary` / `aiAnnotations` 仅在 `aiStatus === "ok"` 时使用 | `src/pages/read/[id].astro:10-11` | 客户端须复刻该门控，不能无条件渲染标注 |
| 统一响应外壳 `{ ok, data, error }` | `apps/api/src/app.ts`、`src/lib/http.ts` | ArkTS HTTP 层按此封装 |
| 匿名身份 `X-Device-Id` + 登录态 `kaogong_session` Cookie | `src/lib/device.ts`、`src/routes/auth.ts:189` | 端侧需自管 deviceId 与 Cookie |
| 领域模型唯一定义在 `packages/contracts/src/content.ts` | 同上 | ArkTS 接口必须与之一一对应，禁止另立字段 |
| 阅读页含 AI 三色标注 / 关系箭头 / 划线 | `apps/web/src/pages/read/[id].astro`（1047 行）、`lib/reader-relations.ts`（255 行） | **最大工作量与最大风险点** |

---

## 仓库事实校正（2026-09-11，开工后核实）

用户提示「GitHub 上应该有最新的」，核查结论：**代码本地最新，内容远端最新，但远端内容是已退役管道的产物。**

### 分支拓扑

| 引用 | 最新提交 | 日期 | 代码 | 内容 |
|---|---|---|---|---|
| 本地 `public-release`（**当前工作分支**） | `7d2a384` | **8-21** | **最新**（未推送） | 7 天（8-12~8-21，策展） |
| GitHub `main`（默认分支） | `e3c1557` | 9-09 | 8-16 | **26 天（到 9-09）** |
| GitHub `public-release` | `1e866a7` | 8-18 | 8-18 | — |
| 本地 `main` / `origin/main` | `d0f5c3a` | 8-16 | 8-16 | — |

- `main` 与 `public-release` **无共同祖先**，两条独立历史；`main` 多 107 个提交。
- `origin/*` 远端引用自 8-16 / 8-18 起未 `fetch`，**已过期**。

### 为什么不能直接并远端内容

GitHub `main` 的每日内容是 **ADR 0007 已退役的自动聚合管道**输出，与当前产品线不符：

- 全仓 **0 个** `picks.json`；**无** `content/cards/`、**无** `content/policy-lines.json`。
- 抽样 `2026-09-09` 文章：`aiRelations: 0`、`aiCards: 0`、**无 `policyLine` 字段**、`keySentences: 0`。
- 每日 8–22 篇（对比 ADR 0008 的「2–5 篇精选」）。

→ **Phase 1 的内容基线继续用本地策展内容**；若需要更多演示体量，须由用户明确决定后再并入，
   并接受 `policyLine` / `aiCards` / 关系标注缺失导致的功能降级。

### 遗留问题处置（2026-09-11 用户决策：三项均按建议执行）

**① 内容基线 —— 定稿：继续用本地策展内容，不并入远端旧管道内容。**
理由见上节：远端 `main` 的 26 天内容缺 `picks` / `cards` / `policy-lines` / `policyLine` /
`aiCards` / `aiRelations`，属 ADR 0007 已退役形态，并入会导致功能降级。

**② 每日自动提交 —— 定稿：应关闭。已查明来源与影响范围。**

来源是 `main` 分支上的 GitHub Actions 工作流 `.github/workflows/daily.yml`：

- 触发：`cron: "0 22 * * *"`（UTC）= 北京时间每天 06:00，另有 `workflow_dispatch`。
- 行为：跑 Python 管道 → `git add content` → 以 `kaogong-bot` 提交「每日更新 YYYY-MM-DD」→
  随后构建前端并部署 Cloudflare Pages。
- **实测运行结论（Sep 2 ~ Sep 9 全部 `failure`）**：卡在「生产发布阻塞门禁」`pnpm release:check`，
  其后「安装前端依赖 / 构建前端 / **部署到 Cloudflare Pages** / 部署后冒烟」**全部 skipped**。
  → 该工作流**每天只产生内容提交，从未真正部署过**；关闭它不会影响线上发布。
- 关闭方式（需用户操作，本机 git 协议不通且无 GitHub token，无法代做）：
  GitHub 仓库 → Actions → 左侧 `daily` → **Disable workflow**。

**③ 未提交工作归属 —— 已处置：拆成两个提交入库。**

- 处置前：工作树有 **35 个已跟踪文件的修改 + 大量未跟踪资源**（185 支箭头 SVG、`vendor/`、
  `reader-relations.ts`、`policies`/`picks` schema 等），合计 247 个待提交文件，
  所在分支 `public-release` 与 `main` 分叉。
- 处置动作：先把 3 个「既有 WIP 与本次改动混合」的文件中属于本次的增量撤回，
  提交既有 WIP；再重新应用本次增量并单独提交。结果：

  | 提交 | 说明 | 文件数 |
  |---|---|---|
  | `8ba7a82` | `wip: 保全 public-release 上既有未提交工作（非本次任务产出）` | 247 |
  | `cb5eb8b` | `feat(harmony): Phase 0 内容分发层——为鸿蒙原生端提供内容通道` | 9 |

- 注意：`8ba7a82` 同时删除了 `docs/screenshots` 下 4 张截图（README 仍引用该路径），
  该删除来自既有工作树状态，未做判断；如需保留请另行恢复。
- `.workbuddy/`（项目记忆）仍为未跟踪，未纳入任何提交。

**④ 网络通道（备忘）**：git 协议不通（代理 21081 / 10655 均失效，直连被 reset）。
可用通道：`api.github.com`（200）、`codeload.github.com`（可下 tarball）；
`raw.githubusercontent.com` 不通。取远端内容可绕开 git：
`curl -sL -o kga.tar.gz https://api.github.com/repos/YangShusen2001/kaogong-cloud-v2/tarball/main`

---

## Phase 0：Web 侧内容通道（前置改造）

最小、可独立验证、不触碰用户数据。**已实施，待环境修复后跑门禁。**

### 范围

1. 新增构建脚本 `apps/web/scripts/build-content-api.mjs`，把 `content/` 产出到 `apps/web/public/content/`
   （清单见 ADR 0009 §决策1）。复用 `src/lib/content.ts` 的加载与清洗逻辑（Node ≥22.18 原生 TS 类型剥离）。
2. `packages/contracts/src/content.ts` 新增 `ContentManifest` / `ContentManifestDay`。
3. `apps/web/src/lib/content.ts` 增量导出 `listContentDates()`。
4. `apps/api/src/app.ts` CORS `allowHeaders` 增加 `Cookie`（原生端手工携带会话令牌）。
5. `apps/web/package.json` 接入 `prebuild` / `predev` / `content:api`。
6. `.gitignore` 忽略 `apps/web/public/content/`。
7. 构建产物断言测试 `apps/web/test/content-api.test.ts`；脚本内置自校验。

### Allowed Files

- `apps/web/scripts/build-content-api.mjs`（新增）
- `apps/web/test/content-api.test.ts`（新增）
- `apps/web/src/lib/content.ts`（仅增量导出 helper）
- `apps/web/package.json`、`.gitignore`
- `packages/contracts/src/content.ts`（仅新增类型）
- `apps/api/src/app.ts`（仅 `allowHeaders` 一行）

### Acceptance Criteria

- [x] 生成脚本可独立运行，产出 `manifest.json` / `policy-lines.json` / `cards.json` /
      `articles/{id}.json` / `{date}/{digest,summary,practice,picks}.json`。
- [x] 实测产物：195 篇文章 · 7 个内容日 · 30 张卡片 · 2 条主线 · 1.8 MB。
- [x] 文章正文与 Web 端清洗结果一致（抽查 3 篇旧数据，HTML 实体残留为 0）。
- [x] 清单不变量通过：`latestDate === days[0]`、按日倒序、有 digest 必有文章、文章 `date` 字段与目录一致。
- [x] 脚本内置自校验，产物不合法即 `exit 1`。
- [ ] `pnpm --filter @kaogong/web build` 后 `apps/web/dist/content/manifest.json` 存在且可解析。**（待环境修复）**
- [ ] `pnpm -r typecheck && pnpm -r test && pnpm -r build` 全绿。**（待环境修复）**
- [x] 未改动任何现有页面渲染行为。

### 阻塞项（环境，非代码）

`node_modules` 处于不完整状态（`.modules.yaml` 缺失、`.pnpm` 内符号链接悬空），
导致 `node` / `python` 访问 `node_modules` 报 `EACCES` / `WinError 1920`，
`astro build`、`vitest`、`tsc` 均无法运行。**这是修复前就存在的状态**（pnpm 在我运行任何命令前
就已检测到并试图重建 modules 目录）。修复需重装依赖，但 `pnpm install` 的批量删除
被安全护栏（`SAFE_DELETE_BULK_CONFIRM_REQUIRED`，10012 个文件 > 阈值 50）拦截，须由用户执行。

### Verification

```text
# 1) 内容通道（不依赖 node_modules，可立即验证）
node apps/web/scripts/build-content-api.mjs
node -e "console.log(Object.keys(require('./apps/web/public/content/manifest.json')))"

# 2) 环境修复（用户执行，需 >50 文件删除权限）
CI=true pnpm install --frozen-lockfile

# 3) 全量门禁
pnpm -r typecheck && pnpm -r test && pnpm -r build
```

---

## Phase 1：鸿蒙 MVP（最小可验证闭环）

**目标：证明「原生端能拿到内容 + 能正确渲染 AI 标注」这一核心命题。**

### 范围（只做这些）

- 新工程 `apps/harmony/`（独立目录）。
- 分层：`model`（对齐 contracts）/ `service`（HTTP + 内容）/ `viewmodel` / `view`。
- HTTP 层：`Envelope<T>` 解包、`X-Device-Id` 注入、超时与错误码映射。
- 持久化：`Preferences` 存 deviceId。
- 页面：
  1. **首页**：今日速览（一句话 + 关键词）+ 精选文章卡片列表。
  2. **阅读页**：原文分段渲染 + AI 标注三色高亮（`viewpoint` / `exam_point` / `term`，含 `figure`）+ 点击术语看释义。**只读**。
- 导航：`Navigation` + `NavPathStack`（不用已废弃的 `@ohos.router`）。

### 明确不做（Phase 1）

- ❌ 登录、收藏、划线、每日一练、错题本、AI 解析、订阅
- ❌ 离线缓存、桌面卡片、实况窗、推送
- ❌ 平板/折叠屏适配、横屏
- ❌ 上架打包

### Allowed Files

- `apps/harmony/**`（全部新增）
- 不改 `apps/web`、`apps/api`、`pipeline`、`content`

### Acceptance Criteria

- [ ] DevEco 构建零 ERROR，产物可安装到 nova 14 Pro。
- [ ] 首页能拉取 manifest + 最新 digest 并渲染（断网有明确错误态，不白屏）。
- [ ] 点卡片进阅读页，正文分段与 Web 端一致。
- [ ] AI 标注按类型正确着色；`term` 点击弹出释义；无释义时不伪造。
- [ ] 冷启动到首页首屏可交互（真机实测记一次数值，作为基线）。
- [ ] 无内存泄漏（页面退出释放 HTTP/监听资源）。

### Verification

```text
# 本机
hvigorw assembleHap --no-daemon
# 真机（nova 14 Pro）
hdc install -r entry-default-signed.hap
hdc shell aa start -a EntryAbility -b <bundleName>
# 内容通道连通性（先于 App 验证）
curl -s https://<站点域>/content/manifest.json | head -c 400
```

---

## Phase 2：账号与用户数据（MVP 验证通过后开工）

- QQ 邮箱验证码登录（Cookie 管理链路实测）。
- 收藏（article / quote / term 三类）、划线（本地优先 + 同步）、错题本。
- `Preferences` 落本地，`X-Device-Id` 与 Web 端语义一致。

**触发条件：Phase 1 全部验收项通过，且用户明确批准。**

---

## Phase 3：原生差异化能力（可选，非承诺）

候选（按价值排序，逐项单独确认）：

1. 离线缓存（已读文章 + 当天题集）
2. 桌面服务卡片（今日速览 / 每日一题）
3. 护眼主题（对齐 Web 端豆沙绿）
4. 每日一练提醒（`notificationManager` + 延时任务）
5. 实况窗（学习进度）

---

## 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 阅读页 AI 标注渲染复杂度（Web 端 1047 行 + 关系箭头 255 行） | **高** | Phase 1 只做三层标注着色，关系箭头推迟到 Phase 2；先跑通再叠加 |
| 鸿蒙 HTTP 客户端 Cookie 传递行为未实测 | **中** | Phase 1 先验匿名路径；登录路径在 Phase 2 开工时第一时间实测，失败则回退新增原生 token 端点并另开 ADR |
| ArkTS 严格类型导致的编译错误批量爆发（历史项目曾有 600+ 级联报错） | **中** | 严格遵循 ArkTS 规范：无 any/解构/对象字面量裸用；所有接口显式声明；分文件小步提交 |
| 商用字体未授权（Web 端已注明需自备） | **低** | 鸿蒙端首版用系统字体，不打包商用字体 |
| 内容为「部署时快照」，非实时 | **低** | 已接受（ADR 0009 §后果）；如需实时另立 ADR |
| 工作量低估（原生重写 > Web 改造） | **中** | 严格按 Phase 分批交付，每阶段独立验收，不合并推进 |

## 待用户拍板（仅 2 项）

1. **Phase 0 是否批准开工**（Web 侧新增 `/content/*` 静态端点）。
2. **Phase 1 范围是否认可**（首页 + 阅读页只读，不含登录/收藏/划线）。

---

## Handoff

### Phase 0

```text
任务：TASK-0027 Phase 0 —— Web 侧内容通道（原生客户端取数前置）
负责人：超级架构师
修改文件：
  apps/web/scripts/build-content-api.mjs         （新增，内容分发层生成器）
  apps/web/test/content-api.test.ts              （新增，构建产物断言）
  apps/web/src/lib/content.ts                    （增量：导出 listContentDates）
  apps/web/package.json                          （增量：content:api / predev / prebuild）
  packages/contracts/src/content.ts              （增量：ContentManifest / ContentManifestDay）
  apps/api/src/app.ts                            （增量：CORS allowHeaders += Cookie）
  .gitignore                                     （增量：忽略 apps/web/public/content/）
  docs/adr/0009-harmonyos-native-client.md       （新增）
  docs/tasks/0027-harmonyos-native-client.md     （新增）
实现内容：
  构建期把 content/ 产出为 public/content/ 下的静态 JSON，供鸿蒙原生端 GET。
  复用 src/lib/content.ts 的 listArticles/unescapeArticle/listCards/listPolicyLines，
  经 Node ≥22.18 原生 TS 类型剥离直接 import，清洗语义与 Web 端单点一致。
  产出 manifest.json（内容发现唯一入口）+ 逐日 digest/summary/practice/picks
  + 扁平 articles/{id}.json + cards.json + policy-lines.json；含陈旧文件清理与自校验。
契约变化：
  新增 ContentManifest / ContentManifestDay（描述构建产物，不进 content/schema/*.json）。
  未修改任何既有契约字段。
测试命令：
  node apps/web/scripts/build-content-api.mjs
  pnpm --filter @kaogong/web test          # 需先修复 node_modules
  pnpm -r typecheck && pnpm -r test && pnpm -r build
测试结果：
  生成器实跑通过：195 篇文章 · 7 个内容日 · 30 张卡片 · 2 条主线 · 1.8 MB。
  不变量核对通过：latestDate=2026-08-21、按日倒序、195 篇归并没遗漏、无空文章日、
  文章 date 字段与所属目录 100% 一致、抽查 3 篇旧数据 HTML 实体残留为 0。
  自校验（exit 1 分支）已生效。vitest / astro build / tsc 尚未运行（见已知问题）。
已知问题：
  node_modules 处于不完整状态（.modules.yaml 缺失、.pnpm 内符号链接悬空），
  node/python 访问 node_modules 报 EACCES / WinError 1920 → astro build、vitest、tsc 全部无法运行。
  该状态在本次改动之前就存在。修复需 CI=true pnpm install --frozen-lockfile，
  但其批量删除（10012 文件）被安全护栏 SAFE_DELETE_BULK_CONFIRM_REQUIRED 拦截，须用户执行。
下游 Agent 注意事项：
  1. 鸿蒙端取数入口只用 manifest.json，不要硬编码日期或文章 id。
  2. 文章走扁平 /content/articles/{id}.json（与 /read/{id} 同源）。
  3. 必须复刻 aiStatus === "ok" 门控，再渲染 aiSummary / aiAnnotations。
  4. 构建需 Node ≥22.18；低于该版本脚本会明确报错退出。
  5. 若删改 content/ 下内容，重跑生成脚本即可，陈旧产物会被自动清理。
是否满足验收标准：代码层面满足；门禁两项（astro build 产物、pnpm -r 三连）待环境修复后确认。
```
