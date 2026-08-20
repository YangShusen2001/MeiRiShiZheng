# 提案 0015：项目开源（合规清理 + 高 Star 项目规范）

> 状态：待审核。目标：把 kaogong-cloud-v2 开源，先做「合规清理」再补「高 Star 项目规范」，避免开源即翻车（密钥泄露 / 版权风险 / 个人信息 / 商用字体）。

## 1. 背景

- 项目已上线 `www.meirishizheng.cn`，代码在本地 `kaogong-cloud-v2`（绿场重构，与旧仓库隔离）。
- 简历需要「项目代码」链接 → 需要一个公开仓库。
- 开源前必须先清理：真实密钥、真实域名、个人路径、抓取的官方文章全文、商用字体。

## 2. 合规清理清单（按风险等级）

### 2.1 高危：真实凭据与域名

| 文件 | 现状 | 处理 |
|---|---|---|
| `.env.local` | 真实 `DEEPSEEK_API_KEY` / `CLOUDFLARE_API_TOKEN` / `JOB_SECRET` 等 | 已被 `.gitignore` 覆盖 ✅；再确认一次 `git status` 不含它 |
| `apps/api/wrangler.toml` | **真实 D1 `database_id`** + 真实域名 `api.meirishizheng.cn` / `ALLOWED_ORIGINS` / `MAIL_FROM` | 改为占位：`api.example.com`、`database_id = "REPLACE_ME"`、`MAIL_FROM = "noreply@example.com"` |
| `docs/deployment.md` | 个人账号的 workers.dev 域名 + 本地绝对路径 | 改为 `https://api.example.com` + 相对路径说明 |
| `README.md` | 本地旧仓库的绝对路径 | 删除该行或改写为「参考/备份仓库」 |
| `启动审核.bat` | 硬编码 `D:\kaogong-cloud-v2` | 改为相对路径（`%~dp0`）或说明 |

### 2.2 高危：抓取的官方文章全文（版权）

- `content/2026-08-12 ~ 2026-08-17`：约 **145 篇官方文章全文 + digest + 质量报告**（人民网/新华网/南方网等）。
- 风险：把官方文章全文再分发到开源仓库有版权问题；高 Star 项目不这么干。
- 处理：**`content/2026-*` 与 `content/_reports/` 全部 gitignore**；保留 `content/schema/*.json`（契约，无版权问题）+ 一份**示例内容**（脱敏或自造样例，见待确认 2）。

### 2.3 中危：商用字体（版权）

- `apps/web/public/fonts/`：`HYXiaoYaoYouJ-2.ttf`（24MB，汉仪）、`maozedong-1.ttf`（2MB）、`AaXiangSuJiangHu-Ying-2.woff2`、`PingFangFangMaoTiCaoShu-logo.woff2` 等**商用字体**，附授权不明，**不能进开源仓库**。
- 处理：gitignore `apps/web/public/fonts/uploads/` 与固定字体文件；README 注明「字体需自备授权，默认回退系统字体」；删除 `bad.ttf`（10B 垃圾文件）。
- 前端 `Base.astro` / `global.css` 已做字体缺失回退（`@font-face` 失败走系统字体），开源版可直接运行。

### 2.4 低危：杂物

- `.omo/`（未跟踪目录）、`pipeline/_test_subset.woff2`、`scripts/local-daily.bat` → 清理或 gitignore。

### 2.5 清理后验证

- `git grep` 敏感词：`DEEPSEEK_API_KEY=sk-`、`CLOUDFLARE_API_TOKEN`、`meirishizheng`、本地用户名、真实 `database_id` → 0 命中。
- 用 **fresh clone** 跑 `pnpm install && pnpm -r typecheck && pnpm -r test`，确认开源仓库可独立运行（无 content 数据时管道测试用 fixture，应可过）。

## 3. 高 Star 项目规范（参考惯例）

### 3.1 README 结构（重写）

```text
- 顶部：项目名 + 一句话定位 + 徽章区（license / tests / astro build）
- 在线 Demo 链接（www.meirishizheng.cn）+ 2~4 张截图（首页 / 阅读页 AI 标注模式 / 每日一练 / 审核 Agent 面板）
- 特性列表（勾选式，突出：AI 概括 / 三类标注 / AI 划线解析 / 审核 Agent / 多 Agent 开发）
- 快速开始（本地 3 步跑起来：pnpm install → 起 api → 起 web）
- 架构图（已有 mermaid）+ 技术栈表（已有）
- 目录结构（已有）+ 文档链接（docs/）
- License 段
```

### 3.2 配套文件

| 文件 | 内容 |
|---|---|
| `LICENSE` | 待确认：MIT 或 Apache-2.0（建议 MIT，高 Star 最常见） |
| `CONTRIBUTING.md` | 开发流程、Agent 协作规则（引用 `AGENTS.md`）、测试要求 |
| `CODE_OF_CONDUCT.md` | 贡献者行为准则（标准模板） |
| `SECURITY.md` | 安全漏洞披露方式 |
| `.github/` | 已移除（2026-08 起纯本地审核，不再使用 GitHub Actions） |

### 3.3 GitHub 仓库设置

- description：`面向公务员考试的时政 AI 阅读站：Astro + Hono Workers + D1，AI 概括/标注/审核 Agent`
- topics：`ai-agent`、`llm`、`cloudflare-workers`、`d1`、`astro`、`python`、`zod` 等

## 4. 执行步骤

1. **清理**：gitignore 内容/字体/杂物 + 占位化 wrangler.toml/文档/批处理。
2. **规范**：新增 LICENSE / CONTRIBUTING / CODE_OF_CONDUCT / SECURITY，重写 README。
3. **验证**：fresh clone 全量测试 + 敏感词扫描。
4. **发布**：首次 push + GitHub 仓库设置（description/topics）。
5. **回填简历**：把公开仓库地址写进「项目代码」。

## 5. 待确认决策

1. **License**：MIT（最宽松、高 Star 常见）还是 Apache-2.0？（建议 MIT）
2. **示例内容**：保留 1 篇「可转载/无版权争议」的真实文章作为 demo，还是造一份脱敏样例？（建议：自造 1 份样例 digest + 文章，零风险）
3. **审核 Agent 黄金标准文档**（`docs/product/review-judging-rubric.md`，内部经验）是否随仓库公开？（建议公开，是亮点，无敏感信息）
4. **仓库名**：`kaogong-cloud-v2` 还是对外名（如 `kaogong-daily` / `shizheng-ai-reader`）？（建议换个对外名，v2 后缀不对外）
