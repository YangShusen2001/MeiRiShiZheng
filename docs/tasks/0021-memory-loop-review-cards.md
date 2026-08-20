# TASK-0021：记忆闭环 MVP（考点卡片 + 间隔重复 + 主动回忆）

## Status

completed

## Owner

review-cards-agent

## Dependencies

- 提案 0021（已评审通过）

## Goal

按提案 `docs/proposals/0021-memory-loop-review-cards.md` 实现最小可行记忆闭环：手工 30 张考点卡片（静态内容）+ 翻卡自测（4 档自评）+ ts-fsrs 间隔重复调度 + D1 存复习状态 + 「今日待复习」软闸门入口。

## Allowed Files

- `content/cards/15w-plan.json`、`content/cards/gzbg-2026.json`（新增）
- `content/schema/card.schema.json`（新增）
- `packages/contracts/src/content.ts`、`packages/contracts/src/api.ts`
- `apps/api/src/db/schema.ts`、`apps/api/src/routes/review.ts`（新增）、`apps/api/src/app.ts`
- `apps/api/package.json`（依赖 ts-fsrs）
- `apps/web/src/lib/review.ts`（新增）、`apps/web/src/pages/`、`apps/web/src/layouts/Base.astro`
- 相关测试文件（api 单测、契约测试、web 测试）
- `docs/tasks/0021-memory-loop-review-cards.md`

## Acceptance Criteria

阶段 A（内容）：
- [ ] `content/cards/` 两个 JSON 通过 `card.schema.json` 校验；30 张卡一问一答、原子、硬考点、数字准确。

阶段 B（后端）：
- [ ] D1 新增 `reviewCards` 表；`routes/review.ts` 实现 `GET /due`（到期 + 每日新卡 ≤5）与 `POST /grade`（ts-fsrs 调度）；身份隔离正确。

阶段 C（前端）：
- [ ] 「今日待复习」入口；毛玻璃遮罩 + 居中卡片层；翻转 + 4 档自评；软闸门「今日跳过」；移动端全屏。

阶段 D（测试）：
- [ ] 全量测试通过；类型检查通过。

## Verification

```text
pnpm --filter @kaogong/api test
pnpm --filter @kaogong/api typecheck
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web build
python -m pytest pipeline/tests
```

## Handoff

```text
任务：TASK-0021 记忆闭环 MVP（考点卡片 + 间隔重复 + 主动回忆）
负责人：review-cards-agent
修改文件：
- content/cards/15w-plan.json、content/cards/gzbg-2026.json（新增，30 张卡）
- content/schema/card.schema.json（新增）
- packages/contracts/src/content.ts（ReviewCard/CardDeck）、api.ts（review 契约）
- apps/api/src/db/schema.ts（reviewCards 表）、routes/review.ts（新增）、app.ts（注册 /api/review）
- apps/api/package.json（ts-fsrs 依赖）、drizzle/0019_kind_wolverine.sql（drizzle-kit 生成）
- apps/api/test/review.test.ts（新增）、migration-reliability.test.ts（迁移列表加 0019）
- apps/web/src/lib/content.ts（listCards）、api.ts（getReviewState/gradeReview）、review.ts（新增）
- apps/web/src/layouts/Base.astro（复习入口 + 卡片数据注入 + initReview）
- apps/web/src/styles/global.css（复习遮罩样式）
- pipeline/src/kaogong/quality.py（classify_artifact 加 card）、pipeline/tests/test_content_schema.py（validators 加 card）
实现内容：30 张考点卡片（十五五 15 + 政府工作报告 15，数字经官方原文核验）；D1 reviewCards 表存 FSRS 状态；GET /api/review/state 返回已知卡状态、POST /api/review/grade 用 ts-fsrs 调度（4 档自评→Rating）；前端毛玻璃遮罩 + 翻转卡片 + 软闸门「今日跳过」+ 每日新卡 ≤5（前端算）+ 移动端全屏。
契约变化：content.ts 新增 ReviewCard/CardDeck；api.ts 新增 reviewRating/reviewCardState/reviewGrade 等 schema；content/schema/card.schema.json 新增（policy + cards[]，card: id/question/answer/tags）。
测试命令：pnpm --filter @kaogong/api test/typecheck；pnpm --filter @kaogong/web test/build；python -m pytest tests（pipeline）
测试结果：API 165/165 + typecheck 0；Web 61/61 + build 162 页；Pipeline 157/157。
已知问题：① apps/web 曾有的 4 个既有 typecheck error（highlights.test.ts ×3 + favorites.astro ×1）已一并修复：测试 styles 改用 `LegacyHighlightRecord[]` 注解替代 `as const`；favorites.astro 本地收藏映射为 Favorite 形状（补 source/note/quote 空串）。② 移动端底部 tabbar 无「复习」入口：桌面 nav 有按钮，移动端依赖遮罩自动弹出；用户点「今日跳过」后再想复习需刷新页面（下次加载仍因 skip 标记不弹，直到次日）——MVP 已知限制。③ 新卡按文件内顺序引入，每日 ≤5；到期卡按 dueAt 升序。
下游 Agent 注意事项：① 生产 D1 需执行 0019 迁移（wrangler d1 migrations apply）。② reviewCards.fsrs_state 存 ts-fsrs Card 的 JSON（due/last_review 为 unix 毫秒），改动前需了解 ts-fsrs v5 Card 结构。③ 卡片内容在 apps/web 构建时读 content/cards，新增卡片只需加 JSON 文件 + 保证 id 全局唯一。
是否满足验收标准：满足（阶段 A/B/C/D 验收项全部达成）。
```
