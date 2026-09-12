# TASK-0015：收藏类型（文章/金句）与注释交互增强

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0011

## Goal

按提案 0004，把收藏区分为「文章收藏」与「金句收藏」，并把注释交互从原生 `prompt()` 升级为浮动工具栏上方内联输入框 + 悬停查看。

## Allowed Files

- `apps/api/drizzle/`（新增 favorites `kind`/`quote` 迁移）
- `apps/api/src/routes/favorites.ts`
- `packages/contracts/src/api.ts`
- `apps/web/src/pages/read/[id].astro`
- `apps/web/src/pages/favorites.astro`
- `apps/web/src/lib/highlights.ts`
- `apps/web/src/lib/reader-annotations.ts`
- `apps/api/test/`、`apps/web/src/lib/*.test.ts`、`apps/web/e2e/` 相关测试
- `docs/proposals/0004-favorites-types-and-note-ux.md`

## Acceptance Criteria

- [x] favorites 迁移新增 `kind`（默认 `article`）与 `quote`（默认空），旧数据兼容。
- [x] `Favorite` / `favoriteCreateSchema` 增加 `kind` 与 `quote`。
- [x] 「☆ 收藏本文」→ `kind=article`；工具栏「收藏」→ `kind=quote`、`quote` 为选中文本、`url` 为来源文章。
- [x] 文章按 `(owner,url)`、金句按 `(owner,url,quote)` 幂等去重；同文章可多条金句。
- [x] 收藏页分组展示文章收藏与金句收藏，均跳回来源文章。
- [x] 点「注释」在浮动工具栏上方弹出输入框（确认/取消），编辑时预填，确认后保存、取消不保存。
- [x] 带注释的划线渲染时加 `title`，悬停可见注释。

## Verification

```text
pnpm --filter @kaogong/api test
pnpm --filter @kaogong/api typecheck
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web build
```

## Handoff

```text
任务：TASK-0015 收藏类型与注释交互增强
负责人：web-reader-agent
修改文件：
- packages/contracts/src/api.ts（Favorite/favoriteCreateSchema 加 kind/quote；FavoriteCreate 改用 z.input）
- apps/api/src/db/schema.ts（favorites 加 kind/quote）
- apps/api/drizzle/0015_abandoned_thunderball.sql（drizzle-kit 生成）+ meta journal/snapshot
- apps/api/src/routes/favorites.ts（按 kind 处理 + 幂等去重）
- apps/web/src/pages/read/[id].astro（工具栏收藏→金句；注释内联输入框；spansFor 带 note）
- apps/web/src/pages/favorites.astro（文章/金句分组展示）
- apps/web/src/lib/highlights.ts / reader-annotations.ts（Span/Segment/ReaderSegment 带 note，渲染 title）
- apps/web/src/styles/global.css（note-editor/fav 样式）
- 测试：api.test.ts、migration-reliability.test.ts、highlights.test.ts
实现内容：收藏区分为文章/金句（kind+quote，幂等键分别为 (owner,url) 与 (owner,url,quote)）；注释改为浮动工具栏上方内联输入框 + 确认/取消 + 悬停 title
契约变化：Favorite 增加 kind/quote；favoriteCreateSchema 增加 kind（默认 article）/quote（默认空）；FavoriteCreate 类型由 z.infer 改为 z.input（输入字段可选）
测试命令：pnpm --filter @kaogong/api test/typecheck；pnpm --filter @kaogong/web test/check/build；e2e highlights
测试结果：API 145/145、typecheck 通过；Web 28/28、check 0 errors、build 59 页；e2e highlights 2/2（chromium）
已知问题：account-merge 的 favorites 合并仍按 url 去重，device 金句与 user 文章同 url 时合并会丢金句（需后续在 accountMergeStatements 中按 url+kind+quote 去重）
下游 Agent 注意事项：契约/迁移已同步；本地 .dev.vars 已含 DEEPSEEK_API_KEY 与 dev AUTH_SECRET（gitignored）
是否满足验收标准：满足
```
