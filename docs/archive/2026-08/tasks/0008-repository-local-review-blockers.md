# TASK-0008：仓库本地审查阻塞修复

## Status

verified

## Owner

test-security-agent

## Dependencies

- TASK-0002
- TASK-0004
- TASK-0007

## Goal

复核并修复仓库内可完成的质量、安全和可靠性缺口，保留需要外部供应商或生产环境的发布阻塞。

## Allowed Files

- 本轮 repository-local remediation 涉及的实现、迁移和测试文件
- 治理文档、任务记录和发布门禁

## Verified Repository-local Items

- AI Pipeline：摘要允许范围、UTF-16 标注定位、每类标注上限，以及候选数和文章数低于最近有效基线 50% 的数量门禁。
- 账号：`device:`/`user:` owner namespace，裸用户 UUID 隔离，验证码消费、匿名数据合并和 Session 创建原子化，并发重放无部分写入。
- 划线：版本化段落状态、冲突检测、空 spans tombstone、旧记录协调和损坏持久化状态的有界失败。
- 订阅：`subscriptions` 是唯一事实源；退订 token generation 可撤销和轮换；delivery lease fencing 防止陈旧 worker finalize；未知供应商结果进入 `outcome_unknown`；存储错误仅保留 `provider_error` 等脱敏分类。
- Worker scheduled boundary 已存在，但当前无 cron 和 newsletter provider。触发时安全返回 `provider_unavailable` 并保持 delivery 不变，不代表生产调度或投递成功。

## Evidence

- API：103/103。
- API typecheck：通过。
- Pipeline：104/104。
- migration reliability：8/8。
- highlight reliability：20/20。
- account merge：16/16。
- newsletter reliability：24/24。
- scheduled boundary：3/3。
- release tests：6/6；其中 release gate fixtures 5/5，部署后只读 smoke harness 1/1。
- 真实 release gate：按设计退出非零，并同时报告 `REL-NEWSLETTER-PROVIDER` 与 `REL-PRODUCTION-DEPLOYMENT`。
- Web 单元 16/16、Playwright 27/27、构建 39 页和 workspace typecheck 已在最终验收中通过；Astro check 为 0 errors/2 hints；账号页双轮视觉 PASS 为当前视觉证据。

## External Exclusions

本任务的 `verified` 只覆盖 repository-local 项目，不包含以下外部条件，也不关闭对应 blocker：

- `REL-NEWSLETTER-PROVIDER`：provider 选型与接入、provider idempotency/reconciliation、bounce、bulk 和真实投递证据。
- `REL-PRODUCTION-DEPLOYMENT`：生产配置、全部 D1 迁移、Worker/Pages 部署、同站点自定义域、部署后 GET smoke 和一次安全验证码事务邮件验证。

TASK-0005 与 TASK-0006 必须保持 `blocked`，直到各自外部条件有可审计证据。仓库测试不能证明 provider exactly-once，也不能证明生产部署成功。

## Verification

```text
pnpm --filter @kaogong/api test
pnpm --filter @kaogong/api typecheck
pytest pipeline/tests -q
pnpm test:release
pnpm release:check
```

## Handoff

```text
任务：TASK-0008 仓库本地审查阻塞修复
负责人：test-security-agent
实现内容：核对 owner namespace、账号合并、Pipeline 50% 数量门禁和标注上限、划线 tombstone、canonical subscriptions、token generations、lease fencing、outcome_unknown、脱敏错误与 dormant scheduled boundary
契约变化：无新增产品契约；发布注册表新增独立生产部署 blocker
测试结果：workspace typecheck 通过；API 103/103、Web 单元 16/16、Pipeline 104/104、migration 8/8、highlights 20/20、account merge 16/16、newsletter 24/24、scheduled 3/3、Playwright 27/27、构建 39 页；release tests 6/6；真实 gate 按设计非零并同时报告两个 high/open blocker
已知问题：外部 provider 和生产部署证据缺失
下游 Agent 注意事项：保持 TASK-0005/0006 blocked，分别关闭两个 release blocker，禁止添加推测或伪造 closeEvidence
是否满足验收标准：repository-local 项目已 verified；外部 provider 和生产部署明确排除
```
