# 提案 0006：划线标注可见性（图标）与 Markdown 支持

- **状态**：待评审
- **日期**：2026-08-16
- **任务分解**：TASK-0017
- **范围**：`apps/web/src/lib/reader-annotations.ts`、`apps/web/src/lib/highlights.ts`、`apps/web/src/pages/read/[id].astro`、`apps/web/src/styles/global.css`、`apps/web/package.json`（Markdown 依赖）

## 背景

当前三类带附加内容的划线（用户 AI 解释、用户注释、AI 术语解析）在页面上没有统一的「此处有解析」标识；用户注释只用了原生 `title`（桌面 hover 才显示、延迟 ~1s、移动端不可用），实际「没法查看」；AI 解释 tooltip 是 CSS `::after` 纯文本，不支持 Markdown。

## 已确认问题

### P1：用户注释没有可用/统一的查看方式

用户注释现在只挂在 `<mark title="...">` 上，依赖浏览器原生 tooltip：桌面要悬停约 1 秒、样式不可控、移动端完全不显示。需要与 AI 解释统一成同一种可样式化、可带图标标识的 tooltip。

### 功能：带 note/explanation 的划线加「右上角小图标」标识

给任何带 `note` 或 `explanation` 的片段，在右上角渲染一个类似「搜索 🔍」的小图标，让用户一眼看出「这一处有解析/注释」。

### 功能：AI 解释 tooltip 支持 Markdown

AI 解释文本可能含 `**加粗**`、列表、代码等 Markdown，当前按纯文本渲染。需要安全地渲染 Markdown（先渲染、再消毒，防 XSS，遵循「AI 不得注入 HTML、程序负责校验」边界）。

## 设计决策（待确认）

1. **图标**：统一一个 🔍 小图标（`::before` 徽标，右上角），标识「有解析」；三种类型靠「划线样式 + tooltip 内容」区分（用户注释=高亮、AI 解释=下划线、AI 术语=底部边框）。—— 如果你想要三种不同图标，请说明。
2. **tooltip 实现**：从 CSS `::after`（`content: attr(...)`）改为**单个 JS 渲染的共享 tooltip**，hover/focus 时定位到对应片段并显示内容，统一承载 note / explanation。
3. **Markdown 依赖**：推荐引入 `marked`（渲染）+ `dompurify`（消毒）；若不想加依赖，可自写最小渲染器（加粗/斜体/行内代码/换行/列表），功能受限但零依赖。

## 实施阶段

### 阶段 A：tooltip 与图标（P1 + 功能）

- 渲染链路把 `note` 从 `title` 改为 `data-note`，`explanation` 保持 `data-explanation`。
- 新增共享 tooltip 元素，hover/focus 显示 note/explanation。
- `[data-note]`、`[data-explanation]` 右上角渲染 🔍 小图标。

### 阶段 B：Markdown 支持（功能）

- 引入 Markdown 渲染 + 消毒；tooltip 内容渲染为 HTML。

### 阶段 C：测试

- 单测：图标属性、data-note/data-explanation 输出。
- e2e：hover 注释显示 tooltip；AI 解释含 Markdown 时正确渲染。

## 验收标准

- [ ] 带注释/解释的划线右上角有小图标标识。
- [ ] 悬停/聚焦带注释的划线能看到注释（桌面与移动端）。
- [ ] 悬停/聚焦带 AI 解释的划线能看到解释，且支持 Markdown（加粗、列表等）。
- [ ] Markdown 渲染经过消毒，无 XSS。
- [ ] 三类内容（用户注释 / AI 解释 / AI 术语解析）可区分。
