# 0018 审核台重构：条目级状态工作台（含 08-20 补跑诊断）

- 状态：**已实施，待用户审核**（2026-08-20 完成 Phase A/B/C，pipeline 测试 156 通过；审核通过后 commit）
- 日期：2026-08-20
- 关联：0013（审核 Agent）、0014（南方时评/候选池）、0015（开源）
- 触发：补跑 2026-08-20 后「质量门禁 failed + 3 条剪藏失败」，用户无法从现有审核台定位是哪几篇、为什么、怎么处理；同时要求调研「主流的成熟做法」后重构后台。

---

## 1. 08-20 补跑诊断结论（先说清楚"是什么情况"）

### 1.1 三条剪藏失败的具体定位

| 标题 | 实际 URL | 根因 |
| --- | --- | --- |
| 省运会马拉松游泳首日决出两金 | https://www.gd.gov.cn/gdywdt/dsdt/content/post_4944691.html | 正文真的只有 1 段（130 字短讯），其余全是页脚噪声；`len(paras) < 2` 判失败 |
| 戎装换农装 种出"共富椒"丨理响巴蜀 | https://sichuan.scol.com.cn/ggxw/202608/83308306.html | **视频稿**，页面无 `<p>` 正文，提出 0 段 |
| 四川民办高校的同学注意！交钱只能交到官方账户，正规收费只有四项丨政策翻译机 | https://sichuan.scol.com.cn/ggxw/202608/83308083.html | **视频稿**，只有 1 段导语（"今天一条视频讲清楚…"） |

已实测复现：`extract_paragraphs` 对上述 3 个页面分别得到 1/0/1 段，与报告 clipDetails 一致。**不是提取器 bug，是内容本身不适合纯文本站**：scol 的「理响巴蜀」「政策翻译机」等是视频栏目；gd.gov.cn 那条是 130 字短讯。

### 1.2 「重写 0 篇」是正常行为

`/api/reanalyze` 默认 `force_ai=False`：只对 aiStatus != ok 的文章重新调 AI，已成功的 33 篇只做正文清洗（不调 AI），清洗结果与原文一致 → 写入 0 篇。**补跑按钮没有坏**。想强制重生成标注需 force（会烧 API 额度，当前 UI 没暴露）。

### 1.3 「数量:below_half_baseline」的触发数学

`quality.volume_errors`：基线 = 目标日期之前**最近一份 qualityStatus ∈ {ok, degraded} 的报告**（即 08-19：候选 75 / 文章 59）。判据 `当前值 × 2 < 基线`：

- candidates：36 × 2 = 72 < 75 → **触发**
- articles：33 × 2 = 66 ≥ 59 → 未触发

门禁按设计工作，但有两个问题：基线只取**最近一次**（单日波动即误报）；08-19 本身也是 degraded（75 候选 → 59 文章，16 条丢失），拿它当"正常基线"并不稳。08-20 当天 17 个源全部 OK、无来源错误，36 候选是真实的低产出日（各源列表页当天内容少），不是管线故障。

### 1.4 digest 36 → 27 的来龙去脉

19:11 抓取产出 36 候选 → 剪藏 33 成功 + 3 失败 → 19:24 AI 审核「应用」阶段判 drop 了 9 条（含 2 条已剪藏成功的视频栏目稿，如「AI客服转人工比取经还难丨政策翻译机」——它们正文只有导语+制作名单，被审核 Agent 以正文过短/信息量低判掉）→ digest.json 变为 27 条，digest.json.bak 保留 36 条原版。这条链路**每一步都有据可查，但没有一步在界面上可见**——这就是用户困惑的来源。

---

## 2. 现状差距（为什么"不知道是哪篇"）

1. 失败条目只出现在顶部**日志文本框**里（`❌ 标题（原因）`），不可点击、不可定位、不可重试；左侧清单只有 digest 条目，没有剪藏/AI 状态徽标。
2. 剪藏失败原因只有一行字符串（如"正文提取过短（1 段）"），没有分类，没有建议动作（重试？跳过？强制收录？）。
3. 门禁失败不解释（"数量:below_half_baseline"对用户不可操作），也没有"哪些源、哪些条目导致"的钻取。
4. 被 drop 的 9 条只在「已应用的改动」小面板里出现一次，之后消失。
5. 无批量重试、无历史趋势、无操作审计。

---

## 3. 主流成熟做法调研

### 3.1 内容审核队列 / 工作台（CMS moderation queue）

主流 CMS/审核产品都围绕**条目级状态机 + 队列视图 + 批量操作**组织：

- 状态流转（pending → approved/rejected → published），每条目状态徽标，可按状态筛选，批量处理，全程可审计——[AppMaster: Content moderation queue design](https://appmaster.io/blog/content-moderation-queue-design)
- 审核表的标准形态：状态列 + 原因列 + 操作列，行内徽标与筛选器——[Shadcn UI Blocks: Content Flags Table](https://www.shadcn-ui-blocks.com/blocks/application-pro/admin-moderation/content-flags-table)
- 中文社区同样思路：评论审核的「可见性、状态流转、通知闭环」——[PaperFlow 评论审核设计](https://www.e-com-net.com/article/2042625094559260672.htm)

### 3.2 CI 流水线式任务状态（GitHub Actions 模式）

**"失败可见 + 一键重试"的业界标准**：每个 job 有状态徽标，失败 job 可展开日志，一键 "Re-run failed jobs"（只重跑失败项，不重跑成功项）——[GitHub Docs: Re-running workflows and jobs](https://docs-github.cnmirror.me/en/enterprise@3.18/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)；Gitea 社区也在补这个能力（[gitea#36924: rerun failed jobs](https://github.com/go-gitea/gitea/pull/36924)）。**每个 digest 条目 = 一个 job**，这套交互直接搬。

### 3.3 数据管道任务级可观测（Airflow / Dagster 模式）

Airflow 的 Task Instance 每个有状态（success/failed/upstream_failed/skipped/retrying），点击看 log、可 clear + 重跑；Dagster 进一步做 asset health 与告警——[Orchestrator Decision Matrix（任务图 vs 资产图心智模型）](https://dev.to/gowthampotureddi/airflow-vs-dagster-vs-prefect-vs-kestra-vs-mage-orchestrator-decision-matrix-for-2026-158a)、[Dagster alert policy types](https://docs.dagster.io/guides/observe/alerts/alert-policy-types)。要点：**运行级汇总面板 + 任务级状态 + 日志钻取 + 重试**。

### 3.4 表格化后台（Ant Design Pro 模式）

国内后台的主流形态：ProTable 的状态列徽标渲染、筛选器（状态/来源/日期）、行选择 + 批量操作、行展开详情——[Ant Design ProTable 详解](https://wenku.csdn.net/doc/55i0akhy4y)。我们保持 Tabler + 原生 JS 不引入构建链，但交互模式对齐这套。

### 3.5 错误分类 + 建议动作（error taxonomy → remediation）

成熟系统不会把失败原因当裸字符串展示，而是**分类 + 每类映射建议动作**（重试 / 跳过 / 换源 / 人工介入），再配批量执行。这是 CI、审核中台、数据平台共同的做法（参考 3.1/3.2 的队列与重跑语义）。

### 3.6 技术选型结论

单人运维工具，**不引入 React/AntD 构建链**（`apps/web` 才走构建；审核台保持 FastAPI + 原生 JS 单文件即可，最多引入 HTMX/Alpine.js 轻量增强）。"成熟"体现在交互模式对齐上述四类主流范式，不在框架。

---

## 4. 方案设计

### 4.1 条目状态模型（核心数据契约）

每个 digest 条目挂一个状态对象（数据已全部存在：clipDetails + article-*.json 的 aiStatus/aiError + 审核 decisions，只需聚合）：

```jsonc
{
  "clipStatus": "ok" | "error" | "skipped" | null,
  "clipError": "too_short" | "video_no_text" | "fetch_failed" | "parse_error" | null,
  "clipMeta": { "paragraphs": 1, "chars": 130 },        // 供人判断
  "aiStatus": "ok" | "error" | null,
  "aiError": "ai_api:rate_limit" | "ai_schema:..." | "location:..." | null,
  "verdict": "keep" | "rewrite" | "drop" | "rerun" | "needs_human" | null,
  "excluded": false, "excludeReason": "",
  "actions": ["retry", "exclude", "force-include"]      // 由分类推导的建议动作
}
```

### 4.2 新增 API（审核服务）

- `GET /api/items/{date}` — 统一条目视图：digest 条目 + 状态对象 + 建议动作；`?status=all|failed|clip_error|ai_error|excluded` 筛选。
- `POST /api/items/{date}/{id}/retry` — 单条重试：clip_error 重新剪藏；ai_error 重新分析；成功/失败都写回 clipDetails 与 report。
- `POST /api/items/{date}/retry-failed` — 批量重试全部失败项（GitHub Actions "rerun failed" 语义）。
- `POST /api/items/{date}/{id}/exclude` — 排除并记录原因（进 report.excluded 列表；不发布但可查）。
- `POST /api/items/{date}/{id}/force-include` — 强制收录（用于单段短讯等边界情况，走 clip 门槛放行）。
- `GET /api/reports/{date}` — 报告详情：门禁每条错误的人类可读解释 + 建议动作 + 失败条目清单（替代现在日志里的裸文本）。
- `GET /api/trends` — 各日候选/文章/AI失败/门禁状态序列（趋势图数据）。

### 4.3 UI：审核工作台（改版布局）

- **顶部运行级状态条**：来源 OK/失败、候选/文章/AI 成功/失败、门禁徽标；门禁错误逐条列出且**可点击**（跳转对应筛选/条目）。
- **左侧清单升级**：每行 = 序号 + 标题 + 状态徽标（✅ 剪藏/AI 正常、❌ 剪藏失败、⚠️ AI 失败、🗑 已排除/被 drop）；hover 显示原因；失败行红色高亮置顶；顶部筛选器（全部/仅失败/剪藏失败/AI 失败/已排除）。
- **右侧详情新增状态面板**：剪藏状态 + 原因 + 元数据（段数/字数）+「重试」；AI 状态 + 原因 +「重试」；「排除并记原因」「强制收录」；操作历史（Phase C）。
- **批量操作条**：勾选/全选失败 → 批量重试。
- **趋势页**：现有「统计」下拉升级为折线图（候选/文章/AI失败随日期）+ 门禁历史徽标，让 below_half_baseline 之类一眼可见。

### 4.4 剪藏失败分类 + 源头治理

- clip_error 细分为四类（见 4.1），各映射建议动作：
  - `fetch_failed` → 重试（网络/超时）；
  - `video_no_text` → 建议跳过（视频稿对纯文本站无价值），不阻塞门禁；
  - `too_short` → 人工判断：强制收录（单段 ≥60 字且非页脚，如 gd 短讯）或排除；
  - `parse_error` → 重试/人工。
- **候选阶段源头过滤（治本）**：站点配置 `noiseTitle` 增加 scol 视频栏目关键词：`理响巴蜀`、`政策翻译机`、`空天侦探社`、`食情局`、`C视频`、`成工之恋`、`川观解盘` 等，让视频稿根本不进候选，而不是剪藏时失败。08-20 的 3 条失败 + 2 条被 drop 的视频稿全部命中。
- gd.gov.cn 短讯：门槛维持 `<2 段` 判失败（避免误收噪声页），但失败后可一键「强制收录」。

### 4.5 门禁调优（消除误报）

- 基线从「最近一次 ok/degraded 报告」改为「**最近 N=5 次的候选/文章中位数**」；样本不足 N 时用现有逻辑。
- 门禁错误输出人类可读解释 + 建议动作（如"候选 36 低于近 5 日中位 75 的一半——当天 17 源全部正常，疑似当日产出少，可核对各源列表后手动放行"）。
- 报告增加 `notes` 字段：运行时可手动标注已知原因（如"当天源产出少"），标注后 volume 不再拦截（对应 0013 的闭环语义）。

### 4.6 审计（Phase C）

- `content/_reports/audit.jsonl`：每次操作（抓取/补跑/重试/排除/强制收录/应用/回退/发布）追加 `{ts, action, itemId, detail}`；条目详情面板展示其操作历史。复用现有 .bak 回退机制。

---

## 5. 实施阶段与验收

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| **A（核心）** | /api/items 聚合 + 清单状态徽标 + 失败筛选 + 单条/批量重试 + 排除/强制收录 + 门禁错误可点击 | 补跑 08-20 后，3 条失败在清单可见、可定位、可一键重试/排除；被 drop 的 9 条可查 |
| **B** | 错误分类与建议动作 + scol 视频栏目 noiseTitle 过滤 + gd 短讯强制收录 + 门禁中位数基线 + 趋势图 | 视频稿不再进候选；门禁解释人类可读；趋势图可看 |
| **C** | 审计 JSONL + 操作历史展示 | 任意条目可查完整操作历史；回退可追溯 |

每阶段补测试：pipeline 门禁（中位数基线）、clip（分类）、server API（items/retry/exclude）、web 不变。

---

## 6. 风险与边界

- 门禁基线改动会影响 0013 的闭环判定，需同步更新 `docs/product/review-judging-rubric.md` 与相关测试。
- 强制收录会绕过 `<2 段` 门槛，需保证页脚过滤先行（已具备），避免噪声页混入。
- noiseTitle 过滤是全局关键词，注意不要误伤非视频栏目（如「政策翻译机」有纯文字稿——过滤的是标题中的栏目名，命中即整篇不进，属可接受取舍；也可改为按源配置 title_drop 更精细）。
