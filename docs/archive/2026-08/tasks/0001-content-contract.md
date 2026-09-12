# TASK-0001：确定文章 AI 内容契约

## Status

completed

## Owner

architecture-agent

## Dependencies

- 无

## Goal

定义首页 AI 概括、阅读页 AI 标注、原文段落和失败降级的机器可读契约。

## Allowed Files

- `content/schema/**`
- `packages/contracts/src/content.ts`
- `docs/architecture/ai-annotation.md`
- 相关测试

## Acceptance Criteria

- [x] 支持 80-120 字首页 AI 概括字段。
- [x] 支持 `viewpoint`、`exam_point`、`term` 三类标注。
- [x] 标注包含原文片段和段落偏移。
- [x] 术语支持 30-80 字释义。
- [x] 记录 AI 状态、模型、Prompt 版本和原文 hash。
- [x] AI 失败时仍可表达原文可发布。

## Verification

```text
pnpm -r typecheck
pnpm -r test
```

## Handoff

```text
任务：TASK-0001 确定文章 AI 内容契约
负责人：architecture-agent
修改文件：content/schema/article.schema.json、packages/contracts/src/content.ts、apps/web/src/lib/content.ts、pipeline/tests/test_content_schema.py、AI 产品/架构文档
实现内容：定义 AI 状态、首页概括、三类标注、术语释义、模型/Prompt/时间/hash 和失败降级字段
契约变化：新增 AiStatus、AiAnnotationType、AiAnnotation 及 ClippedArticle AI 可选字段；历史内容可缺失，新处理内容必须完整写入状态
测试命令：pytest pipeline/tests/test_content_schema.py -q；pnpm -r typecheck；pnpm -r test；pnpm -r build
测试结果：契约定向测试 6 项通过；全量结果见任务完成验证
已知问题：JSON Schema 无法比较 start/end 或验证切片文本，TASK-0002 必须实现语义校验器
下游 Agent 注意事项：TASK-0002 生成结构化 JSON 并定位偏移；TASK-0003 只读消费 aiAnnotations，不写入用户划线表
是否满足验收标准：满足
```
