# Kaogong Cloud Design System

## 1. Atmosphere & Identity

Kaogong Cloud 是**备考手账**气质：官方材料以干净纸面呈现，标注是"笔迹"而非"UI"——中心句 [ ] 大括号、支撑句荧光笔、手绘箭头，全部保持书写感；正文保持印刷感（宋体/楷体），分层原则见 §9。深蓝/护眼豆沙绿的底色 token 保留，质感换为纸面。

## 2. Color

实现源：`apps/web/src/styles/global.css`（token 不变，新增标注红）。

| 角色 | Token | Light | Dark | 用法 |
| --- | --- | --- | --- | --- |
| Canvas | `--bg` | `#f5f7fa` | `#0d1117` | 页面背景（护眼豆沙绿系保留） |
| Surface | `--surface` | `#ffffff` | `#161b22` | 卡片、阅读纸面 |
| Editorial accent | `--accent` | `#a06d08` | `#e3b341` | 引用与划线 |
| **标注红** | `--rel-color` | `#b2493a` | `#c96a5a` | **关系标注主色**（[ ] / 箭头；全局样式面板可改） |
| **荧光笔** | `--rel-hl` | `#e8b93c` | `#8a7420` | 支撑句荧光（透明度 `--rel-hl-opacity` 默认 0.32） |

规则：标注红只用于批注语义，不作为导航/按钮主色；样式面板改全局（`relation-style.json`）。

## 3. Typography

阅读正文：宋体/楷体（印刷感，`--font-serif`）；UI 与标题：PingFang SC / 微软雅黑。
**手写体（2026-08-22 拍板）**：站酷快乐体（标题/标注/UI 点缀）+ 手书体/楷体变体（温润），双字体均需**商免清单核验**（font.luhui.net），文件由用户自备授权放入 `apps/web/public/fonts/`（子集化走 `pipeline/src/kaogong/fonts.py` 既有管道，`font-config.json` 注册）。**正文禁止手写体**（可读性）。

## 4. Spacing & Layout

- 4px 基线；`--s-1..6` / `--r-xs..lg` 不变；主内容 80% 居中、<640px 全宽；375/768/1280px 无横向溢出。
- **连线走廊**：阅读页关系 overlay 向左扩 64px（`margin-left: -64px`），仅在 ≥900px 视口启用左走廊；窄屏直箭头 + 移动端结构卡片。

## 5. Components

卡片/按钮/表单/订阅/导航：保持既有语义与无障碍约束（WCAG 2.2 AA、44px 触控、aria-live）。新增：
- 「连线」模式：工具栏开关按钮（默认关；无关系时 disabled）。
- 移动端结构卡片：点击中心句弹出底部固定面板（中心句全文 + 支撑点列表 + 关闭），移动连线模式的替代呈现。

## 6. Motion & Interaction

- 微交互 150ms；导航 250ms；首页极光 16-22s。
- **书写动画**（rough-notation [ ]/荧光笔/下划线）：首次进入视图播放一次（约 800ms），`prefers-reduced-motion` 关闭。
- 箭头/标注仅 transform+opacity 动画；不布局动画。

## 7. Depth & Surface

卡片单像素 token 边框 + 纸面底（`#fffdf8` 阅读区）；悬浮阅读工具用 `--shadow`；**纸张感**：阅读区纸面（微纹理可选 CSS 噪点）、卡片圆角不规则化（如 `12px 8px 14px 10px`，克制）——作为视觉层渐进落地项，禁止大面积装饰。

## 8. Accessibility & Accepted Debt

- 目标 WCAG 2.2 AA；标注为装饰（`aria-hidden` overlay），语义走既有 `aria-label`/`data-explanation`。
- 字体授权（商用字体需自备，README 红线）是本阶段接受的债务：站酷快乐体/手书体未接入前用系统字体回退。

## 9. 手绘标注层（2026-08-22 定稿）

| 层 | 元素 | 技术 |
| --- | --- | --- |
| 中心句 | 红色手绘双括号 [ ]（书写动画） | rough-notation（MIT，vendored `public/vendor/`） |
| 支撑句 | 淡黄荧光笔（透明度可调） | rough-notation highlight |
| 指向 | 手绘箭头素材（默认 `41.svg`；素材库 185 支 `public/vendor/handy/` + 上传自定义） | SVG 素材 + 矢量摆放 |
| 方向 | 上指=锚定句最上行 / 下指=最下行 | `aiRelations.direction` |

- **分层**：上面所有为"批注层"；正文印刷层不受影响（font、颜色、行距不因标注改变）。
- **数据分层**：样式=全局配置（`relation-style.json`，样式面板改），素材选择/方向=每点数据（`aiRelations.points[].style`），不做表现层进内容结构。
- 标注在「连线」模式（默认关）中显示；AI 标注模式关闭时同步隐藏。
