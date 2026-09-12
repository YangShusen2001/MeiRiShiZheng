# TASK-0000：项目基线审计和阻塞修补

## Status

completed

## Owner

orchestrator-agent

## Dependencies

- 无

## Goal

在新功能开发前建立可复现基线，修复会阻塞后续任务的 Schema 校验和每日发布问题，并把划线缺陷拆为独立任务。

## Allowed Files

- `.github/workflows/**`
- `pipeline/tests/**`
- `docs/proposals/**`
- `docs/tasks/**`
- 基线修补直接涉及的文件

## Baseline Results

- Web 单元测试：12 项通过。
- Astro 类型检查：通过，存在一个非阻塞 inline script hint。
- Web 静态构建：通过，生成 24 个页面。
- API 测试：18 项通过。
- Pipeline 测试：64 项通过。
- 现有 Schema 测试：通过，但原实现只校验 `2026-08-12`，覆盖不足。
- 最近常规 CI：成功。
- 最近每日任务：失败，机器人推送 `main` 时遇到 non-fast-forward；Cloudflare 部署步骤未执行。
- 用户划线：纯函数测试通过，但真实交互不满足可靠性要求，见提案 0002 和 TASK-0007。

## Acceptance Criteria

- [x] 记录 Web、API、Pipeline 和构建基线。
- [x] 定位最近每日发布失败的直接原因。
- [x] Schema 测试覆盖全部发布内容目录。
- [x] 每日任务增加并发控制和非强制 rebase 推送。
- [x] 划线缺陷形成提案和独立任务。
- [x] 修补后相关测试和工作流配置检查通过。

## Verification

```text
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web build
pnpm --filter @kaogong/api test
pytest pipeline/tests -q
```

## Handoff

```text
任务：项目基线审计和阻塞修补
负责人：orchestrator-agent
修改文件：.github/workflows/daily.yml、pipeline/tests/test_content_schema.py、docs/deployment.md、docs/proposals/0002-highlight-reliability-baseline.md、docs/tasks/0000-baseline-audit.md、docs/tasks/0007-highlight-reliability.md
实现内容：记录测试和构建基线；把 Schema 校验扩展到全部发布内容；定位并修复每日任务 non-fast-forward 风险；形成划线可靠性提案和任务
契约变化：无产品数据契约变化；扩大现有 JSON Schema 测试覆盖范围
测试命令：Web test/check/build、API test、pytest pipeline/tests -q、gh run/view、gh secret list、wrangler pages deployment list、git diff --check
测试结果：Web 12 项、API 18 项、Pipeline 64 项通过；Astro 构建 24 页成功；Cloudflare Pages 凭据和历史部署可访问
已知问题：划线可靠性由 TASK-0007 修复；AI 内容契约仍由 TASK-0001 实现；工作流修复需提交推送后才能在线验证
下游 Agent 注意事项：先完成 TASK-0007 的数据安全阶段，再把 AI 标注叠加到阅读页；不要执行无回填策略的破坏性划线迁移
是否满足验收标准：满足基线审计和阻塞修补标准
```
