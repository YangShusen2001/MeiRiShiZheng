# 提案 0007：阅读页悬浮交互三处修正

- **状态**：待评审
- **日期**：2026-08-16
- **任务分解**：TASK-0018
- **范围**：`apps/web/src/pages/read/[id].astro`、`apps/web/src/styles/global.css`、`apps/web/e2e/highlights.spec.ts`

## 背景

阅读页有三处悬浮交互不符合预期：①AI 解释 tooltip 鼠标移入即消失；②左上角 logo「每日时政」不是粗体；③「去除」按钮会与划线弹出的浮层（选择工具栏 / AI 解释 tooltip）重叠遮挡。

## 已确认问题

### ① tooltip 不可悬停（移入即消失）

`[data-explanation]` 的共享 tooltip（`.annotation-tip`）目前用 `mouseover` 显示、`mouseout` 隐藏。当指针从划线文字移到 tooltip 上时，`mouseout` 在 mark 上触发（tooltip 不是 mark 的子节点）→ 立即隐藏，导致无法把鼠标移到 tooltip 上继续阅读。期望：tooltip 悬停常驻，移开「划线文字 + tooltip」两者才消失。

> 说明：当前「注释（note）」字段只存储不渲染，页面只有 AI 解释（explanation，含 AI 术语）走共享 tooltip。本提案的「tooltip 常驻」针对这条共享 `.annotation-tip`。若你还需要把「注释」也重新渲染出来，请单独说明。

### ② 左上角「每日时政」非粗体

`.logo-text` 当前 `font-weight: 400`，期望改为粗体（700）。

### ③ 「去除」按钮与划线浮层重叠

`.hl-remove`（去除，z-index 101）、`.annotation-tip`（tooltip，z-index 120）、`.hl-toolbar`（选择工具栏，z-index 100）都用同一个锚点（选区/划线 rect）做「下方优先、放不下才翻上方」的定位。当同一处划线同时触发多个浮层时（典型：AI 解释后的划线 hover 同时出现「去除」和 tooltip；选中文本时划过已有划线，同时出现工具栏和「去除」），多个浮层会堆叠在同一位置互相遮挡。期望：上下分开，不重叠。

## 设计决策（待确认）

1. **tooltip 悬停常驻**：给共享 tooltip 加「粘性」——鼠标移到 tooltip 上时不隐藏，离开划线文字且离开 tooltip 后才隐藏。实现用标准模式：离开 mark 后延迟 ~150ms 隐藏，tooltip 自身 `mouseenter` 取消延迟、`mouseleave` 触发隐藏；`focus` 维持现状（focusout 才隐藏，聚焦常驻）。
2. **logo 粗体**：`.logo-text` `font-weight` 400 → 700，无其他影响。
3. **浮层上下分离**：
   - 「去除」按钮固定锚定在划线**上方**（当前默认下方）。
   - 共享 tooltip 锚定在划线**下方**（维持现状）。
   - 选择工具栏锚定在选区**下方**（维持现状）。
   - 三者各自保留「放不下则翻转到另一侧」的边界回退。
   - 存在有效选区（工具栏可见）期间抑制 hover「去除」，避免与选择工具栏重叠。

## 实施阶段

### 阶段 A：tooltip 悬停常驻（①）

- `showAnnotationTip` 记录当前目标元素；给 tooltip 挂 `mouseenter`（取消隐藏延迟）/ `mouseleave`（触发隐藏）。
- mark 的 `mouseout` 改为「延迟 150ms 隐藏」，指针进入 tooltip 或另一处 `[data-explanation]` 时取消。
- `focus` 路径维持常驻（已满足）。

### 阶段 B：logo 粗体（②）

- `.logo-text` 改 `font-weight: 700`。

### 阶段 C：浮层上下分离（③）

- 给「去除」按钮增加「上方锚定」定位（复用 `placeFloating` 加参数或新增 `placeAbove`）。
- 选中文本期间抑制 hover「去除」（在 `pointerdown`/`selectionchange` 里控制），避免与选择工具栏重叠。

### 阶段 D：测试

- e2e：悬停 AI 解释划线 → tooltip 出现 → 移入 tooltip 不消失 → 移出后消失。
- e2e：AI 解释划线 hover 时「去除」位于 tooltip 上方、互不遮挡。
- 回归：现有 29 单测 + e2e highlights 保持通过。

## 验收标准

- [ ] 悬停 AI 解释划线出现 tooltip，鼠标移到 tooltip 上不消失，移开两者才消失。
- [ ] 左上角「每日时政」为粗体。
- [ ] 「去除」按钮与选择工具栏 / AI 解释 tooltip 上下分离，不再重叠遮挡。
