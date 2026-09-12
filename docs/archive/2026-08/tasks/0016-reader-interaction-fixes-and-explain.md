# TASK-0016：阅读页交互修复与 AI 解释增强

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0015

## Goal

按提案 0005，修复注释框确认/取消点不了、划线不能跨段，把 AI 解释改为下划线 + 悬停查看，并移除首页卡片的「AI 概括 · 日期」行。

## Allowed Files

- `apps/web/src/pages/read/[id].astro`
- `apps/web/src/pages/index.astro`
- `apps/web/src/lib/reader-annotations.ts`
- `packages/contracts/src/api.ts`
- `apps/api/src/routes/highlights.ts`（若 `explanation` 需要透传/校验）
- `apps/api/test/`、`apps/web/src/lib/*.test.ts`、`apps/web/e2e/` 相关测试
- `docs/proposals/0005-reader-interaction-fixes-and-explain.md`

## Acceptance Criteria

- [x] 注释框「确认」「取消」可点击；确认保存、取消不保存。
- [x] 跨两个段落的选区能划线（荧光笔/下划线），刷新后保留。
- [x] AI 解释应用下划线，悬停显示解释，不出现瞬态浮层。
- [x] 用户注释与 AI 解释分开存储、分开渲染。
- [x] 首页文章卡片不再显示「AI 概括 · 日期」行。

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
任务：TASK-0016 阅读页交互修复与 AI 解释增强
负责人：web-reader-agent
修改文件：
- packages/contracts/src/api.ts（highlightSpanSchema/highlightSchema 加 explanation）
- apps/web/src/pages/read/[id].astro（注释框 pointerdown 拦截、跨段选区拆分、AI 解释改下划线+explanation、fetchExplanation 替代瞬态浮层）
- apps/web/src/lib/highlights.ts / reader-annotations.ts（Span/Segment/ReaderSegment 带 explanation，渲染 data-explanation）
- apps/web/src/styles/global.css（mark[data-user-highlight][data-explanation] tooltip）
- apps/web/src/pages/index.astro（移除卡片 <small> 行）
- apps/api/test/highlight-reliability.test.ts（paragraphBody 补 explanation 字段）
- apps/web/e2e/highlights.spec.ts（新增注释编辑器确认 e2e）
实现内容：修复注释框确认/取消点不了（pointerdown 未拦截）；支持跨段划线（逐段拆分+保存）；AI 解释改为下划线+悬停 tooltip；首页卡片去 <small>
契约变化：highlightSpanSchema 增加 explanation（默认空串）、highlightSchema 增加 explanation（可选）
测试命令：pnpm --filter @kaogong/api test/typecheck；pnpm --filter @kaogong/web test/check/build；e2e highlights
测试结果：API 145/145、typecheck 通过；Web 29/29、check 0 errors、build 59 页；e2e highlights 3/3（chromium，含注释编辑器确认）
已知问题：跨段划线的文本类动作取拼接文本，逐段保存非严格跨段原子（如需原子性需批量接口）；AI 解释 tooltip 移动端未单独适配
下游 Agent 注意事项：explanation 为 JSON 字段，无表迁移；与用户 note 分开渲染（note=title，explanation=data-explanation）
是否满足验收标准：满足
```
