# 提案 0010：每日一练扩充 · 后台框架选型 · 头像 · 功能缺口

- **状态**：调研结论（待拍板）
- **日期**：2026-08-16
- **范围**：`pipeline/src/kaogong/practice.py`、`pipeline/src/kaogong/pipeline.py`、`apps/web/src/pages/practice.astro`、`apps/web/src/layouts/Base.astro`、`pipeline/src/kaogong/review/`

## ② 每日一练：扩到 20 题 + 历史刷题

### 现状

`practice.py` 用 `target_count(text) = len(text) // 120` 出题（3–30 上限）。但材料是 `_digest_text` 拼的**标题+摘要**，而 digest 里大部分条目只有标题没有摘要（摘要只在 pubdate 源有），所以今天 22 篇文章只出了 **5 题**。

### 结论：能做，但要先喂足材料

要出 20 道**有依据**的题（不能 AI 硬编），得把剪藏原文里的 `aiSummary` + `keySentences` + AI 标注喂给出题，而不是光喂标题。改法：

1. `pipeline.py` 的 `_digest_text` → 改为「标题 + AI 概括 + 金句 + 关键标注」的富材料（从 `article-*.json` 读）。
2. `practice.py` 的 `target_count` → 目标固定为 20（材料不足时按 120 字/题自然缩水，但不硬凑）。
3. 出题覆盖「当天文章」，按栏目/主题分布（全国时政、申论精读、地方要闻都要出到）。

### 历史刷题（缩略 + 点击展开）

`practice.astro` 当前只显示最新一期。加「历史刷题」：

- 列出历史题集（日期 + 题目数），默认**缩略**（只显示日期/题数/来源）。
- 点击展开：显示该期题目 + 直接作答/看答案。
- 数据源：`content/*/practice.json`（`listPracticeSets()` 已可列，需扩展读取）。

## ③ 后台框架：直接抄哪个

现状：审核后台是「FastAPI + 一个手写 HTML」。要「不造轮子」，有三档选型：

| 档位 | 方案 | 代价 | 适合 |
| --- | --- | --- | --- |
| A（最轻） | **Tabler**（MIT，Bootstrap 后台模板） | 换皮，后端 FastAPI 不动 | 现在这样小工具，最快 |
| B（你已喜欢） | **shadcn/ui + 仪表盘布局**（React） | 后台前端要引入 React | 想要现代质感 + 可长期演进 |
| C（最全） | **Ant Design Pro / Arco Design Pro**（React/Vue，中文生态） | 重，组件超全 | 后台功能变多后 |

**我的建议**：先 **A（Tabler）** —— 现在后台就「抓取/补跑 AI/发布/字体」几个动作，Tabler 是 MIT 开源的成熟后台模板，直接套它的布局和组件，后端零改动，半天能换完。等后台功能多了再升级 B/C 不迟。

参考：[Tabler](https://tabler.io/)、[shadcn/ui](https://ui.shadcn.com/)、[Ant Design Pro](https://pro.ant.design/)、[免费后台模板清单](https://colorlib.com/wp/free-bootstrap-admin-dashboard-templates/)。

## ④ 登录后用微软 emoji 当头像

现状：登录后顶栏只显示 QQ 邮箱前缀文字。

**结论：可以，而且很轻。** 方案：

- 用 [Microsoft Fluent Emoji](https://github.com/microsoft/fluentui-emoji)（开源）里的一小撮做「头像池」。
- 对邮箱做**确定性哈希** → 从池子里选一个 emoji 作为该用户固定头像（同一个人每次登录头像不变）。
- 顶栏：`[emoji头像] + 邮箱前缀`，emoji 用 Fluent 3D 风格 PNG/SVG（可走 CDN）或回退原生 emoji。

**要点**：确定性（同一邮箱同一头像）、无需存图、几行 JS 搞定。

## ⑤ 我认为最缺的功能（后台 + 网页端）

### 后台（最缺，按优先级）

1. **来源管理后台** —— 新闻源现在硬编码在 `sources.py`，每次加源要改代码 + 提交流程。做成「后台增删改源（URL/正则/翻页/限额）+ 存配置 + 一键重抓」，这是后台最该补的。
2. **内容搜索/筛选** —— 跨日期搜标题/正文，快速定位。
3. **数据统计面板** —— 每日候选/文章/AI 成功率的趋势图。

### 网页端（服务考生，按优先级）

1. **错题本 / 刷题记录** —— 配合每日一练，记录错题，可回顾重刷（考生刚需）。
2. **文章目录（TOC）+ 阅读进度** —— 长文导航 + 记住读到哪里。
3. **全文搜索增强** —— 现在的搜索可能是标题级，扩展到正文 + 划线。
4. **打印 / 导出 PDF** —— 线下学习。

## 建议动手顺序

1. ② 每日一练 20 题 + 历史刷题（对考生价值最大）
2. ④ emoji 头像（最轻，顺手做）
3. ③ 后台换 Tabler 皮（可选，看你要不要先换）
4. ⑤ 里的「来源管理后台」+「错题本」（下一批）

---

**待你拍板**：②（20 题 + 历史刷题）和 ④（emoji 头像）我现在就可以做；③ 你要不要换 Tabler？⑤ 想先做哪几个？
