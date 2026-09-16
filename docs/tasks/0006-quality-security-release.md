# TASK-0006：独立质量、安全和发布验证

## Status

blocked

## Owner

test-security-agent

## Dependencies

- TASK-0002
- TASK-0003
- TASK-0004
- TASK-0005

## Goal

独立验证产品验收标准、安全边界、Pipeline 质量门禁和生产发布条件。

## Allowed Files

- 测试和测试配置
- `.github/workflows/**`
- `docs/architecture/**` 质量与运行文档
- `docs/tasks/0006-quality-security-release.md`
- 经对应模块负责人确认的问题修复文件

## Acceptance Criteria

- [x] TypeScript 类型检查、测试和构建通过。
- [x] Python 测试和内容 Schema 校验通过。
- [x] AI 标注偏移、失败降级和双层标注重叠测试通过。
- [x] 验证码过期、重放、限流和邮箱枚举测试通过。
- [x] 邮件幂等、退订和重试测试通过。
- [ ] 部署后首页、阅读、登录和订阅冒烟测试通过。
- [x] Pipeline、API、认证、AI 和邮件有可诊断日志或指标。
- [x] 未关闭的高风险问题阻止生产发布。

## Release Control Status

- 发布阻塞单一事实源：`docs/release-readiness.json`。
- `scripts/release-gate.mjs` 对未关闭的 high/critical blocker 返回非零；关闭 high/critical blocker 时必须填写 `closeEvidence.verifiedAt`、`closeEvidence.verifiedBy` 和 `closeEvidence.evidence`。
- `REL-NEWSLETTER-PROVIDER` 保持 high/open；在供应商选择、集成和真实投递证据完成前，不得关闭，也不得执行生产 Pages 部署。
- `REL-PRODUCTION-DEPLOYMENT` 独立保持 high/open；生产配置、全部 D1 迁移、Worker/Pages、同站点域名、部署后 GET smoke 和安全验证码邮件验证均无关闭证据。
- `scripts/smoke-release.mjs` 只发送 GET 请求，覆盖首页、阅读页、API ping、认证 session 和订阅状态。它是部署后 HTTP 冒烟，不代替浏览器视觉/交互 E2E。
- 当前没有生产部署或线上冒烟通过证据，因此相关验收项保持未勾选。

## Verification

```text
pnpm -r typecheck
pnpm -r test
pnpm -r build
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web test:e2e
pytest pipeline/tests -q
pnpm test:release
pnpm release:check
```

当前 repository-local 结果：

- API 103/103、API typecheck、Pipeline 104/104 和 migration 8/8 通过。
- 定向证据为 highlights 20/20、account merge 16/16、newsletter 24/24、scheduled boundary 3/3。
- Web 单元 16/16、Playwright 27/27、构建 39 页和 workspace typecheck 已在最终验收中通过；账号页双轮视觉 PASS 仍为当前视觉证据。
- `pnpm test:release` 和 `pnpm release:check` 的本次结果记录在 TASK-0008。真实 gate 必须同时报告 `REL-NEWSLETTER-PROVIDER` 与 `REL-PRODUCTION-DEPLOYMENT`。

> **2026-09-16 更新**：上条是当时的验收要求，现已不再成立 —— `REL-PRODUCTION-DEPLOYMENT` 实测通过并 `closed`，
> `REL-NEWSLETTER-PROVIDER` 降为 `medium`。`pnpm release:check` 现 exit 0，不再输出任何 blocker。
> 现状以 `docs/release-readiness.json` 与 `docs/deployment.md` §4 为准。
- API 以脱敏结构化事件记录认证 Session/限流、newsletter issue/投递/重试/失败和 AI explain 失败；Pipeline 在 `content/_reports/` 写入源错误、Schema、AI 定位和 `qualityStatus`，相关日志与报告有自动化测试。
- 账号页六张移动/平板/桌面截图均无横向溢出，并通过两轮独立视觉评审。
- 未运行生产 Worker/Pages 冒烟，未运行已部署环境的验证码事务邮件，未发送真实 newsletter。

## Blocked

- `REL-NEWSLETTER-PROVIDER` 仍为 high/open，缺少 provider 选型、独立集成、provider 幂等或结果对账、退信与批量投递验证，以及可审计的真实投递证据。
- `REL-PRODUCTION-DEPLOYMENT` 仍为 high/open，尚无生产配置、完整 D1 迁移证据、Worker/Pages 部署记录和同站点自定义域，因此无法执行部署后 GET smoke，也未完成已部署验证码事务邮件验证。
- 已完成的本地条件：`DESIGN.md`、`deliveryAvailable` 真实状态、账号/订阅 E2E、三视口视觉评审以及 API/Pipeline 可诊断事件与质量报告均已有证据。
- 解除条件：完成 newsletter provider 的选型和独立集成，通过退信、批量投递与生产安全真实投递验证；部署 Worker/Pages 后完成首页、阅读、登录和订阅冒烟及验证码事务邮件验证；最后按注册表要求填写 blocker 关闭证据并重新运行全部门禁。

## Handoff

```text
任务：TASK-0006 独立质量、安全和发布验证
负责人：test-security-agent
修改文件：质量/发布任务记录、发布门禁与只读 smoke、CI/每日工作流、API 脱敏诊断及测试、账号 E2E 和视觉证据
验证范围：TypeScript、API/Web 单元测试、Web 构建与 Astro check、三设备 Playwright、Pipeline、release fixture、发布门禁、结构化诊断和视觉评审
测试结果：workspace typecheck 通过；API 103/103、Web 单元 16/16；构建 39 页；Web check 0 errors、2 hints；Playwright 27/27；Pipeline 104/104；migration 8/8；release 测试 6/6；账号页两轮独立视觉 PASS
发布门禁：真实注册表必须按设计退出 1，并独立报告 `REL-NEWSLETTER-PROVIDER` 与 `REL-PRODUCTION-DEPLOYMENT`
未验证：生产 Worker/Pages 冒烟、已部署验证码事务邮件、真实 newsletter
阻塞原因：newsletter provider 与真实投递证据缺失；生产部署 URL、Secrets/Variables 和同站点自定义域未提供
解除条件：完成 Blocked 节全部条件，取得可审计证据后重跑验证并更新注册表
是否满足验收标准：本地代码、账户 E2E、可观测性和发布门禁验收已满足；生产部署冒烟、事务邮件和外部 newsletter 投递未完成，任务保持 blocked
```
