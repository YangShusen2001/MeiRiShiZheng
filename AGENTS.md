# Agent Development Rules

## Project Goal

这是一个面向公务员考生的时政文章聚合和学习网站。

核心产品链路：

```text
官方时政来源
  -> Python 内容管道
  -> 原文清洗、AI 概括、AI 标注
  -> Astro 静态站
  -> Cloudflare Pages
```

用户通过 QQ 邮箱验证码登录，可以阅读原文、查看 AI 标注、收藏文章并订阅每日摘要邮件。

产品需求、验收标准和 AI 规则以 `docs/product/` 为准；本文件只规定开发和 Agent 协作方式。

## Repository Map

- `apps/web`: Astro + TypeScript 前端和阅读交互。
- `apps/api`: Hono Cloudflare Worker、D1、Drizzle 和用户数据 API。
- `packages/contracts`: TypeScript API/内容契约。
- `pipeline`: Python 抓取、清洗、去重和 AI 内容处理管道。
- `content`: Pipeline 产出的 JSON 内容和 JSON Schema。
- `docs/product`: 产品需求、AI 规则和验收标准。
- `docs/architecture`: 模块边界、数据流和技术方案。
- `docs/agents`: Agent 角色、权限和 Handoff 规则。
- `docs/tasks`: 可执行任务及依赖关系。
- `docs/adr`: 架构决策记录。

## Non-negotiable Boundaries

- `apps/web` 不直接访问 D1、邮件服务或 DeepSeek。
- `apps/api` 是用户数据和会话的唯一访问入口。
- `pipeline` 不修改用户数据库，不创建用户 Session，不发送验证码邮件。
- AI 标注是只读内容数据，不写入用户 `highlights` 表。
- AI 标注与用户标注必须分开存储、分开删除、分开渲染。
- 普通文章必须保留来源、发布时间和官方原文链接。
- AI 不得直接生成或注入 HTML；AI 返回结构化 JSON，程序负责校验和定位。
- 不得为了预期中的未来规模引入微服务或基础设施；新增基础设施需要 ADR。
- 不得提交密钥、验证码明文、邮件服务 Token 或真实用户隐私数据。

## Development Workflow

1. 阅读本文件和当前任务关联的产品、架构、Agent 文档。
2. 检查 `git status`，理解已有修改，不覆盖其他人的工作。
3. 先搜索现有实现、契约和测试，再决定修改位置。
4. 复杂任务先创建或更新 `docs/tasks/` 任务文件。
5. 先确定 Schema/API 契约，再并行实现前端、后端或 Pipeline。
6. 每个 Agent 只修改任务允许的文件范围。
7. 开发 Agent 必须为行为变化补测试。
8. 测试/安全 Agent 独立验证，不以开发 Agent 的口头结论代替测试。
9. 集成前运行相关检查，集成后运行全量检查。
10. 最终检查 `git diff`，报告完成内容、验证结果、已知风险和下游注意事项。

## Pipeline Quality Gate

Pipeline 输出“通过”不是指脚本没有抛异常，而是指内容产物满足发布条件：

1. JSON 通过对应的 `content/schema/*.json` JSON Schema。
2. 必填字段、日期、状态、原文 URL 和来源字段有效。
3. AI 概括目标为 80-120 个中文字符，允许范围为 60-150；超出时重试或标记失败。
4. AI 标注类型只能是 `viewpoint`、`exam_point`、`term`。
5. 每个标注必须能在对应原文段落中定位，且 `start/end` 有效、不可跨段。
6. 政策术语释义目标为 30-80 个中文字符，失败时该标注无释义但不能伪造。
7. AI 生成失败时文章仍可发布原文，但必须写入 `aiStatus` 和失败原因，并进入重试/报告。
8. 内容源失败、条目异常减少或 Schema 校验失败时，流水线必须给出非成功质量状态；不得静默发布。
9. 质量门禁必须有自动化测试，不能只依赖 Agent 的文字检查。

## Handoff Format

每个 Agent 完成任务时必须提供：

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

## Completion Checklist

- [ ] 产品验收标准已满足或明确记录未满足项。
- [ ] 相关 Schema、TypeScript 契约或 API 文档已同步。
- [ ] 相关单元、集成或端到端测试已补充。
- [ ] 类型检查、测试和构建已执行。
- [ ] Pipeline 输出通过质量门禁。
- [ ] 没有修改无关文件或覆盖已有工作。
- [ ] 没有新增未记录的架构决策。
- [ ] `git diff` 已检查。
- [ ] 未执行的检查和剩余风险已在 Handoff 中说明。
