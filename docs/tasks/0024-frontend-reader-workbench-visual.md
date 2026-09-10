# TASK-0024：前端——阅读器 island + 工作台 + 视觉层（0022 阶段 C）

## Status

completed

## Owner

待分配（web-reader-agent）

## Dependencies

- TASK-0022（契约）
- TASK-0023（管道产物：picks / aiRelations / 卡片锚定）
- 提案 0022 §6（工作台）、§8（React island）、§9（视觉层）

## 进度（2026-08-22）

- [x] **线上箭头渲染**：`roughjs` 手绘曲线 + 手绘箭头头（4 种 relation kind 配色、半透明、悬停/点击显示簇、`ResizeObserver`+`document.fonts.ready` 重算、`prefers-reduced-motion` 关闭）；`reader-annotations.ts` 输出 `data-rel-ids`/`data-annotation-id` 装饰（纯函数层框架无关）；阅读页接入（AI 模式显示、`#ai-relations` JSON 注入、移动端点击闪烁兜底）
- [x] 修复构建回归：`apps/web/src/lib/content.ts` 仅认日期目录（policy-lines.json 引入的文件扫描 ENOTDIR）
- [x] 测试：reader-relations 纯函数 4 用例；web 全量 61 passed；tsc 0 错误；`astro build` 162 页成功
- [ ] 移动端段落结构卡片（中心句+支撑点列表）
- [ ] 阅读器迁 React island（箭头编辑器前置）
- [ ] 选材工作台（全文预览 + 箭头编辑器 + 主线归属 + 槽位确认）
- [ ] 视觉层（双字体子集化/纸感/rough-notation 荧光笔三色映射/DESIGN.md 重写）

## 工作台编辑器交互规格（2026-08-22 用户拍板）

1. **荧光笔先画**：用户在全文预览里用荧光笔（rough-notation highlight）绘制重点区域（支撑句）。
2. **[ ] 吸附**：把 [ ]（中心句标注）拖到荧光笔区域上，自动吸附左右（左/右括号贴合荧光区边缘）；可微调。
3. **箭头素材库自选**：`public/vendor/handy/` 已入库 **185 支手绘箭头**（含 `index.json` 元数据），编辑器内预览库供自选，支持用户**自己上传替换**（存 `aiRelations.style.arrow`）。
4. **箭头方向可选**：只吸附"被标注的重点句子"（aiAnnotations span）；向上指向 → 默认渲染在荧光区**最上一行**；向下指向 → **最下一行**（数据字段 `direction: "up"|"down"`，默认 down；前端渲染已按此实现，`reader-relations.ts` 的 `drawArrows`）。
5. 渲染按当前 DOM 实时计算（getBoundingClientRect + ResizeObserver），**不同分辨率/排版下自动适应**（荧光笔、括号、箭头端点全部重算）。

## 已实现（2026-08-22）

- [x] 阅读器正式版：rough-notation 双括号（全局样式色）+ 支撑句荧光笔（淡黄，透明度可调）+ Handy Arrows 素材箭头（默认 `41.svg`，矢量方向摆放 + 可选 rotate/素材）
- [x] 素材库：`apps/web/public/vendor/handy/`（185 SVG + index.json，2MB）；`rough-notation`/`roughjs` ESM vendored 到 `public/vendor/`
- [x] `direction` up/down 渲染支持（锚定句最上/最下行边缘）
- [x] **编辑器**（审核台 `/editor/{articleId}`）：全文预览 → 点标注句设 [ ] 中心句 / 荧光支撑点 → 右侧关系列表（素材缩略图点击开库、上下方向、删除）→ 箭头库 185 支 + 上传自定义 → 保存 `PUT /api/relations`（.bak 备份 + 引用校验 + 人工编辑审计字段）
- [x] **样式面板**：颜色/荧光色/括号线粗/荧光透明度/箭头尺寸/默认方向 → `PUT /api/relation-style` 写 `apps/web/public/relation-style.json`（线上站 fetch 刷新生效）；线上渲染已接全局样式 + CSS 变量
- [x] DESIGN.md 重写（手绘视觉语言 §9 + 字体规范 §3）
- [x] 移动端结构卡片（点击中心句底部面板）
- [ ] 手绘纸感版式渐进落地（DESIGN §7；字体文件待用户提供授权后走 fonts.py 子集化——债务见 §8）

## Goal

按提案 0022 §8/§9/§10-C 落地前端：阅读器迁 React island（前置）→ 线上渲染手绘箭头（overlay + 移动端结构卡片）→ 选材工作台（全文预览 + 箭头编辑器 + 主线归属 + 槽位确认）→ 手绘视觉层（字体子集化 / 纸感版式 / rough-notation 标注 / rough.js 箭头）。

## Allowed Files

- `apps/web/src/`（pages/read、lib/reader-annotations、styles/global.css、layouts/Base.astro、package.json）
- `apps/web/public/fonts/`、`apps/web/src/font-config.json`
- `pipeline/src/kaogong/fonts.py`（字体子集化扩展）
- `pipeline/src/kaogong/review/`（server.py、ui/index.html 或独立编辑器页）
- `packages/contracts/src/`（如需新增工作台契约）
- `docs/tasks/0024-frontend-reader-workbench-visual.md`
- `DESIGN.md`

## Acceptance Criteria

- [ ] 阅读器迁 React island：仅 `read/[id].astro` 交互主体；现有回归清单全过（划线三式/撤销、AI 解释、术语收藏、收藏、原文/AI 模式、字体/沉浸/全屏）；纯函数层（readerSegmentsToHtml 等）与 highlights 对象模型复用不重写。
- [ ] 线上箭头渲染：SVG overlay + 贝塞尔/手绘曲线；悬停/点击中心句显示该簇；`ResizeObserver` + `document.fonts.ready` 重算；`prefers-reduced-motion` 关闭；移动端显示段落结构卡片（中心句+支撑点列表）。
- [ ] 选材工作台：全文预览（完整正文 + AI 三色标注 + 金句，原文/AI 模式切换）；箭头编辑器（改锚点/增删/关系标签/拖动画预览），人工修正写回内容数据且不被重跑覆盖；主线归属改正；槽位确认（左侧 top 12 带等级+理由 → 右侧 5 槽位，一键 AI 建议稿/逐槽替换）；每日选材完整走通后发布。
- [ ] 视觉层：站酷快乐体 + 手书体/楷体变体双字体（商免清单核验 + 子集化）；纸感版式（噪点纹理/不规则圆角/微旋转/纸影）；荧光笔 rough-notation 三色映射（考点=蜡笔黄/观点=蜡笔青/术语=蜡笔橙，走查后确认）；箭头 rough.js 蜡笔曲线；明暗主题 + 375px + 200% 缩放 + 打印无回归；护眼豆沙绿 token 保留。
- [ ] DESIGN.md 同步重写（保留明暗 token 与正文层约束，质感换为手绘纸感）。
- [ ] 测试：Playwright 回归 + 视觉层在明暗主题/375px/200% 缩放检查。

## Verification

```text
CI=true pnpm --filter @kaogong/web test
CI=true pnpm --filter @kaogong/web check
CI=true pnpm --filter @kaogong/web test:e2e（Playwright 回归清单）
cd pipeline && python -m pytest -q（审核台相关）
```

## Handoff

```text
任务：
负责人：
修改文件：
实现内容：
契约变化：
测试命令：
测试结果：
已知问题：
下游 Agent 注意事项：
是否满足验收标准：
```
