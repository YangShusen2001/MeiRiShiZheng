# TASK-0023：管道精选制与卡片提炼（0022 阶段 B）

## Status

completed

## Owner

待分配（content-pipeline-agent）

## Dependencies

- TASK-0022（契约与主线池，completed）
- 提案 0022 §4（选材漏斗）、§5（关系标注）、§3（主线池）
- `docs/product/card-refinement-rules.md`（2026-08-22 拍板：模板 A 通用 + B/C 类型路由；每日有效新卡 ≤5）

## 进度（2026-08-22）

- [x] 模板路由与卡片提炼模块 `pipeline/src/kaogong/card_ai.py`（A/B/C prompt、解析、锚定定位校验、每篇 ≤8、每日 ≤5 额度）
- [x] article Schema 新增 `aiCards`（与 card def 机器一致性测试保护）；contracts 同步（复用 ReviewCard）
- [x] 卡片测试 + 契约一致性用例；真实 API 抽卡验证（docs/tasks/0023-card-refinement-preview.md）
- [x] **数字卡反转**（2026-08-22 拍板：数字不背、原文标记）：card_ai 禁止纯数字卡；AI 标注新增 `figure` 类型（白名单/上限 10/prompt/schema/TS/前端渲染/CSS/规则文档全链路）
- [x] 粗筛（来源权威性/标注密度/完整性/标题签名去重/时效）`curation.py`
- [x] 主线归属与评级（AI 单次调用输出 grade+policyLine，程序校验主线 id；无 key 程序兜底）
- [x] 槽位分配与 picks（头版可脱离主线；essay×2/file×1/extra×1 绑主线；下限 2 历史补剧；assignments 回写）
- [x] 关系标注 `relation_ai.py`（引用校验、中心类型、每段中心 ≤1、支撑 ≤5、**支撑点允许跨段**（实现校正）、locked 防覆盖）
- [x] `curate_content` 管道集成 + `--curate-only` CLI + curation 报告字段
- [x] quality_gate 纳入 curation 口径（picks 缺失/空 + 卡片/关系失败 → degraded，不驳回原文；2026-08-22 拍板）
- [x] 人工确认/箭头编辑走工作台（TASK-0024 已实现 editor）

## Goal

实现每日选材漏斗的管道侧：粗筛（减法）→ AI 主线归属 → 槽位等级排序（AI 只排序不打分）→ 考点卡片 AI 提炼 → 关系标注（箭头）AI 生成 → 门禁扩展（引用校验 / 上限 / 人工锁定防覆盖）。产出仍是 `content/{date}/` 内容文件，只是"发布"口径收窄为含 `picks` 的精选目录。

## Allowed Files

- `pipeline/src/kaogong/`（pipeline.py、reanalyze.py、review_agent.py、practice.py、config.py、quality.py 等）
- `pipeline/tests/`
- `content/schema/*.json`（如门禁需要新增字段）
- `content/policy-lines.json`（读取）
- `docs/tasks/0023-pipeline-curation.md`

## Acceptance Criteria

- [ ] 粗筛：来源权威性分级 / 标注密度 / judge_item 完整性 / 标题级去重 / 时效；AI 只输出等级（S/A/B/C）+ 一句话理由，程序负责排序与槽位分配。
- [ ] 主线归属：AI 判断文章归属活跃主线，输出 `policyLine`；无归属文章标记素材库（`evergreen` 候选），不入选今日。
- [ ] 槽位：头版要闻可脱离主线池；申论精读×2 / 考点提炼×1 / 多样性补充绑主线；今日目录 `picks` 2-5 篇（下限 2，不足时历史文章补剧）。
- [ ] 卡片提炼：每篇精选 3-8 张原子卡（一问一答、硬考点、表述来自原文），带 `policyLine` / `examPointId` / `anchor`（文章+句子锚定）。
- [ ] 关系标注：AI 输出 `aiRelations`（引用已存在标注 id），程序校验引用有效、不跨段、数量上限（每段 ≤1 中心 + ≤5 支撑）。
- [ ] 人工锁定：`editedAt > aiGeneratedAt` 的关系标注标记 `locked`，重跑不覆盖；显式解锁可重置。
- [ ] 门禁测试覆盖：引用无效 / 超上限 / 锁定不被覆盖 / 等级输出非法。

## Verification

```text
cd pipeline && python -m pytest -q
CI=true pnpm --filter @kaogong/web test（契约消费侧回归）
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
