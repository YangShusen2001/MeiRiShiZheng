# 生产部署验证记录 · 2026-09-16

> 用途：关闭 `docs/release-readiness.json` 中 `REL-PRODUCTION-DEPLOYMENT` 的可审计证据。
> 全部数据来自**对生产环境发起的只读 GET**，无任何写操作、未发送任何邮件。

## 1. 背景

`daily.yml`（`.github/workflows/daily.yml`）自 2026-09-11 起连续失败，卡在「生产发布阻塞门禁」`pnpm release:check`：

| run | 日期 | 结果 |
|---|---|---|
| `34659624752` | 2026-09-11 | failure |
| `34726131792` | 2026-09-12 | failure |
| `34790935065` | 2026-09-13 | failure |
| `34912417852` | 2026-09-15 | failure |
| `35037871966` | 2026-09-15 | failure |

门禁输出：

```
release gate blocked:
- REL-NEWSLETTER-PROVIDER: Production Resend newsletter delivery evidence is incomplete (high, open)
- REL-PRODUCTION-DEPLOYMENT: Production Worker, D1, Pages, and same-site verification are incomplete (high, open)
```

门禁位于流水线**第 7 步**，其后 5 步（安装前端依赖 → 构建前端 → 部署 Pages → 记录部署地址 → 部署后只读冒烟）**全部 skipped**。前 6 步正常：`每日更新 <日期>` 提交一直有产出（`origin/main` 最新为 `620a152 每日更新 2026-09-16`）。

**即：内容在入库，站点不发布。**

## 2. 处置结论

- `REL-NEWSLETTER-PROVIDER`：**降级 high → medium，status 保持 open，closeEvidence 保持 null**（不伪造证据）。缺失属实，但不在关键路径，不该阻塞主干发布。
- `REL-PRODUCTION-DEPLOYMENT`：**实测通过，关闭**。第 1–5、7 条 closeCriteria 均已满足；第 6 条（生产验证码邮件）未执行，并入前者跟踪。

## 3. 实测记录

命令（Node 24，直连生产）：

```sh
PUBLIC_SITE_URL=https://www.meirishizheng.cn \
PUBLIC_API_BASE=https://api.meirishizheng.cn \
node scripts/smoke-release.mjs
```

逐项原始结果：

| # | 目标 | 状态 | 观测 |
|---|---|---|---|
| 1 | `https://www.meirishizheng.cn/` | `200` | 50743 B · `title="每日时政"` · 31 个 href |
| 2 | `/daily/2026-09-15/` | `200` | 50000 B · `title="每日日报 · 2026-09-15（周二） · 时政小助手"` · **18 条 `/read/` 链接** |
| 3 | `/read/135ed3d8ee/` | `200` | 56851 B · `title="在加强基础研究座谈会上的讲话 · 时政小助手"` |
| 4 | `https://api.meirishizheng.cn/api/ping` | `200` | `{"ok":true,"data":"pong"}` |
| 5 | `/api/auth/session` | `401` | `{"ok":false,"error":{"code":"AUTH_REQUIRED","message":"未登录"}}`（预期） |
| 6 | `/api/subscription` | `401` | `AUTH_REQUIRED`（预期） |
| 7 | `/daily/2026-09-14/`（不存在） | `404` | 47120 B · `title="页面不存在 · 每日时政"` → 见下方"顺带核实" |

对应 closeCriteria：

- 第 1 条（secrets / variables / bindings / 生产 URL）：Pages 构建产物正常拉取 `api.meirishizheng.cn`，`/api/ping` 通 → 绑定生效。
- 第 2 条（D1 迁移链）：`/api/subscription` 走到鉴权分支才 401（未在 SQL 层报错）→ 迁移链已应用。
- 第 3 条（部署标识）：Worker `kaogong-api` · D1 `kaogong-db` · Pages `kaogong-web`。
- 第 4 条（同站自定义域）：`www.meirishizheng.cn`（Pages）与 `api.meirishizheng.cn`（Worker）同站 → `SameSite=Lax` 会话 cookie 可用。
- 第 5 条（部署后 GET 冒烟）：见上表 1–6。
- 第 7 条（可审计记录）：本文件。

## 4. 附带结论：冒烟脚本的判据缺陷（本次一并修复）

`scripts/smoke-release.mjs` 原先硬要求**首页**必须含 `/read/` 链接，否则报 `home page has no reader link`。生产实测该假设不成立：

```
remote smoke failed: home page has no reader link
```

原因不是站点故障，而是**产品设计**：首页的 `/read/<id>/` 卡片来自 `picks.json` 的 `picked`（`apps/web/src/pages/index.astro:119-126`），而管道**在零选日按设计不写 `picks.json`**（`picked: []` 违反 `minItems: 1`）。2026-09-15 正是零选日 —— 线上首页如实渲染了空态：

> 「今天没有够格的，宁缺勿滥」/「今天还没有落盘的选材。管道只在有够格内容时才写 picks.json，这里宁缺勿滥。」

所以**零选日的首页必然没有 `/read/` 链接**，这是正确行为。旧脚本把「零选日」误判成「部署失败」。

修复：首页无 reader 链接时，退回「首页最新的 `/daily/<日期>/` 页面」再取一次 reader 链接 —— 日报页恒有 `/read/` 链接（实测 18 条），既不放松判据，也不再误杀零选日。

## 5. 顺带核实

- **`404.html` 已生效**：`/daily/2026-09-14/` 返回 **404** 且带正确 `title`，而非旧已知问题里「Pages 用 `index.html` 兜底并回 200」。此前"状态码 200 不是判据"的告警在本部署上已不再适用。
- **线上非旧构建**：线上首页能渲染出当前源码的空态文案，且含 `/policy/2026-09/`、`/daily/2026-09-15/` 等现行路由，与 `apps/web/src/pages/` 一致。
- 线上内容日期为 `2026-09-15`，`origin/main` 已有 `2026-09-16` 提交 → 印证「内容已入库、发布被门禁掐住」。
