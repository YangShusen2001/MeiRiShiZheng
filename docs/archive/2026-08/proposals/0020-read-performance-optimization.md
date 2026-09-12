# 提案 0020：阅读页滑动卡顿修复与滚动性能优化

- 状态：**已实施，待用户确认**（2026-08-20）
- 触发：用户反馈"阅读页滑动卡顿"，定位到阅读进度条
- 关联：0017 §3.2（动效数值标准——只动 transform/opacity）

## 1. 根因审查（代码级）

### 1.1 主因：阅读进度条 = 每帧 layout thrashing

`[id].astro` 的进度条实现（已删除）：

```js
progressBar.style.width = `${...}%`;          // 每次 scroll 事件直接改 width
window.addEventListener("scroll", updateProgress, { passive: true });  // 一帧可触发多次
```

- **width 是 layout 属性**：每次赋值强制浏览器重排（layout）+ 重绘（paint）+ 合成，阅读页正文段落在滚动时持续被重排——这就是卡顿源。
- scroll 事件**一帧可触发多次**，无节流，放大开销。
- 附带 `transition: width 80ms`，每帧插值再添一次 layout。
- 违反 0017 §3.2 硬规则"只动 transform/opacity"（width/height/top/left 触发全部三步渲染）——实现时未遵守自己的标准，教训写进提案。

### 1.2 次因：Base.astro 导航 onScroll 无节流

`classList.toggle` 本身不触发 layout，但 scroll 事件高频执行（每帧多次）仍属浪费；且 `.top.scrolled` 切换 backdrop-filter + box-shadow 会触发重绘。

### 1.3 已排查无问题项

- 阅读页无其他滚动监听；段落/标注 DOM 量级小，无虚拟滚动需求
- `.top`/`.tabbar` 的 backdrop-filter 区域小（顶栏/底栏），非卡顿源
- `html { scroll-behavior: smooth }` 不影响滚动性能

## 2. 修复（已实施）

| 项 | 改动 |
| --- | --- |
| 阅读进度条 | **整体去除**（用户决策）：`[id].astro` 元素 + JS 监听、`global.css` `.read-progress` 样式全部删除 |
| 导航 onScroll | Base.astro 加 **rAF 节流**（一帧只处理一次 classList 切换） |

## 3. 验证

- 阅读页长文滚动：肉眼确认无卡顿（用户本地验证）
- 若日后想恢复进度条：用 `transform: scaleX(1 - p)` + `transform-origin: left`（GPU 合成，不触发 layout），scroll 监听包 rAF 节流——写入备忘，不在本次范围。

## 4. 教训

- 动效/滚动相关实现必须过一遍 0017 §3.2 的"只动 transform/opacity"清单；scroll 监听一律 rAF 节流。
- 提案 §3.2 数值标准应作为实现前 checklist，而不是事后引用。
