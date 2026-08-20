# 提案 0017（整合版）：PC 视觉重设计与动效 + 移动端体验

> 状态：**待审核**。本版为整合版：原 0017（anime.js 选型 + PC 动效）与 0016（移动端优化）合并，并纳入 emilkowalski/skills 动画标准调研（见 `docs/proposals/_research_emil/SUMMARY.md`）。审核通过后按 `docs/tasks/0020` 执行。
>
> 决策记录：①动效库选 anime.js（v4）；②动效走"丰富档"但受频率门禁约束；③与 PC 视觉重设计一起规划；④移动端从"挂起"改为**并入本提案一并改**（2026-08-20 确认）。

---

## 1. 调研结论回顾（已定稿，不再重复论证）

1. **anime.js v4**：TypeScript + ESM、零依赖、gzip ~7–15KB、框架无关，Astro `<script>` 直接 import，不需要换框架（原 0017 结论）。
2. **emilkowalski/skills**（Emil Kowalski：Vercel/Linear 前设计工程师，Sonner/Vaul 作者）：业界主流动画设计标准的浓缩，核心是**频率门禁 + 精确数值**，本次整合全部采用其数值（见 §3）。
3. **工具修正**：原 0017 假设"用 anime.js 做全部动效"。按主流做法修正为 **CSS 优先，anime.js 只做需要 JS 编排的场景**（stagger 组、滚动触发、spring、数字滚动、时间线）。hover/按压/弹层/状态切换全部纯 CSS。

## 2. 设计基线（本站定位 + 现有 token）

- 定位不变：**沉静的编辑部气质**——学院蓝 `#1d4ed8` + 克制金 `#a06d08` + 宋体标题（`global.css :root` 已有一整套明/暗 token）。
- 视觉重设计 = **在现有 token 上深化**（体系化、统一卡片/间距/阴影层级），不推翻重来。
- 移动端与 PC 共用 token，仅布局/交互不同（断点 768px，现有）。

## 3. 动效标准（整合版强制执行，全部来自 emilkowalski/skills）

### 3.1 频率门禁（决定"动不动"）

| 频率档 | 本站例子 | 决策 |
| --- | --- | --- |
| 100+ 次/天 | 键盘操作、核心导航跳转 | **不动画** |
| 几十次/天 | 卡片 hover、按钮按压、列表点击 | 只允许**近不可感知**（快、微） |
| 偶尔 | 弹窗、下拉、搜索面板、主题切换 | 标准动画 |
| 稀有/首次 | 每日一练完成、首次引导 | 允许 delight（bounce/stagger） |

### 3.2 数值表（实现时禁止自造曲线）

| 项 | 值 |
| --- | --- |
| `--ease-out` | `cubic-bezier(0.23, 1, 0.32, 1)`（进出场默认） |
| `--ease-in-out` | `cubic-bezier(0.77, 0, 0.175, 1)`（屏内移动） |
| hover/颜色变化 | `ease` |
| 按钮按压 | `scale(0.97)`，transition 160ms ease-out |
| tooltip/小 popover | 125–200ms，从触发器 scale(0.97→1) |
| 下拉/select | 150–250ms，origin-aware |
| modal | 250ms ease-out，scale(0.96)+opacity，backdrop 同速；**保持居中** |
| 抽屉/底部面板 | 500ms `--ease-drawer`（`cubic-bezier(0.32,0.72,0,1)`） |
| stagger | 30–80ms 间隔，300ms ease-out，绝不阻塞交互 |
| spring | `{duration: 0.5, bounce: 0.2}`，bounce 仅 0.1–0.3 |
| 铁律 | UI 动画一律 <300ms；**只动 transform/opacity**（+clip-path）；**never scale(0)** |

### 3.3 性能与滚动实现 checklist（实现前必过，0020 教训补充）

1. **只动 transform/opacity**：`width/height/margin/padding/top/left` 全部触发 layout——滚动相关实现（进度条、滚动指示器、粘性元素）一律用 `transform: scaleX/translateY` + GPU 合成，或干脆不做。
2. **scroll 监听一律 rAF 节流**：一帧最多处理一次；`passive: true`。
3. **禁止在 scroll 回调里读写 layout 属性**（scrollHeight/clientWidth/style.width）——读一次强制同步布局，写一次强制重排。
4. 新功能实现后对照本清单自查一次（0020 的进度条就是因为跳过自查引入卡顿）。

### 3.4 无障碍（随每个动效一起交付）

```css
@media (prefers-reduced-motion: reduce) { /* 减弱而非归零：保留透明度过渡，去掉位移 */ }
@media (hover: hover) and (pointer: fine) { /* hover 动效只对精确指针生效 */ }
```

## 4. 动效清单（✅ 做 / ❌ 不做）

### ✅ 做（按杠杆排序）

| # | 位置 | 动效 | 数值 | 工具 | 频率档 |
| --- | --- | --- | --- | --- | --- |
| 1 | 全部可点元素 | 按压反馈 scale(0.97) | 160ms ease-out | CSS | 几十/天·近不可感知 |
| 2 | 文章卡片 hover | 上浮 2px + 阴影加深 | 150–200ms ease-out，`(hover:hover)(pointer:fine)` 门控 | CSS | 几十/天·近不可感知 |
| 3 | 导航下拉/搜索面板/邀请码面板 | 从触发器 scale(0.95→1) 生长 | 200ms ease-out，transform-origin 指向触发元素 | CSS | 偶尔 |
| 4 | 登录/邀请码 modal | scale(0.96)+opacity 居中进入 | 250ms ease-out，backdrop 同步 | CSS `@starting-style` | 偶尔 |
| 5 | 主题切换 | 颜色 crossfade（不位移） | 150ms ease | CSS | 偶尔 |
| 6 | 首页卡片组入场 | stagger 浮现（淡入+上移 8px） | 间隔 40ms，300ms ease-out，IO once 首屏不重播 | anime.js stagger | 页面进入 |
| 7 | 今日速览/搜索标签组 | stagger 逐个浮现 | 间隔 30–50ms | anime.js | 页面进入 |
| 8 | 每日一练完成/首次引导 | delight：spring 弹出 + 轻 bounce | `{duration:0.5, bounce:0.2}` | anime.js spring | 稀有 |
| 9 | 得分/统计数字 | 数字滚动 | 600ms ease-out（marketing 档可放宽） | anime.js | 稀有 |
| 10 | 移动端 | 仅按压反馈 + modal，其余零动效 | 同上 | CSS | 性能优先 |

### ❌ 不做（门禁拒绝，写进提案防返工）

- 正文段落滚动浮现、列表滚动 reveal（用户每天读的功能性内容，动画妨碍阅读）
- 键盘触发操作动画；任何 >300ms 的装饰性动画；`scale(0)`；ease-in；transition: all
- 移动端 hover 类动效（触摸无 hover）

## 5. PC 视觉重设计（范围）

| 区域 | 改动 |
| --- | --- |
| 设计 token | `global.css :root` 增加动效 token（`--ease-out/--ease-in-out/--ease-drawer` + 时长 scale `--dur-xs/--dur-sm/--dur-md`）；梳理阴影层级（`--shadow/--shadow-sm` 已有，补 hover 档 `--shadow-lg`） |
| 首页 | 卡片风格统一（圆角/阴影/间距按 token）；hero 与 AI 速览视觉深化；轮播过渡 |
| 导航 | sticky 滚动收窄已有 collapsed 状态，补 200ms 过渡；下拉面板动效（#4 表） |
| 阅读页 | 排版深化（宋体标题字距、行距、标注高亮微调）；不动正文滚动动效 |
| 列表/搜索/收藏/练习 | 统一卡片/条目样式，触控目标升级（见 §6） |
| 明暗主题 | 两套 token 已有，检查对比度与一致性，不新增主题 |

> 具体视觉细节（配色微调方向、卡片密度）待 §9 决策 3 确认后写进 Task。

## 6. 移动端（原 0016 并入）+ 划线对象模型重做（0019 方案 B）

> 划线交互层（`[id].astro`）在 0017 P3 一并重做为**对象模型**（提案 0019 方案 B，用户 2026-08-20 确认），PC 与移动端共用一套新交互，避免同一代码改两次。

### 6.1 划线对象模型（重做核心）

```ts
interface Highlight {
  id: string;                                    // 稳定 id（时间戳+随机）
  quote: string;                                 // 引文文本锚点（内容更新后重新定位）
  ranges: { paragraphIndex: number; start: number; end: number }[];  // 跨段一个对象
  styles: HighlightStyle[];
  note?: string;
  explanation?: string;
  createdAt: number;
}
```

- 存储 v2（`kaogong.highlights.v2.{articleId}`），**v1→v2 迁移**：旧逐段记录按段合并成对象，quote 用段落文本切片生成；迁移函数单测。
- `highlights.ts` 区间纯函数**保留复用**（样式叠加/合并逻辑不动，web 36 用例基线尽量少动），对象层在其上新增。
- **删除整条 = 一次操作**（hover 菜单：删除整条/删除本段）；**undo 栈**（逆操作入栈，Ctrl+Z + 工具栏「↩ 撤销」，上限 50 步）。
- **quote 锚点**顺带修复"文章重抓后划线错位"的隐藏 bug。
- 移动端：就近弹出工具栏 + hover 菜单的触控等价物（长按划线弹出菜单）。

### 6.2 移动端体验项

| 优先级 | 项目 | 说明 |
| --- | --- | --- |
| P0 | 触控目标 ≥44px | `q-opt`/`wq-opt`/`.btn`/`fav-filter` 统一 min-height 44px |
| P0 | 划线工具栏**就近弹出**（原提案默认底部固定） | 紧贴选区上/下方，溢出翻边，符合原生选中菜单习惯（已拍板） |
| P0 | 阅读高频操作沉底 | A−/A＋、AI 标注模式切换移到与划线工具栏同一底部栏 |
| P1 | 「去除」改长按/二次确认 | 防误触 |
| P1 | 列表项整行可点、删除按钮 ≥44px | 收藏/错题 |
| P1 | 底部安全区统一 | `env(safe-area-inset-bottom)` 已有部分，补齐 |
| P2 | 底部 Tab 导航 | **已拍板必做**（首页/搜索/每日一练/收藏/我的；顶部菜单简化为「我的/更多」） |
| P2 | 深色跟随系统 / 阅读进度条 | 可选 |

## 7. 技术方案

- 依赖：仅 `apps/web` 增加 `animejs`（`pnpm add animejs`）；审核台/API/pipeline 零改动。
- 新文件 `apps/web/src/lib/motion.ts`：统一动效入口（`prefers-reduced-motion` 检查 + IntersectionObserver once + anime.js 封装），移动端（<769px）不初始化。
- 接入点：`Base.astro`（导航/主题/弹层）、`index.astro`（卡片/速览 stagger）、`[id].astro`（阅读页移动端工具栏）、`[date].astro`、`practice.astro`（结果/数字）、`search.astro`（面板）。
- 页面路由切换不引入转场动画（静态站 MPA，无 SPA 转场价值）。

## 8. 实施阶段与验收

| 阶段 | 内容 | 验收要点 |
| --- | --- | --- |
| P0 动效基础 | token 落地 + 按压/hover/modal/下拉动效 + reduced-motion | 手感清单：慢放 10% 检查曲线不突兀；reduced-motion 下位移消失、透明度过渡保留 |
| P1 PC 视觉 | **纸感米色**深化：首页/导航/阅读页/列表样式（亮蓝白主题保留为可选） | 与截图对比；明暗主题均正常 |
| P2 动效编排 | stagger/spring/数字滚动（anime.js） | IO once 不重播；stagger 不阻塞交互；移动端无动画 |
| P3 移动端 + 划线重做 | 44px 触控 + **划线对象模型重做（0019 方案 B）** + 就近弹出 + 操作沉底 + 底部 Tab 导航（必做） | 真机单手操作；划线选文→工具栏就近出现；**跨段划线一次删除、Ctrl+Z/撤销按钮逐级回退、v1 数据迁移后旧划线保留**；Tab 导航全部页面可用 |
| ~~P4 可选~~ | ~~底部 Tab / 深色跟随系统~~ | 底部 Tab 已并入 P3；深色跟随系统仍可选（低优先级） |

每阶段跑 `pnpm -r typecheck && pnpm -r test`，web 构建需 `PUBLIC_API_BASE`。

## 9. 决策记录（2026-08-20 已拍板）

1. **移动端划线工具栏**：**就近弹出**（选区上/下方，溢出翻边）。
2. **底部 Tab 导航**：**上**（首页/搜索/每日一练/收藏/我的；顶部菜单简化为「我的/更多」）——从 P4 可选升为必做，并入 P3。
3. **PC 视觉方向**：**b) 纸感米色**（暖阅读，深化现有纸感 token：`--bg:#f6f1e6` 系；作为 PC 主推方向，亮蓝白主题保留为可选）。
4. **动效强度**：**丰富版**（§4 全表 + delight + 数字滚动）。
5. **划线功能重做**：**对象模型方案 B 并入 P3**（2026-08-20 确认，见 §6.1 与提案 0019）——跨段一次删、undo 栈、v1→v2 迁移、quote 锚点修复重抓错位，与移动端工具栏重做合并实施。

## 10. 边界

- 不引入新框架；不重写页面结构（视觉/动效只改样式与渐进增强脚本）。
- 不动 `apps/api`、`pipeline`、`packages/contracts`、审核台。
- 0016 原提案保留原文供追溯，头部标记"已并入 0017"。
- 0018（审核台重构）与本提案独立，Phase A 不着急改（用户确认）。
