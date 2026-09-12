# TASK-0002：生成 AI 概括和三类标注

## Status

completed

## Owner

content-pipeline-agent

## Dependencies

- TASK-0001

## Goal

在抓取原文后生成首页概括、观点句、申论考点和政策术语，并通过质量门禁。

## Allowed Files

- `pipeline/**`
- `content/schema/**`
- `content/**` 样例
- 内容相关测试

## Acceptance Criteria

- [x] AI 输出为结构化 JSON，不生成 HTML。
- [x] 概括目标长度为 80-120 字。
- [x] 标注片段可以定位到对应原文段落。
- [x] 术语释义目标长度为 30-80 字。
- [x] AI 失败时原文仍可发布并记录错误。
- [x] 质量报告能区分抓取、定位、Schema 和 AI 失败。
- [x] 每类标注有硬上限，日报候选数或文章数低于最近有效基线 50% 时进入质量错误。

## Verification

```text
pytest pipeline/tests -q
```

## Handoff

```text
任务：TASK-0002 生成 AI 概括和三类标注
负责人：content-pipeline-agent
修改文件：pipeline/src/kaogong/article_ai.py、pipeline/src/kaogong/pipeline.py、内容 Schema/契约、Pipeline 测试
实现内容：DeepSeek 结构化输出、摘要重试、原文片段唯一定位、偏移/hash/语义校验、错误降级和日期质量报告
契约变化：成功产物增加 aiQuality.locationErrors
测试命令：pytest pipeline/tests -q
测试结果：当前仓库本地证据为 Pipeline 104/104 通过；摘要允许范围 60-150、标注上限 viewpoint=5/exam_point=8/term=5、UTF-16 定位和日报 50% 数量门禁均有测试覆盖
已知问题：未批量重生成历史 content；下一次 Pipeline 运行开始产生 AI 字段
下游 Agent 注意事项：日报发布应关注 _reports 的 aiError/locationErrors
是否满足验收标准：满足
```
