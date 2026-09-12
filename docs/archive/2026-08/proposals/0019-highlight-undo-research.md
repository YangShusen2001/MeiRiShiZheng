# 提案 0019：划线功能重做调研（"撤销分好几次"根因 + 主流做法 + 代价）

- 状态：**已并入提案 0017 P3（2026-08-20 用户确认方案 B）**。本文保留调研结论供实现引用；实施见 `docs/tasks/0020` P3。
- 触发：0017 决策拍板后用户提出——划线能完整划，但"撤销需要分好几次"，问重做代价
- 关联：0017 P3（移动端划线工具栏就近弹出）、0018（审核台，无关）

---

## 1. 问题根因（代码级定位）

### 1.1 数据模型现状

`apps/web/src/pages/read/[id].astro`：`localStorage["kaogong.highlights.v1.{articleId}"]` 存**逐段平铺**的 `LocalHighlight[]`：

```ts
interface LocalHighlight { paragraphIndex: number; start: number; end: number; styles: HighlightStyle[]; note?; explanation? }
```

- 每段一条独立记录，**无 id、无"划线对象"概念、无创建时间、无操作历史**。
- 划线（`toolbar` 点击）＝选区按段拆分 → 每段 `applyStyle` → 每段 `reconcileParagraph`（异步保存+整段重渲染）。跨段划线一次操作会生成 N 条记录。
- 去除（hover `<mark>` → 浮出「去除」按钮）＝`markOffsets` 取**当前 hover 的那个 mark** 的段落区间 → `removeRange` → 只删**这一小段**。

### 1.2 "撤销分好几次"的两个根因

1. **跨段划线 = N 个 mark，去除只能逐段删**：划 3 段 → 生成 3 个 mark → 想删掉这条划线，要 hover 每段各点一次「去除」，共 3 次。同段内若被多次划线/样式叠加切成多个 mark，同样逐片删。
2. **没有真正的"撤销上一步"**：页面不是 contenteditable，DOM 变更不进浏览器 undo 栈，**Ctrl+Z 无效**；代码里也没有操作历史。用户只能靠「去除」逐段点。

> 顺带发现一个隐藏风险：偏移模型（paragraphIndex + 字符偏移）在**文章重抓后段落文本变化时会全部错位**——pipeline 对 AI 标注有 `_locate` 重定位，用户划线没有。

## 2. 主流成熟做法（调研）

### 2.1 注释 = 对象，DOM 高亮 = 投影（业界标准）

- **Hypothesis / W3C Web Annotation**：一条注释是一个对象 `{id, quote（引文文本锚点）, ranges（位置锚点列表）, 元数据}`；跨段就是一个对象带多个 ranges；DOM 上渲染成多个高亮块只是**投影**，删除=删对象=一次；内容更新后按 quote 文本重新锚定（[Hypothesis for Web Developers](https://web.hypothes.is/blog/hypothesis-for-web-developers/)、[TextQuoteAndPosition（W3C 标准实现）](https://github.com/judell/TextQuoteAndPosition)）。
- **微信读书 / Readwise / Glarity**：hover 划线 → 菜单（删除整条/写想法/复制），删除一次整条，跨段同样。
- 中文社区同类实现：[记一次划线需求的实现方式（掘金）](https://juejin.cn/post/7344993022075813938)、[web 文本划线的极简实现（华为云）](https://bbs.huaweicloud.com/blogs/381885)。

### 2.2 撤销 = 操作历史栈（编辑器标准）

VS Code / Photoshop / 设计工具的通用做法：每次操作（划线/删除/改样式）把**逆操作**入栈，Ctrl+Z 或按钮逐级回退；栈上限（如 50 步）。非 contenteditable 的阅读页划线需要自己实现这个栈，浏览器不提供。

## 3. 重做代价评估

| 方案 | 内容 | 改动范围 | 代价 | 局限/收益 |
| --- | --- | --- | --- | --- |
| **C 超轻量**：只加撤销栈 | 操作前快照/逆操作入栈，工具栏加「↩ 撤销」+ Ctrl+Z | 仅 `[id].astro`（约 60 行）+ 少量测试 | **~0.5 天** | 撤销可预期了；但跨段删除仍要逐段 hover 点 N 次（体验问题还在） |
| **A 最小修复**：跨段一次删 | hover mark → 收集同次操作的各段记录删除（需给记录补 opId 或按对象分组，向后兼容） | `[id].astro` + `highlights.ts` 小改 + 迁移逻辑 | **~1–1.5 天** | 跨段一次删解决；但无撤销栈（Ctrl+Z 仍无效），存储加了历史包袱字段 |
| **B 对象模型重做（推荐）** | `Highlight {id, quote, ranges:[{paragraphIndex,start,end}], styles, note, explanation, createdAt}`；v1→v2 迁移；对象级 API + 对象级 undo 栈；hover 菜单（删除整条/删除本段/撤销）；quote 锚点解决重抓错位 | `highlights.ts` 扩展 + `[id].astro` 划线交互重写 + 迁移 + 测试更新 | **~3–4 天** | 与主流对齐：跨段一次删、撤销可预期、内容更新不错位、为"我的划线列表"页与云端同步留好模型；同时是 0017 P3 移动端工具栏重做的顺带收益 |

### 3.1 推荐组合

**方案 B 并入 0017 P3 一起做**，理由：

1. 0017 P3 本来就要重做移动端划线工具栏（就近弹出）——**同是 `[id].astro` 划线交互层，分开做等于同一块代码改两次**；合并实施总代价 ≈ 3–4 天，而不是 B(3–4) + P3 划线部分(1–2)。
2. B 的 undo 栈 + hover 菜单（删除整条/本段）同时解决 PC 与移动端"撤销分好几次"。
3. 顺带修掉"文章重抓后划线错位"的隐藏 bug（quote 锚点）。

### 3.2 风险与注意

- **v1 数据迁移**：现有 `kaogong.highlights.v1.*` 数据需读入并转换为 v2 对象（同段区间合并成对象；quote 用段落文本切片生成），旧 key 保留或清理，迁移函数需单测。
- 区间纯函数（`highlights.ts`）**保留复用**：对象模型在其上层，不推翻已验证的样式叠加/合并逻辑（web 36 用例基线尽量少动）。
- hover 菜单与现有「AI 解析邀请码」「AI 标注 tooltip」浮层不冲突（现有 `annotationTip`/`removeBtn` 机制复用）。
- 移动端就近弹出工具栏（0017 P3）与 hover 菜单（桌面）是同一交互层的两个分支，一并设计。

## 4. 结论

- 根因：**数据模型无对象概念 + 无操作历史**，去除按 DOM mark 逐段删。
- 主流做法：**对象模型 + DOM 投影 + 操作历史栈**（Hypothesis/微信读书/编辑器标准）。
- 建议：**方案 B 并入 0017 P3**（约 3–4 天），一次解决跨段删除、撤销、内容更新错位、移动端工具栏四件事；若只求最小改动，方案 C 0.5 天兜底（跨段删除问题保留）。
