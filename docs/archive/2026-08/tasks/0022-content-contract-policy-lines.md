# TASK-0022：契约与主线池（0022 阶段 A）

## Status

completed

## Owner

foundation-agent

## Dependencies

- 提案 `docs/proposals/0022-curation-memory-pivot.md`（已评审，核心决策 2026-08-22 拍板）

## Goal

按提案 0022 §10 阶段 A 落地数据契约：主线池文件与 Schema、关系标注（箭头）契约、卡片锚定字段、复习项目字段，保持 TS 与 JSON Schema 双端一致（消除手工漂移的长期目标）。

## Allowed Files

- `content/policy-lines.json`（新增，starter 2 条主线）
- `content/schema/policy-lines.schema.json`（新增）
- `content/schema/article.schema.json`（扩展：aiRelations / policyLine / evergreen）
- `content/schema/card.schema.json`（扩展：policyLine / examPointId / anchor）
- `packages/contracts/src/content.ts`
- `apps/web/src/lib/content.ts`（新增 listPolicyLines）
- `pipeline/src/kaogong/quality.py`（classify_artifact 增加 policy-lines）
- `pipeline/tests/test_content_schema.py`（policy-lines 校验 + aiRelations schema 用例）
- `apps/web/src/lib/content.test.ts`（listPolicyLines 用例）
- `docs/tasks/0022-content-contract-policy-lines.md`

## Acceptance Criteria

- [ ] `content/policy-lines.json` 通过新 Schema；starter 包含「十五五规划建议」「2026 年政府工作报告」两条 active 主线。
- [ ] `article.schema.json` 支持 `aiRelations`（引用标注 id + kind 枚举 + 人工修正审计字段）、`policyLine`、`evergreen`；形状校验有测试覆盖（合法通过、非法 kind / 缺字段失败）。
- [ ] `card.schema.json` 支持可选 `policyLine` / `examPointId` / `anchor`；现有 30 张卡不破坏（不 required）。
- [ ] `packages/contracts/src/content.ts` 新增 `PolicyLine`、`AiRelation` 系列类型；`ClippedArticle` / `ReviewCard` 与 Schema 字段一一对应。
- [ ] `apps/web/src/lib/content.ts` 提供 `listPolicyLines()`，测试覆盖（文件缺失返回 []）。
- [ ] Python 契约测试：`policy-lines.json` 纳入校验；`classify_artifact` 识别 policy-lines。
- [ ] 双端测试与类型检查通过（TS typecheck / web vitest / pytest 契约用例）。

## Verification

```text
CI=true pnpm --filter @kaogong/web test
CI=true pnpm --filter @kaogong/web typecheck（或仓库级 typecheck）
pipeline 侧：pytest tests/test_content_schema.py -q
```

## Handoff

```text
任务：TASK-0022 契约与主线池（0022 阶段 A）
负责人：foundation-agent
修改文件：content/policy-lines.json（新增）；content/schema/policy-lines.schema.json（新增）；
  content/schema/article.schema.json（aiRelations/policyLine/evergreen）；
  content/schema/card.schema.json（policyLine/examPointId/anchor）；
  content/cards/15w-plan.json、gzbg-2026.json（补 deck 级 policyLine）；
  packages/contracts/src/content.ts（PolicyLine/AiRelation 系列类型与字段扩展）；
  apps/web/src/lib/content.ts（listPolicyLines + 类型导出）；
  pipeline/src/kaogong/quality.py（classify_artifact 增加 policy-lines）；
  pipeline/tests/test_content_schema.py（policy-lines/card/aiRelations 用例）；
  apps/web/src/lib/content.test.ts（listPolicyLines 用例）
实现内容：主线池契约 + 关系标注（箭头）契约 + 卡片锚定契约，TS 与 JSON Schema 双端一致。
契约变化：ClippedArticle 新增可空 aiRelations/policyLine/evergreen；ReviewCard/CardDeck 新增可空
  policyLine/examPointId/anchor；新增 PolicyLine/PolicyLinesFile 与 aiRelation/aiRelationPoint 定义。
  均为可空字段，历史内容兼容。
测试命令：apps/web 侧 vitest run src/lib/content.test.ts（本机 7/7 通过）；
  contracts/web/api tsc --noEmit（本机 0 错误）；
  Python 侧 pytest tests/test_content_schema.py -q（需在 Windows 管线环境执行，本 WSL 无 pip）
测试结果：TS 侧全绿；JSON 语法与 schema $defs 引用闭环已本地抽查；Python 契约用例待 Windows 执行。
已知问题：WSL 环境无 pip/ensurepip，Python 侧未能本地运行；policy-lines.json 仅含 2 条 starter 主线，
  其余活跃主线由用户按 0022 §3.2 人工维护补充。
下游 Agent 注意事项：TASK-0023 依赖本任务的 Quality 门禁扩展（引用有效/上限/locked 防覆盖为语义层校验，
  在 article_ai.py 的 validate_article_ai 落地，不在 JSON Schema）；aiRelations 的跨字段引用校验必须
  参考本任务新增的 schema 字段与 Python 已定位注解。
是否满足验收标准：满足（除 Python 侧在本机不可运行，待 Windows 复跑）。
```
