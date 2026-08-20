# TASK-0020：PC 视觉重设计与动效 + 移动端体验（提案 0017 整合版）

## Status

pending

## Owner

待分配（默认主开发 Agent）

## Dependencies

- 提案 `docs/proposals/0017-pc-redesign-animation.md` 审核通过（含 §9 五项决策拍板）
- 提案 `docs/proposals/0019-highlight-undo-research.md`（划线对象模型方案 B，已并入 0017 P3；实现时引用其 §2 主流做法与 §3 方案 B 设计）
- 提案 `docs/proposals/0016-mobile-ux.md`（已并入 0017，仅追溯用）
- 动效数值标准：`docs/proposals/_research_emil/SUMMARY.md`（实现时必须引用其数值，禁止自造曲线/时长）
- 无其他任务依赖；0018（审核台）独立、不同步执行

## Goal

按 0017 整合版落地 PC 视觉重设计与动效（CSS 优先 + anime.js 仅做 JS 编排）+ 移动端拇指体验（触控 44px / 划线就近弹出 / 高频操作沉底），保持"沉静的编辑部气质"定位与现有明暗 token，遵守频率门禁与精确数值标准。

## Allowed Files

- `apps/web/src/styles/global.css`（token 新增：`--ease-out`/`--ease-in-out`/`--ease-drawer`、时长 scale、`--shadow-lg`；按压/hover/modal/下拉动效；reduced-motion 与 `(hover:hover)(pointer:fine)` 门控）
- `apps/web/src/layouts/Base.astro`（导航 sticky 过渡、下拉面板 origin-aware 动效、主题切换 crossfade、移动端底部栏入口）
- `apps/web/src/lib/motion.ts`（新增：统一动效入口，reduced-motion 检查 + IntersectionObserver once + anime.js 封装，<769px 不初始化）
- `apps/web/src/pages/index.astro`（卡片/速览 stagger 入场）
- `apps/web/src/pages/[id].astro`（**划线对象模型重做**：v2 存储 + 跨段一次删 + undo 栈/Ctrl+Z + hover 菜单；移动端划线工具栏就近弹出、A−/A＋/AI 标注模式沉底、去除长按/二次确认、正文不动画）
- `apps/web/src/lib/highlights.ts`（**对象层新增**：Highlight 对象 API、v1→v2 迁移；区间纯函数保留复用）
- `apps/web/src/lib/highlights-migrate.ts`（**新增**：v1 数据迁移函数，供单测）
- `apps/web/src/pages/practice.astro`（触控 44px、结果 delight spring、数字滚动）
- `apps/web/src/pages/favorites.astro`（列表整行可点、删除按钮 ≥44px）
- `apps/web/src/pages/search.astro`（面板动效、标签 stagger、触控目标）
- `apps/web/src/pages/[date].astro`（卡片样式统一）
- `apps/web/package.json`（仅新增 `animejs` 依赖）

**禁止改动**：`apps/api`、`pipeline`、`packages/contracts`、审核台、页面结构（HTML 骨架）与路由。

## Acceptance Criteria

### P0 动效基础
- [ ] `global.css` 新增动效 token（三条 easing + 时长 scale），无自造曲线
- [ ] 全部可点元素按压反馈 `scale(0.97)` / 160ms / ease-out
- [ ] 卡片 hover 上浮+阴影，150–200ms，`(hover:hover)(pointer:fine)` 门控
- [ ] 下拉/搜索/邀请码面板从触发器生长（transform-origin），200ms ease-out
- [ ] 登录/邀请码 modal scale(0.96)+opacity 250ms + backdrop 同步；never scale(0)
- [ ] `prefers-reduced-motion: reduce` 下：位移消失、透明度过渡保留

### P1 PC 视觉
- [ ] 首页卡片/hero/速览样式按 §5 深化，明暗主题均正常
- [ ] 导航 sticky 收窄补 200ms 过渡；阅读页排版深化
- [ ] 列表/搜索/收藏/练习卡片样式统一（共用 token）

### P2 动效编排（anime.js）
- [ ] `motion.ts` 就位：reduced-motion 检查 + IO once + <769px 不初始化
- [ ] 首页卡片组 stagger（间隔 40ms、300ms ease-out、IO once 不重播、不阻塞交互）
- [ ] 速览/搜索标签 stagger 30–50ms
- [ ] 练习完成 delight spring `{duration:0.5, bounce:0.2}`；数字滚动 600ms
- [ ] 移动端（<769px）无 stagger/滚动动效

### P3 移动端 + 划线重做
- [ ] 触控目标 ≥44px（`q-opt`/`wq-opt`/`.btn`/`fav-filter`/删除按钮）
- [ ] **划线对象模型**：Highlight 对象（id/quote/ranges/styles/note/explanation/createdAt）+ v2 存储 + v1→v2 迁移（旧划线保留，迁移函数有单测）
- [ ] **跨段划线一次删除**（hover 菜单：删除整条/删除本段）
- [ ] **undo 栈**：逆操作入栈（上限 50），Ctrl+Z 与工具栏「↩ 撤销」逐级回退，可中断重定向
- [ ] **quote 锚点**：内容更新后按引文重定位（重抓不错位）
- [ ] 划线工具栏就近弹出（选区上/下方，溢出翻边）
- [ ] A−/A＋、AI 标注模式切换沉底（与划线工具栏同底部栏）
- [ ] 「去除」长按呼出或二次确认；列表项整行可点
- [ ] 底部安全区 `env(safe-area-inset-bottom)` 补齐
- [ ] 底部 Tab 导航（首页/搜索/每日一练/收藏/我的，顶部菜单简化为「我的/更多」）

## Verification

```text
机械检查（每阶段）：
  cd D:\kaogong-cloud-v2
  pnpm -r typecheck
  pnpm -r test            # web 36 用例基线不得减少
  cd apps/web && $env:PUBLIC_API_BASE='https://api.meirishizheng.cn' pnpm build   # 构建通过

手感检查（P0/P2 后必做，非可选）：
  1. DevTools Animations 面板 10% 慢放：进入/退出曲线不突兀、无中途急停
  2. 连续快速开关下拉/弹层：transition 可中断重定向，不从零重启（不用 keyframes）
  3. Rendering 面板开启 prefers-reduced-motion：位移消失、opacity 反馈保留
  4. 触发 hover 动效后 DevTools 模拟触摸：无残留 hover 状态
  5. 真机（或 DevTools 设备模式）移动端：选文 → 工具栏就近出现；单手拇指可达底部栏
  6. 刷新/来回滚动首页：stagger 只播一次（IO once），不重播不阻塞
  7. 次日 fresh-eyes 复查：任何"看着不对"的动效按数值表重新调，不凭感觉
  8. 划线（P3）：跨 3 段划线 → hover 任一段「删除整条」一次删净；Ctrl+Z 逐级回退到划线前；刷新页面划线仍在（v2 持久化）
  9. 迁移（P3）：先用旧版划几条线 → 部署新版 → 旧划线完整保留且可删除/撤销（v1→v2 迁移单测通过）
  10. 重抓错位（P3）：修改正文段落（模拟内容更新）→ 划线按 quote 重新定位不错位
```

## Handoff

```text
任务：TASK-0020 PC 视觉重设计与动效 + 移动端体验
负责人：
修改文件：见 Allowed Files
实现内容：
契约变化：无（纯前端样式与渐进增强脚本；apps/web package.json 增 animejs）
测试命令：pnpm -r typecheck && pnpm -r test；web build（需 PUBLIC_API_BASE）
测试结果：
已知问题：
下游 Agent 注意事项：动效数值一律来自 _research_emil/SUMMARY.md；审核台/API 不受影响
是否满足验收标准：
```

## Notes

- 实现顺序按 P0 → P1 → P2 → P3 → P4，每阶段独立验收后再进下一阶段。
- 若实际代码与提案描述漂移（文件不存在、结构变化），停下报告，不要即兴发挥。
- 动效"丰富"≠到处动：频率门禁拒绝清单（正文滚动动画、键盘操作动画、>300ms 装饰）是硬边界。
- P3 划线重做（0019 方案 B）与移动端工具栏是同一交互层，**合并实施**（估计 3–4 天量级）；`highlights.ts` 区间纯函数与 web 36 用例基线尽量少动，对象层在其上新增，v1→v2 迁移必须单测。
- 存储 key：v2 用 `kaogong.highlights.v2.{articleId}`（或同 key 版本化升级，迁移后清理 v1 数据）。
