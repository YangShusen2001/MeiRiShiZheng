# 调研：emilkowalski/skills —— 动画设计的"行业标准参考"

- 调研日期：2026-08-20
- 对象：https://github.com/emilkowalski/skills（作者 Emil Kowalski，Vercel / Linear 前设计工程师，Sonner / Vaul / Motion 生态作者，animations.dev 创始人）
- 性质：给 AI 编程助手用的"设计品位"技能包（`npx skills@latest add emilkowalski/skills`），核心思想是**用精确数值标准取代"凭感觉"**，防止 AI（和人）做出 `ease-in` 入场、`scale(0)` 弹窗、400ms 下拉这类典型错误。
- 本摘要为后续 0017 整合提案提供数值依据；原始文件已下载到 `docs/proposals/_research_emil/`。

## 1. 仓库结构（22 个文件，与本站相关的 7 个 skill）

| Skill | 作用 | 对我们的价值 |
| --- | --- | --- |
| `animate` + `RECIPES.md` | 从零构建一个动画的完整决策序列 + 12 个现成配方 | ★★★ 直接抄配方 |
| `review-animations` + `STANDARDS.md` | 严格评审动画，附**精确数值标准表** | ★★★ 本文档主体 |
| `find-animation-opportunities` | 扫界面找"该动的地方"，但 80% 候选会被门禁拒绝 | ★★★ 决定"哪些地方动、哪些不动" |
| `improve-animations` + `PLAN-TEMPLATE.md` | 全库动画审计 → 产出自包含执行计划 | ★★ Task 模板参考 |
| `animation-vocabulary` | 动画术语词典 | ★ 写提案/Task 用词准确 |
| `emil-design-eng` | 设计工程总纲（动画决策框架 + 组件原则） | ★★ 总纲 |
| `apple-design` | Apple 设计原则（WWDC 提炼） | 可选 |

## 2. 核心数值标准（STANDARDS.md，后续实现必须引用，禁止自造曲线）

### 2.1 该不该动？——频率门禁（最高优先级规则）

| 使用频率 | 决策 |
| --- | --- |
| 100+ 次/天（快捷键、命令面板、核心导航） | **不动画，永远** |
| 几十次/天（hover、列表导航、高频开关） | 移除或压到**近不可感知** |
| 偶尔（弹窗、抽屉、toast、设置） | 标准动画 |
| 稀有/首次（引导、空状态、成功庆祝） | 允许 delight（乐趣预算在这） |

**键盘触发操作一律不动画**（Raycast 打开无动画，这才是对的）。动画的合法目的只有 6 种：反馈、空间一致性、状态指示、防止突兀跳变、解释（仅营销/引导）、delight（仅稀有档）。"好看"不算理由。

### 2.2 缓动（Easing）

| 场景 | 曲线 |
| --- | --- |
| 进入/退出 | `ease-out` |
| 屏幕内移动/变形 | `ease-in-out` |
| hover/颜色变化 | `ease` |
| 恒定运动（进度条、跑马灯） | `linear` |
| 默认 | `ease-out` |

**UI 上永远不用 `ease-in`**。内置缓动太弱，用强自定义曲线（后续统一为 CSS 变量 token）：

```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);        /* 强 ease-out：UI 进出 */
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);    /* 强 ease-in-out：屏内移动 */
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);     /* iOS 抽屉曲线 */
```

### 2.3 时长（Duration）

| 元素 | 时长 |
| --- | --- |
| 按钮按压反馈 | 100–160ms |
| Tooltip、小 popover | 125–200ms |
| 下拉、select | 150–250ms |
| Modal、抽屉 | 200–500ms |
| 营销/解释性 | 可更长 |

**铁律：UI 动画一律 <300ms**。180ms 的下拉比 400ms 的更跟手。

### 2.4 物理感（Physicality）

- **永远不 `scale(0)`**：入场从 `scale(0.9–0.97) + opacity: 0` 开始（现实世界没有东西从无到有）。
- **popover/dropdown 从触发器生长**（`transform-origin` 指向触发元素）；**modal 例外**，保持居中。
- 按钮按压：`:active { transform: scale(0.97) }`，transition 160ms ease-out。
- Spring（物理弹簧）：`{ duration: 0.5, bounce: 0.2 }`（Apple 风格）或 `{ mass: 1, stiffness: 100, damping: 10 }`；bounce 保持 0.1–0.3，只在拖拽/俏皮交互用。
- **Stagger**：组入场 30–80ms 间隔，装饰性，绝不阻塞交互。

### 2.5 性能（Performance）

- **只动 `transform` 和 `opacity`**（GPU 合成）；`width/height/margin/padding/top/left` 全触发布局重排，禁。
- `clip-path` 是唯一合法第四属性（reveal、tab 颜色过渡、hold-to-confirm）。
- **CSS 动画优于 JS（rAF）**：CSS 在主线程外跑，页面忙时不掉帧；JS 只用于动态/可中断/手势类。
- 需要 JS 控制又要 CSS 性能 → **WAAPI**（`element.animate()`）。
- 不要用父元素 CSS 变量驱动子元素 transform（全子树样式重算）。

### 2.6 中断与退出

- 快速重复触发（toast、开关）用 **CSS transition**（可中断重定向），**不用 keyframes**（从头重启）。
- 入场免 JS：`@starting-style`。
- **退出的路径和进入对称**（从哪边进从哪边出）。

### 2.7 无障碍（随动画一起交付，不是事后补）

```css
@media (prefers-reduced-motion: reduce) { /* 减弱而非归零：保留透明度/颜色过渡，去掉位移 */ }
@media (hover: hover) and (pointer: fine) { /* hover 动画只对精确指针设备生效，触摸不误触发 */ }
```

## 3. 对我们 PC 重设计的启示（find-animation-opportunities 思维）

按频率门禁筛选本站 PC 端候选：

**✅ 应该做（按杠杆排序）**
1. 按钮/卡片/文章项按压反馈 `scale(0.97)` 160ms —— 反馈类，高频但近不可感知，成本极低（纯 CSS）
2. 导航下拉/搜索面板/邀请码弹层：从触发器 scale 生长，150–250ms ease-out，origin-aware —— 空间一致性
3. 登录/邀请码 modal：居中 scale(0.96) + backdrop 250ms ease-out —— 偶尔档
4. 收藏/划线/解析按钮的状态切换：颜色 crossfade（`ease`）—— 状态指示
5. 文章列表 hover：极轻微 lift + shadow（150–200ms ease-out，且 `(hover:hover) and (pointer:fine)` 门控）—— 几十次/天档，只能近不可感知
6. 首次访问引导/每日一练完成庆祝（稀有档）：stagger 30–80ms / spring bounce ≤0.3 —— delight 预算

**❌ 明确不做（门禁拒绝）**
- 首页/列表的滚动 reveal、正文滚动动画 —— 用户每天读的功能性内容，动画妨碍阅读
- 键盘操作（快捷键）动画
- 任何 >300ms 的装饰性动画

## 4. 与 anime.js 的关系（修正 0017 原假设）

0017 原假设"用 anime.js 做全部动效"。调研后按"最便宜的够用工具"原则修正：

| 场景 | 工具 |
| --- | --- |
| hover / 按压 / 颜色 / 状态切换 | **纯 CSS transition**（不引入 JS） |
| 入场（无 JS 状态） | CSS `@starting-style` |
| 预定动画、页面忙时也要流畅 | CSS animation（主线程外） |
| 需要 JS 编排：滚动 reveal、stagger 组、数字滚动、时间线 orchestration、页面过渡 | **anime.js**（或 WAAPI） |
| 手势/弹簧 | anime.js spring 或 WAAPI |

结论：**CSS 优先，anime.js 只做需要 JS 编排的那一小撮**（这正是 Emil 与 Anime.js 作者共同认可的主流做法）。anime.js 的 easing 支持 cubic-bezier，与 2.2 的 token 统一。动效丰富 ≠ 到处动，而是"该动的地方动得准"。

## 5. Task 模板复用（improve-animations/PLAN-TEMPLATE）

Task 文件采用该模板结构，保证"零上下文执行者"也能照做：
**Problem（现状+位置+现状代码）→ Target（精确数值，禁止"用更顺滑的缓动"这类模糊描述）→ Repo 约定 → Steps（每步一个具体编辑）→ Boundaries（不碰范围外文件/不加依赖/漂移就停下报告）→ Verification（机械检查命令 + 手感检查清单 + reduced-motion 检查）**

## 6. 参考来源

- 仓库 README：[github.com/emilkowalski/skills](https://github.com/emilkowalski/skills)
- 动画课程/文章：[animations.dev](https://animations.dev/)、[emilkowal.ski/ui](https://emilkowal.ski/ui)（含 "You Don't Need Animations"、"7 Practical Animation Tips"、"Agents with Taste"）
- 缓动曲线库：[easing.dev](https://easing.dev/)、[easings.co](https://easings.co/)（不自己造曲线）
- 第三方衍生：[delphi-ai/animate-skill](https://github.com/delphi-ai/animate-skill)（基于 Emil 课程）、[awesomeskills.dev 收录](https://www.awesomeskills.dev/fr/skill/dot-skills-emilkowal-animations)、[今日头条介绍](https://www.toutiao.com/article/7675396109539230243/)
