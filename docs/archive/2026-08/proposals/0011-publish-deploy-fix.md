# 提案 0011：修复本地「发布到 CF」失败

- **状态**：待评审
- **日期**：2026-08-16
- **范围**：`pipeline/src/kaogong/review/server.py`、`.env.local`（示例）、`docs/deployment.md`

## 背景

用户在本地审核后台点「🚀 发布到 CF」失败。发布链路是 `api_publish`：质量门禁 → `npx astro build` → `npx wrangler pages deploy`。

## 已确认问题（根因）

### P1：本地缺 Cloudflare 凭证（部署认证失败）

`.env.local` 目前只有 `DEEPSEEK_API_KEY` 和 `PUBLIC_API_BASE`，**没有 `CLOUDFLARE_API_TOKEN` 和 `CLOUDFLARE_ACCOUNT_ID`**。`wrangler pages deploy` 需要这两项做认证，缺失时直接报英文 `auth required / 未登录`，部署必然失败。

CI（`daily.yml`）用的是 GitHub Secrets（`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`），本地跑审核服务没有这些，所以本地部署永远通不过。

### P2：`npx` 绕过了 pnpm 脚本 + 工具解析不稳

`_run` 用 `npx astro build`（跳过 `package.json` 的 `prebuild` 前置检查）和 `npx wrangler pages deploy`。项目用 pnpm 管理，`npx` 可能解析到错误版本或触发联网下载；且 `npx astro build` 不执行 `prebuild`（`PUBLIC_API_BASE` 的 fail-fast 检查被绕过）。

### P3：失败提示不友好

凭证缺失时 `wrangler` 只输出英文 auth 错误，用户不知道去哪补配置。

## 方案

1. **部署前凭证检查**（`api_publish` 开头）：`CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` 任一缺失时，直接返回中文提示「请在 .env.local 补 CLOUDFLARE_API_TOKEN 和 CLOUDFLARE_ACCOUNT_ID 后重启」。
2. **改用 pnpm**（`_run`）：构建用 `pnpm build`（含 `prebuild` fail-fast），部署用 `pnpm exec wrangler pages deploy ...`。
3. **`.env.local` 示例补凭证项**：`docs/deployment.md` 或根目录加 `.env.local.example`，列出三项（`DEEPSEEK_API_KEY` / `PUBLIC_API_BASE` / `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID`），并注明 Cloudflare 凭证在 Cloudflare Dashboard → API Tokens 获取。

## 验收标准

- [ ] 缺 Cloudflare 凭证时，点发布返回清晰中文提示，不再报英文 auth 错误。
- [ ] 凭证齐全时，`pnpm build`（含 prebuild）+ `pnpm exec wrangler pages deploy` 能成功部署。
- [ ] 构建仍受 `PUBLIC_API_BASE` fail-fast 保护。

## 待你确认

- 你的 Cloudflare 凭证（API Token + Account ID）现在有吗？有的话补进 `.env.local` 即可；没有的话我告诉你从哪拿。
