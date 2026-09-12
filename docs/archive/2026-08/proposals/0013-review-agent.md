# 提案 0013：审核 Agent（本地化，替代手动逐条审核）

> 状态：已实现（Phase 1/2/3）。把「每日时政」的审核从「人工逐条手改」升级为「Agent 判质量 + 自动修复 + 质量门禁验证」，并把 AI 标注纳入审核台可视化。判定黄金标准见 `docs/product/review-judging-rubric.md`。

## 1. 背景与约束

- 用户每晚在 Windows 本机 `启动审核.bat` → 审核台（端口 8321）抓取、审核、发布。
- **不使用 GitHub Actions**（免费额度已跑满），因此审核 Agent 必须跑在**本地**，而不是任何远程定时任务。
- 现状：抓取后，人工在审核台里逐条「改标题/摘要、删噪声、补跑 AI」；机器侧已有 `quality_gate`（Schema + 语义 + 数量门禁），但它只判「格式对不对」，判不了「内容该不该收、标题摘要好不好」。
- 另一个痛点：**抓取 + AI 之后，审核台里看不到 AI 标注**，只能到线上阅读页开「AI 标注模式」才看得到，无法在发布前复核 AI 质量。

## 2. 目标

1. 一个「审核 Agent」：读当日内容 → 逐条判质量 → 自动改写/删除/补跑 → 跑质量门禁 → 出报告，把人工降到「扫一眼报告 + 点发布」。
2. 审核台**可视化 AI 标注**（概括 + 考点/观点/术语 + 释义），让 AI 产出在发布前可复核。
3. 全程**本地运行**，只新增 DeepSeek 调用（key 已具备），不引入任何远程基础设施。

## 3. 现状盘点（审核 Agent 要接手的手动动作）

| 手动动作 | 现状 | Agent 接管方式 |
|---|---|---|
| 判噪声/相关性 | `config.json` 的 `noiseTitle` 关键词黑名单（纯规则，易误伤漏网） | `judge_item`：LLM 判相关性 + 噪声 + 标题摘要质量 |
| 改标题/摘要 | 审核台人工改 | `rewrite_item`：结构化改写 |
| 删除条目 | 人工点「本期不发布」 | `drop_item`：标记 `excluded` + 理由（不物理删除） |
| 补跑 AI | 人工点「补跑」 | `rerun_ai`：对 `aiStatus=error` 的文章补跑 |
| 质量校验 | `quality_gate`（已有） | `run_quality_gate`：Agent 每次改完回读剩余错误 |

## 4. Agent 设计

### 4.1 工具（tool）

| 工具 | 输入 | 输出 |
|---|---|---|
| `read_digest` | date | 当日 digest + 各篇 article（含 `aiSummary`/`aiAnnotations`/`aiStatus`） |
| `judge_item` | item | `{ score: 0-100, verdict: keep\|rewrite\|drop\|rerun, reason, newTitle?, newSummary? }` |
| `rewrite_item` | itemId + 新标题/摘要 | 应用结果 |
| `drop_item` | itemId + reason | 应用结果（标记 excluded） |
| `rerun_ai` | articleId | 重跑 AI 概括/标注后的状态 |
| `run_quality_gate` | date | 剩余 schema/semantic/volume 错误 |

### 4.2 主循环（这才是"真 Agent"，区别于一次性脚本）

```text
读日报 + 质量报告
  → 逐条 judge_item（结构化 JSON，逐条校验）
  → 对 verdict ∈ {rewrite, drop, rerun} 的条目执行对应工具
  → run_quality_gate 拿回剩余错误
  → 仍有失败 → 带上「剩余错误」再修一轮（最多 N=3 轮）
  → 产出审核报告 + 改动 diff
  → 人复核 → 发布
```

关键点：每个动作都有**验证反馈**（质量门禁回读），失败则基于反馈收敛；判不准/修不好的条目标「待人工」，**绝不静默删内容**。

### 4.3 审核报告数据结构（可审计、可量化）

`content/_reports/<date>.review.json`：

```json
{
  "date": "2026-08-15",
  "agent": "review-agent-v1",
  "model": "deepseek-chat",
  "rounds": 2,
  "qualityStatus": "ok",
  "decisions": [
    {
      "articleId": "14588442ca",
      "verdict": "rewrite",
      "reason": "标题含来源前缀且摘要超 150 字",
      "before": { "title": "…", "summary": "…" },
      "after": { "title": "…", "summary": "…" }
    }
  ],
  "needsHuman": ["<articleId>"],
  "generatedAt": "2026-08-15T21:30:00+08:00"
}
```

这份报告本身就是「Agent 落地案例」的量化证据：每期自动修好几条、人工还剩几条、几轮收敛。

## 5. 与现有审核台集成（本地优先）

- `pipeline/src/kaogong/review/server.py`：新增 `POST /api/review-agent`（后台线程 + `/api/review-agent/status` 轮询，复用现有 `发布到 CF` 的异步模式）。
- `ui/index.html`：顶部加「🤖 AI 审核」按钮 + 结果面板（每条 verdict + before/after + reason；底部门禁状态 + 待人工清单）。
- **不自动发布**：Agent 只写回 `content/{date}/` 的 digest/article 并出报告，发布仍走人工点「发布到 CF」。

## 6. AI 标注可视化（回应"抓取后看不到 AI 标注"）

审核台的「编辑面板」目前只有标题/摘要 + 原文预览，缺 AI 产出。计划加：

1. **AI 速览区**：展示 `aiSummary`（AI 概括）。
2. **标注列表**：按段落列出 `考点 / 观点 / 术语`，每条显示「类型 · 段落 N · 原文片段 · 释义」。
3. **原文内联高亮**：在「原文预览」里把标注片段用不同颜色标出（考点/观点/术语），悬停显示释义——和线上阅读页的「AI 标注模式」一致，便于发布前复核。

## 7. 分阶段落地 + 验收标准

| 阶段 | 内容 | 状态 |
|---|---|---|
| Phase 1 | 只判不改：`judge_item` 评分 + 理由 + 建议动作，展示在审核台报告 | ✅ 已实现 |
| Phase 2 | 判 + 改：`rewrite`/`drop` 应用到工作副本 + diff 报告 + 可回退 | ✅ 已实现 |
| Phase 3 | 闭环：`rerun` 补跑失败 AI + `quality_gate` 验证，应用后返回门禁状态 | ✅ 已实现（单轮闭环，人工确认在前） |

## 8. 安全与兜底

- Agent 无权直接发布；发布仍是人工动作。
- `drop_item` 只标记 `excluded`，不物理删除文章 JSON。
- 每次改写/删除都写 `reason`，进报告可审计。
- Agent 的 LLM 输出走 zod/JSON Schema 校验 + 重试（复用现有 `article_ai` 模式）。
- 判不准的项 → `needsHuman`，而不是猜测硬改。

## 9. 已确认决策（2026-08）

1. **应用方式**：Agent **直接改** `content/{date}/` 工作副本（出报告 + 可回退；Phase 2 起生效，Phase 1 只判不改）。
2. **判质量的"黄金标准"**：已定稿为 `docs/product/review-judging-rubric.md`（相关性 30 / 标题 20 / 摘要 20 / AI 标注 20 / 原文完整 10；verdict 映射 keep / rewrite / drop / rerun）。`review_agent.py` 的 system prompt 以此为准。
3. **Phase 起点**：从 **Phase 1（只判不改）** 开始。
