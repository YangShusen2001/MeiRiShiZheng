# TASK-0017：划线标注可见性（图标）与 Markdown 支持

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0016

## Goal

按提案 0006，给带 note/explanation 的划线加右上角小图标，统一注释与解释的 tooltip 查看，并让 AI 解释 tooltip 支持 Markdown。

## Allowed Files

- `apps/web/src/lib/reader-annotations.ts`
- `apps/web/src/lib/highlights.ts`
- `apps/web/src/pages/read/[id].astro`
- `apps/web/src/styles/global.css`
- `apps/web/package.json`（Markdown 依赖）
- `apps/web/src/lib/*.test.ts`、`apps/web/e2e/` 相关测试
- `docs/proposals/0006-annotation-visibility-and-markdown.md`

## Acceptance Criteria

- [x] 带注释/解释的划线右上角有小图标标识。
- [x] 悬停/聚焦带注释的划线能看到注释（桌面与移动端）。
- [x] 悬停/聚焦带 AI 解释的划线能看到解释，且支持 Markdown。
- [x] Markdown 渲染经过消毒，无 XSS。
- [x] 三类内容（用户注释 / AI 解释 / AI 术语解析）可区分。

## Verification

```text
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web build
```

## Handoff

```text
任务：TASK-0017 划线标注可见性与 Markdown 支持
负责人：web-reader-agent
修改文件：
- apps/web/package.json（新增 marked/dompurify 依赖）
- apps/web/src/lib/markdown.ts（新增 renderMarkdown：marked 渲染 + DOMPurify 消毒）
- apps/web/src/lib/reader-annotations.ts（note 由 title 改为 data-note；explanation 保持 data-explanation）
- apps/web/src/lib/highlights.ts（segmentsToHtml 的 note 改为 data-note）
- apps/web/src/styles/global.css（[data-note]/[data-explanation] 右上角 🔍 图标；.annotation-tip 共享 tooltip；移除旧 ::after tooltip）
- apps/web/src/pages/read/[id].astro（共享 tooltip + renderMarkdown + hover/focus 事件）
- apps/web/src/lib/highlights.test.ts（title → data-note 断言）
- apps/web/e2e/highlights.spec.ts（新增悬停 tooltip + Markdown e2e）
实现内容：带注释/解释的划线右上角统一 🔍 图标；注释与解释统一为 JS 共享 tooltip（桌面/移动端，支持 Markdown）；AI 解释 Markdown 渲染（marked + DOMPurify 消毒）
契约变化：无（纯前端渲染；数据仍为 span 的 note/explanation 文本）
测试命令：pnpm --filter @kaogong/web test/check/build；e2e highlights
测试结果：Web 29/29、check 0 errors、build 59 页；e2e highlights 4/4（chromium，含悬停 tooltip + Markdown <strong>）
已知问题：共享 tooltip 的鼠标移出即隐藏（聚焦 tabindex 可常驻查看）；tooltip 内 Markdown 链接未额外处理 target=_blank
下游 Agent 注意事项：AI 解释/注释仍为纯文本存储，Markdown 仅在渲染层解析；DOMPurify 消毒防 XSS
是否满足验收标准：满足
```
