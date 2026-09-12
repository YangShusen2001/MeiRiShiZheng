# TASK-0012：前端内容展示与构建契约

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0011

## Goal

修复首页空日报渲染、搜索命中数截断不一致，以及生产构建缺少 `PUBLIC_API_BASE` fail-fast（提案 0003 阶段 A/B）。

## Allowed Files

- `apps/web/src/pages/index.astro`
- `apps/web/src/pages/search.astro`
- `apps/web/src/lib/content.ts`
- `apps/web/src/lib/api.ts`
- `apps/web/astro.config.mjs` / `apps/web/package.json`（构建 fail-fast）
- 相关测试
- `docs/proposals/0003-content-quality-and-integrity-baseline.md`

## Acceptance Criteria

- [x] 首页取最近的**非空** digest（`sections.length > 0` 回退），失败日仍展示历史材料。
- [x] 搜索命中数与渲染条数一致（或有明确截断提示/分页）。
- [x] 生产构建 `PUBLIC_API_BASE` 未设置时 fail-fast（非零退出），兑现 `docs/deployment.md` 的承诺。

## Verification

```text
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web build
```

## Handoff

```text
任务：TASK-0012 前端内容展示与构建契约
负责人：web-reader-agent
修改文件：
- apps/web/src/lib/content.ts（新增 latestNonEmptyDigest）
- apps/web/src/pages/index.astro（latest = latestNonEmptyDigest(digests)）
- apps/web/src/pages/search.astro（命中数 >100 时显示截断提示）
- apps/web/package.json（新增 prebuild 脚本）
- apps/web/scripts/check-build-env.mjs（新增：PUBLIC_API_BASE 未设置则退出 1）
- apps/web/src/lib/content.test.ts（latestNonEmptyDigest 2 个用例）
实现内容：首页回退到最近非空日报；搜索截断提示与命中数一致；生产构建缺少 PUBLIC_API_BASE 时 prebuild fail-fast
契约变化：无（未改 packages/contracts）
测试命令：pnpm --filter @kaogong/web test/check/build（build 需先设 PUBLIC_API_BASE）
测试结果：web 单测 26/26；无 env 构建 fail-fast（EXITCODE=1）；设 PUBLIC_API_BASE 后 build 59 页成功；dev 首页实测回退到 2026-08-15（6 卡片）
已知问题：无
下游 Agent 注意事项：prebuild 要求任何 astro build 都需 PUBLIC_API_BASE；空 digest 回退只是前端兜底，根因由 TASK-0009 管道侧修复
是否满足验收标准：满足
```
