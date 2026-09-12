# TASK-0007：用户划线可靠性修复

## Status

completed

## Owner

web-reader-agent

## Dependencies

- TASK-0000

## Goal

修复用户划线的数据丢失、加载竞态、注释丢失、移动端不可用和浏览器测试缺口。

## Allowed Files

- `apps/web/**` 划线和阅读页相关文件
- `apps/api/**` 划线相关路由、Schema 和迁移
- `packages/contracts/src/api.ts`
- 相关测试和测试配置
- `docs/proposals/0002-highlight-reliability-baseline.md`

## Acceptance Criteria

- [x] 使用原子服务端操作保存段落划线，不再前端先删后插。
- [x] 同段并发编辑有版本冲突检测，不静默覆盖。
- [x] 初始划线加载完成前禁止编辑。
- [x] 保存失败可见且不丢失旧数据。
- [x] 用户可单独移除某一种样式。
- [x] 注释可查看、编辑、删除且不会因样式切分静默丢失。
- [x] 旧迁移有明确重建或回填策略和升级测试。
- [x] 内容变化时校验旧偏移，不错误标注其他文字。
- [x] 移动端选区和浮层定位可用。
- [x] Playwright 覆盖创建、叠加、删除、刷新和移动端。
- [x] 删除写入版本化空 spans tombstone，旧记录和陈旧写入不能使划线复活。

## Verification

```text
pnpm --filter @kaogong/api test
pnpm --filter @kaogong/web test
pnpm --filter @kaogong/web check
pnpm --filter @kaogong/web build
```

## Handoff

```text
任务：TASK-0007 用户划线可靠性修复
负责人：web-reader-agent
修改文件：划线 API/Schema/迁移、阅读页、API 客户端、样式、Playwright/Vitest 测试、CI 和 ADR 0005
实现内容：版本化段落 JSON 状态；单 SQL 原子替换；409 冲突检测；空 spans tombstone；加载门禁；失败重载；偏移文本校验；按样式删除；注释查看编辑删除；移动端底部操作条；桌面/Android/iOS 浏览器回归
契约变化：新增 HighlightSpan、HighlightParagraphReplace、HighlightParagraphResponse 和 HighlightParagraphListItem
测试命令：pnpm -r typecheck；pnpm -r test；pnpm --filter @kaogong/web check；pnpm --filter @kaogong/web test:e2e；pnpm -r build；pytest pipeline/tests -q
测试结果：当前仓库本地证据为 highlights 20/20、迁移 8/8、API 103/103 和 API typecheck 通过；Web 单元 16/16、Astro check 0 errors/2 hints、Playwright 27/27、构建 39 页及双轮视觉 PASS
已知问题：旧无偏移划线无法可靠恢复；因无生产用户采用 ADR 0005 的重建/忽略无效记录策略。注释随重叠 span 继承，未来若需要一个注释跨多个独立样式实体，可再拆独立 annotations 表
下游 Agent 注意事项：TASK-0003 必须把 AI 标注作为独立只读层，不写入 highlight_paragraphs；生产部署 API 前先应用 0007 迁移
是否满足验收标准：满足
```
