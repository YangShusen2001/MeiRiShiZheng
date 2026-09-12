# TASK-0011：阅读页划线、注释与选区交互一致性

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0008

## Goal

修复阅读页划线/注释/选区的交互缺陷与收藏不一致，消除用户数据丢失（重叠注释静默丢失）与交互失效（元素锚定选区无法触发工具栏），并理顺收藏语义与冲突竞态（提案 0003 阶段 A/B）。

## Allowed Files

- `apps/web/src/pages/read/[id].astro`
- `apps/web/src/lib/highlights.ts`
- `apps/api/src/routes/highlights.ts`
- `apps/api/src/routes/favorites.ts`
- `packages/contracts/src/api.ts`
- `apps/web/e2e/` 与相关测试
- `docs/proposals/0003-content-quality-and-integrity-baseline.md`

## Acceptance Criteria

- [ ] 重叠划线上新增注释保存后刷新不丢失（回归用例）；`inheritedNote` 仅在 span 是原注释区间的严格子段时继承。
- [ ] 三击整段 / 元素锚定选区能触发划线工具栏（新增 e2e 用例）。
- [ ] 工具栏「收藏」与页面「收藏」统一用官方 URL/标题；失败时工具栏不显示 `saved`、不清空选区。
- [ ] `HIGHLIGHT_CONFLICT` 重载按段落合并，不覆盖其他段落并发保存的结果。
- [ ] 注释长度按契约限长（客户端校验），重叠 span 合并后不重复提交。
- [ ] legacy `highlights` 提供删除/可见性策略，`styles` 为空或 `start >= end` 的行不再静默不可见且无法清理。

## Verification

```text
pnpm --filter @kaogong/api test
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web test:e2e
```

## Handoff

```text
任务：TASK-0011 阅读页划线、注释与选区交互一致性
负责人：web-reader-agent（后端部分由子代理实现）
修改文件：
- apps/web/src/lib/highlights.ts（新增 resolveSpanNotes 纯函数）
- apps/web/src/pages/read/[id].astro（注释按选区覆盖匹配、元素锚定选区、收藏统一官方 URL/回写 saved、冲突按段落重载、注释 2000 截断、spansFor 合并重复 span）
- apps/web/src/lib/highlights.test.ts（resolveSpanNotes 4 个回归用例）
- apps/web/e2e/highlights.spec.ts（元素锚定选区 e2e 用例）
- apps/api/src/routes/favorites.ts（POST 按 owner+url 幂等去重）
- apps/api/src/routes/highlights.ts（成功 PUT 后清理被取代的 legacy highlights）
- apps/api/test/api.test.ts、highlight-reliability.test.ts（后端回归：幂等 2 例 + legacy 清理 3 例）
实现内容：修复重叠划线加注释静默丢失、三击/缩进拖选无法触发工具栏、工具栏收藏内部 URL 与 saved 恒 true、HIGHLIGHT_CONFLICT 重载覆盖并发保存、注释超长无校验、重复 span 未合并；后端收藏幂等与 legacy 划线清理
契约变化：无（未改 packages/contracts；note 2000 上限沿用现有 highlightSpanSchema）
测试命令：pnpm --filter @kaogong/web test/check/build/test:e2e；pnpm --filter @kaogong/api test/typecheck
测试结果：web 单测 24/24；astro check 0 errors/2 hints；build 59 页；e2e highlights 2/2（chromium）；api 143/143；api typecheck 通过
已知问题：favorites 幂等为应用层 select-then-insert，无 (owner_id,url) 唯一索引，极端并发双 POST 仍可能产生两行（如需强保证可后续加迁移建唯一索引）
下游 Agent 注意事项：AI 标注仍为独立只读层，不得写入 highlight_paragraphs；未改动共享 contracts，与 TASK-0013 无冲突
是否满足验收标准：满足
```
