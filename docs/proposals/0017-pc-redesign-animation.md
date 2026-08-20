# 提案 0017：PC 端大改 + 动效方案（anime.js 调研）

> 状态：待审核。先调研（不写代码）：anime.js 是否符合项目、是否需要换框架、替代方案对比、建议方案。

## 1. 背景

- 移动端优化暂缓（提案 0016 挂起）；**PC 端要大改**。
- 候选动效库：[juliangarnier/anime](https://github.com/juliangarnier/anime)（anime.js）。
- 问题：① 它符不符合我们的项目？② 用它是否需要换框架？③ 有没有其他类似项目？

## 2. anime.js 调研结论

### 2.1 是什么、当前状态

- **anime.js v4**（2025 年发布的 v4.0.0，现 v4.3.x）：完全重写，TypeScript + ESM、零依赖、gzip 后约 7–15KB。
- 核心是**动画引擎**：`animate` / `stagger`（交错）/ `timeline`（时间线）/ `scrub`（滚动联动）/ keyframes / SVG / 颜色 / 弹簧与惯性缓动等。
- 10 年历史的老牌库，生态成熟（[官方 Release](https://github.com/juliangarnier/anime/releases/tag/v4.0.0)、[v4 指南](https://most.tw/posts/programminglanguage/animejs-v4-animation-guide-2026/)）。

### 2.2 关键判断：它是"动效引擎"，不是"UI 组件库"

- anime.js 提供的是**运动能力**（滚动浮现、悬停反馈、交错入场、数字滚动、转场），**不提供现成 UI 组件**（卡片、导航、轮播等仍是我们自己的 HTML/CSS）。
- 对我们的项目（时政阅读站，`DESIGN.md` 定位是"沉静的编辑部气质：学院蓝 + 克制金 + 宋体标题"），动效应**克制、辅助阅读**，而非炫技。anime.js 完全能做"克制的微动效"。

### 2.3 框架问题：**不需要换框架**

- anime.js 是**框架无关**的原生 JS 库。Astro 的 `<script>`（client-side）直接 import 即可，静态站照旧。
- 结论：**前端继续用 Astro，不加 React/Vue**；把 anime.js 作为渐进增强的动效层（不依赖它的 JS 也能正常阅读，符合"内容站先可用后好看"）。

## 3. 替代方案对比（2026 视角）

| 库 | 定位 | 体积 | 许可 | 适合我们？ |
|---|---|---|---|---|
| [anime.js v4](https://github.com/juliangarnier/anime) | 通用动画引擎（滚动/交错/时间线） | ~7–15KB gzip | MIT | ✅ 首选：轻、零依赖、Astro 友好 |
| [GSAP](https://gsap.com/) | 行业标准动画 + ScrollTrigger 等插件 | 核心 ~20KB+ | 免费核心，付费插件（SplitText 等） | ⚠️ 更重，功能冗余；ScrollTrigger 强但本项目用不上全部 |
| [Motion](https://motion.dev/)（前 Framer Motion） | 声明式动画，框架无关 + React | 轻 | MIT | 可选：API 现代，但生态较新 |
| [Lenis](https://github.com/darkroomengineering/lenis) | 平滑滚动（仅滚动） | 极小 | MIT | 可选：只解决"丝滑滚动"一项 |
| AOS / ScrollReveal | 纯滚动浮现 | 极小 | MIT | 简单场景够用，但灵活性差 |
| 纯 CSS + IntersectionObserver | 零依赖 | 0 | — | 最轻，适合只做 2–3 种固定动效 |

> 对比参考：[npm-compare animejs/gsap/motion](https://npm-compare.com/animejs,framer-motion,gsap,motion,react-motion,react-spring,react-transition-group)、[GSAP Alternatives 2026](https://annnimate.com/compare/gsap-alternatives)。

## 4. 建议方案（PC 大改 + 动效）

### 4.1 动效原则（贴合"沉静阅读站"）

1. **渐进增强**：无 JS 也能完整阅读；动效只做装饰层。
2. **克制**：单次动效 ≤600ms、仅 1–2 种强调色、滚动浮现以"淡入 + 上移 12–16px"为主。
3. **性能**：只动 `transform/opacity`；`IntersectionObserver` 触发，首屏不重播。

### 4.2 具体动效清单（PC 端）

| 位置 | 动效 | 实现 |
|---|---|---|
| 首页 | 文章卡片**交错浮现**（滚动进入视口，stagger 60ms） | anime.js `stagger` + IO |
| 首页 | 今日速览横幅：关键词标签**逐个浮现** | `stagger` + `delay` |
| 阅读页 | 段落**淡入上移**（滚动到该段时） | `scrub`/IO |
| 全局 | 顶部导航**滚动后收窄 + 阴影**（已有 collapsed，加过渡） | CSS transition |
| 全局 | 按钮/卡片**悬停微反馈**（上浮 2px + 阴影加深） | CSS 即可，不必引库 |
| 可选 | 数据统计数字滚动（审核台/统计页） | anime.js `animate` |

### 4.3 集成方式（Astro）

- `pnpm add animejs`（v4 包名 `animejs`），在需要的页面 `<script>` 里 `import { animate, stagger } from "animejs"`。
- 抽一个 `src/lib/motion.ts` 统一管理动效入口（尊重 `prefers-reduced-motion`）。
- 只给 PC 端（`@media (min-width: 769px)`）启用，移动端不加动效（省性能 + 移动端另做体验）。

### 4.4 与现有 CSS 的关系

- 现有 `global.css` 的 `hero__aurora` 背景动画、卡片阴影等保留；anime.js 只加"滚动触发 + 交错"类动效，不推翻现有样式。

## 5. 待确认决策

1. **选型**：anime.js（推荐）还是 GSAP（滚动叙事更强但更重）或零依赖 CSS+IO（最保守）？
2. **动效强度**：只做「卡片交错浮现 + 段落淡入」的克制版，还是允许更丰富的转场/滚动叙事？
3. **PC 大改范围**：是视觉重设计（配色/字体/间距体系按 DESIGN.md 深化），还是仅加动效？两者要一起规划（提案 0017 先定动效，视觉重设计可另开提案）。
4. **移动端**：维持提案 0016 挂起，等 PC 定稿后再做（推荐）。
