# TASK-0026：测试、文档与发布验证（0022 阶段 E）

## Status

pending

## Owner

待分配（test-security-agent）

## Dependencies

- TASK-0022 ~ TASK-0025 全部完成
- 提案 0022 §12/§13（ADR 反转记录、产品文档重写）
- 0006 既有 release blockers（REL-PRODUCTION-DEPLOYMENT、REL-NEWSLETTER-PROVIDER）

## Goal

全量验证与收尾：契约/管道/前端/复习全量测试与类型检查；ADR 记录加量决策（0008/0014）正式反转；产品文档重写；生产发布验证（部署、D1 迁移、冒烟、退信/退订演练）在改赛道后重新执行。

## Allowed Files

- `docs/adr/`（新增反转记录 ADR）
- `docs/product/`（product-overview.md、mvp-scope.md、user-flows.md）
- `docs/release-readiness.json`（关闭/更新 blocker 证据）
- `docs/release-verification-2026-09-16.md`（生产部署验证记录，2026-09-16 新增）
- `docs/deployment.md`、`docs/tasks/0026-release-verification.md`
- 测试/修复相关文件（经对应模块负责人确认）

## Acceptance Criteria

- [ ] 全量检查通过：`pnpm -r typecheck && pnpm -r test && pnpm -r build`、`pipeline pytest -q`、Schema 契约测试。
- [ ] ADR：记录"从规模聚合转向精选+记忆"，明确反转 0008/0014 加量决策及其理由。
- [ ] 产品文档重写：定位、核心价值、用户流程、MVP 范围与 0022 §2 目标形态一致；旧"每日聚合"表述清理。
- [x] 生产部署验证：Worker/D1 迁移/Pages 部署记录；同站点域名 SameSite 会话；GET 冒烟（首页/阅读/API ping/认证/订阅）—— **2026-09-16 实测通过**，证据 `docs/release-verification-2026-09-16.md`。其中「一封安全验证码邮件 + 登录确认（不记录明文）」**未执行**（依赖生产发信域），已并入下一条跟踪。
- [x] Newsletter 生产证据：未取得，blocker **保持 `open` 且 `closeEvidence` 仍为 `null`** 并记录原因；已由 `high` 降为 `medium`（不阻塞主干发布），降级理由见注册表 `severityChangeReason`。
- [x] 发布门禁（release-gate）反映最新证据；无 high/critical 未关闭项阻碍本次发布说明（`pnpm release:check` exit 0）。

## Verification

```text
pnpm -r typecheck && pnpm -r test && pnpm -r build
cd pipeline && python -m pytest -q
pnpm run release:check
pnpm run test:smoke（部署后执行）
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
