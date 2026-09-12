# 提案 0005：阅读页交互修复与 AI 解释增强

- **状态**：待评审
- **日期**：2026-08-16
- **任务分解**：TASK-0016
- **范围**：`apps/web/src/pages/read/[id].astro`、`apps/web/src/pages/index.astro`、`apps/web/src/lib/reader-annotations.ts`、`packages/contracts/src/api.ts`、`apps/api/src/routes/highlights.ts`

## 背景

上一轮 TASK-0015 引入的注释内联输入框存在一个交互 BUG：确认/取消按钮点不了。此外，阅读页划线不支持跨段落、AI 解释仍是「黄色高亮 + 瞬态浮层」，首页卡片底部残留一行「AI 概括 · 日期」信息。

## 已确认问题

### P1：注释编辑器「确认 / 取消」无法点击

`read/[id].astro` 中 `document` 的 `pointerdown` 监听（约 367 行）在点击注释框按钮时会先触发 `hide()` → `closeNoteEditor()`，把 `noteEditorTarget` 清空，早于按钮的 `click` 事件；注释框只 `stopPropagation` 了 `mousedown`，未挡住 `pointerdown`，导致确认/取消拿不到目标、静默失效。

**修复**：给 `noteEditor` 也 `stopPropagation` `pointerdown`（或在 document `pointerdown` 里排除 `noteEditor.contains(t)`）。

### P1：划线不能跨段

`selectionToOffsets` 用 `para.contains(range.endContainer)` 把跨段选区判为无效，跨两个段落的划线无法保存。数据模型本身按段存储（`highlight_paragraphs` 每段一条），支持跨段，但当前前端只处理单段。

**修复（设计取舍）**：把跨段选区按段落拆分成多个单段区间；样式类动作（荧光笔/下划线）逐段保存；文本类动作（注释/收藏金句/AI 解释）取选区拼接文本。首版可先顺序保存各段（非严格跨段原子），后续如需原子性再上批量接口。

### P2：AI 解释改为下划线 + 悬停查看，与每日 AI 标注一致

当前工具栏「AI 解释」= 黄色高亮 + `explain-pop` 瞬态浮层。要改为：下划线样式 + 解释持久化到 span、悬停 tooltip 查看（对齐 `.ai-term[data-explanation]` 的交互）。为与用户注释分开存储，给 span 增加可选 `explanation` 字段（JSON 列，无需表迁移）。

**修复**：「AI 解释」应用 `underline` 样式并把 `/api/explain` 结果写入 span 的 `explanation`；渲染时带 `data-explanation` 用 tooltip 展示；去掉瞬态浮层。

### P3：首页卡片去除「AI 概括 · 日期」一行

`index.astro` 文章卡片底部的 `<small>{it.summaryKind} · {it.date}</small>` 移除（轮播 meta 保留）。

## 决策

1. 注释框挡住 `pointerdown`，确认/取消可点击。
2. 跨段划线：拆分为逐段区间，样式动作逐段保存。
3. AI 解释：下划线 + span 级 `explanation` + 悬停 tooltip，与用户注释分开。
4. 首页卡片移除 `<small>` 信息行。

## 实施阶段

### 阶段 A：BUG 修复（P1）

- 注释框 `pointerdown` 拦截。
- 跨段选区拆分与逐段保存。

### 阶段 B：AI 解释增强（P2）

- 契约 `highlightSpanSchema` 增加可选 `explanation`。
- 阅读页「AI 解释」→ 下划线 + 持久化解释 + 悬停 tooltip。

### 阶段 C：UI 清理与测试（P3）

- 首页卡片去 `<small>`。
- e2e：注释确认/取消、跨段划线、AI 解释悬停。

## 验收标准

- [ ] 注释框「确认」「取消」可点击；确认保存、取消不保存。
- [ ] 跨两个段落的选区能划线（荧光笔/下划线），刷新后保留。
- [ ] AI 解释应用下划线，悬停显示解释，不出现瞬态浮层。
- [ ] 用户注释与 AI 解释分开存储、分开渲染。
- [ ] 首页文章卡片不再显示「AI 概括 · 日期」行。
