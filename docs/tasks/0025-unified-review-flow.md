# TASK-0025：复习统一（0022 阶段 D）

## Status

pending

## Owner

待分配（account-agent）

## Dependencies

- TASK-0022（契约字段）
- TASK-0024（前端复习界面）
- 提案 0022 §7（复习逻辑统一）

## Goal

按提案 0022 §7 统一复习逻辑：卡片 / 错题 / 每日一练共用一套 FSRS 调度；每日一练题目从卡片池出题并绑定卡片；错题自动进 FSRS（答错 = Again）并回链卡片。

## Allowed Files

- `apps/api/src/`（db/schema.ts、routes/review.ts、routes/practice.ts、routes/wrong.ts 等）
- `packages/contracts/src/api.ts`
- `apps/web/src/`（复习入口、每日一练、错题本相关页面）
- 相关测试文件
- `docs/tasks/0025-unified-review-flow.md`

## Acceptance Criteria

- [ ] D1 复习状态表泛化为「复习项目」（card / wrong-question，复合主键 ownerId+itemId），迁移脚本幂等。
- [ ] 错题入队：答错自动评 Again 进 FSRS；答对从队列移除（或降频，按拍板）。
- [ ] 每日一练出题自卡片池（AI 出题 + 人工审核通道），题目绑定生成卡片 id，答错回链卡片页。
- [ ] 一套调度入口：今日到期 = 卡片 + 错题 + 出题统一队列，前端「今日待复习」聚合展示。
- [ ] 既有行为回归：登录/未登录身份隔离（user:/device:）、邀请码配额、收藏不受影响。
- [ ] 测试覆盖：调度迁移、身份隔离、错题入队/出队、出题绑定。

## Verification

```text
CI=true pnpm --filter @kaogong/api test
CI=true pnpm --filter @kaogong/api typecheck
CI=true pnpm --filter @kaogong/web test
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
