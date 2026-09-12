# TASK-0003：阅读页原文和 AI 标注模式

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0001
- TASK-0002
- TASK-0007

## Goal

在原文上渲染只读 AI 标注，同时保留用户自己的标注。

## Allowed Files

- `apps/web/**`
- 前端内容和阅读测试

## Acceptance Criteria

- [x] 支持原文模式和 AI 标注模式。
- [x] 观点句加粗，考点高亮，术语下划线。
- [x] 鼠标悬停或键盘聚焦术语显示释义，移开或失焦隐藏。
- [x] AI 标注不可被用户删除。
- [x] 用户标注和 AI 标注可重叠且互不覆盖。
- [x] AI 数据缺失时仍可阅读原文。

## Verification

```text
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
```

## Handoff

```text
任务：TASK-0003 阅读页原文和 AI 标注模式
负责人：web-reader-agent
修改文件：apps/web/src/lib/reader-annotations.ts、apps/web/src/lib/highlights.test.ts、apps/web/src/pages/index.astro、apps/web/src/pages/read/[id].astro、apps/web/src/styles/global.css、apps/web/e2e/reader-ai.spec.ts、docs/tasks/0003-reader-ai-mode.md
实现内容：首页文章卡片显示标题、来源、分类并优先展示 aiSummary；阅读页支持原文/AI 模式，按偏移合并 AI 与用户原子区间；观点加粗、考点高亮、术语下划线及 hover/focus 释义；AI 失败和历史文章保留原文降级；桌面与移动端适配
契约变化：无；只读消费 TASK-0001 已确定的 ClippedArticle ai* 字段，AI 标注不进入用户 highlights
测试命令：pnpm --filter @kaogong/web test；pnpm --filter @kaogong/web check；pnpm --filter @kaogong/web build；pnpm --filter @kaogong/web test:e2e
测试结果：Vitest 16 项通过；Astro check 0 错误；构建成功生成 24 页；Playwright 桌面 Chromium、Android Chromium、iOS WebKit 共 12 项通过
已知问题：历史内容没有 AI 字段时仅显示原文和摘要降级提示；无解释的 term 仍显示术语下划线，但不伪造解释
下游 Agent 注意事项：继续保证 Pipeline 的 start/end 与 JS 字符串偏移一致；用户划线删除入口仅识别 data-user-highlight，不会删除 AI 标注
是否满足验收标准：满足
```
