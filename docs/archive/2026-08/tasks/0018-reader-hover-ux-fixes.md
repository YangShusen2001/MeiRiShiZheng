# TASK-0018：阅读页悬浮交互三处修正

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0017

## Goal

按提案 0007，修复三处悬浮交互：①AI 解释 tooltip 悬停常驻；②左上角「每日时政」改粗体；③「去除」按钮与选择工具栏 / tooltip 上下分离，避免重叠。

## Allowed Files

- `apps/web/src/pages/read/[id].astro`
- `apps/web/src/styles/global.css`
- `apps/web/e2e/highlights.spec.ts`
- `docs/proposals/0007-reader-hover-ux-fixes.md`

## Acceptance Criteria

- [x] 悬停 AI 解释划线出现 tooltip，鼠标移到 tooltip 上不消失，移开两者才消失。
- [x] 左上角「每日时政」为粗体。
- [x] 「去除」按钮与选择工具栏 / AI 解释 tooltip 上下分离，不再重叠遮挡。

## Verification

```text
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web test:e2e -- e2e/highlights.spec.ts --project=chromium
```

## Handoff

```text
任务：TASK-0018 阅读页悬浮交互三处修正
负责人：web-reader-agent
修改文件：
- apps/web/src/pages/read/[id].astro
- apps/web/src/styles/global.css
- apps/web/e2e/highlights.spec.ts
实现内容：
① 共享 tooltip 悬停常驻：新增 cancelHideAnnotationTip/scheduleHideAnnotationTip（150ms 延迟隐藏），tooltip 自身 mouseenter 取消隐藏、mouseleave 延迟隐藏；mark mouseout 改为延迟隐藏，且标记仍聚焦（document.activeElement === el）时保持常驻。
② .logo-text font-weight 400 → 700。
③ placeFloating 增加 preferAbove 参数（下方优先默认、上方优先可选）；「去除」按钮改为上方锚定；showRemoveFor 增加「存在有效选区时抑制」守卫，避免与选择工具栏重叠；tooltip 维持下方锚定。
契约变化：无（纯前端交互/样式；无 API、无数据模型变化）
测试命令：pnpm --filter @kaogong/web test / check / test:e2e
测试结果：单测 29/29；astro check 0 errors；e2e highlights 6/6（新增「tooltip 悬停常驻」「去除与 tooltip 上下分离」2 条）
已知问题：视口边缘极端情况（划线贴顶/贴底）时，「去除」或 tooltip 会翻转到另一侧，可能与另一浮层相邻但不重叠；hover「去除」按钮离开后无 mouseleave 隐藏（沿用既有行为，未改动）
下游 Agent 注意事项：placeFloating 第三参 preferAbove 供「去除」使用；tooltip 粘性靠 150ms 延迟 + tooltip 自身 mouseenter/mouseleave，焦点常驻通过 document.activeElement 判断
是否满足验收标准：满足
```
