# 提案 0003：内容质量门禁与数据一致性基线修复

- **状态**：待评审
- **日期**：2026-08-16
- **任务分解**：TASK-0009（发布正确性/门禁）· TASK-0010（内容清洗/源适配）· TASK-0011（阅读页交互）· TASK-0012（前端展示/构建）· TASK-0013（鉴权/API）· TASK-0014（安全/运维）
- **范围**：内容管道（`pipeline/`）、内容契约（`content/schema`）、前端内容加载（`apps/web/src/lib/content.ts`）、阅读页交互（`apps/web/src/pages/read/[id].astro`、`search.astro`、`index.astro`）、API 客户端（`apps/web/src/lib/api.ts`）、本地审核服务（`pipeline/src/kaogong/review/`）、API 限流（`apps/api/src/routes/explain.ts`）

## 背景

TASK-0008 已把仓库内可复核的账号、划线、订阅、AI 定位等可靠性项目标记为 `verified`。但本轮独立审查发现：**质量门禁只校验了“字段合法性”，没有校验“产物是否真的应该发布”**——一个 0 候选、0 文章的失败日，其空 `digest.json` 仍被写出、仍被前端当作“最新一期”渲染，导致首页与日报页在源失败当天变成空白；同时质量报告里的 `articles` / `locationErrors` 等统计会与磁盘上的真实产物漂移，发布门禁基于陈旧数字做出判断。此外还存在内容实体规范化不对称、本地审核服务无鉴权、API 内存限流永不清理等可靠性缺口。

这些问题不会让单测变红，但会让“质量门禁通过”不等于“用户看到的内容是对的”。

## 已确认问题

### P1：空日报产物仍被写出并成为前端“最新一期”

`pipeline/src/kaogong/pipeline.py` 的 `build_content` 在 `candidates` 为空时仍无条件写出 `digest.json`（`sections: []`），随后才由 `quality_gate` 判定 `failed` 并以退出码 1 结束（`__main__.py`）。前端 `apps/web/src/lib/content.ts` 的 `listDigests()` 只按“目录下存在 `digest.json`”判定为一期日报，`apps/web/src/pages/index.astro` 取 `digests[0]` 作为“今日时政”。当前仓库 `content/2026-08-16/` 就是该状态：`digest.json` 为空 sections，`content/_reports/2026-08-16.json` 的 `qualityStatus` 为 `failed`（`candidates: 0, articles: 0`）。

当前生产链路靠 `python -m kaogong` 的非零退出码（`.github/workflows/daily.yml` 的“抓取”步骤失败即中止）和本地审核服务 `api_publish` 的 `_latest_failed_report` 检查来拦截，但这是一种**先写坏产物、再靠外层退出码兜底**的脆弱设计：

- 失败的空 `digest.json` 已写入工作树，本地 `astro build` / `pnpm build` 会把它当“最新一期”，首页“今日时政”渲染为空、`/daily/2026-08-16/` 为空页。
- 前端没有任何质量意识（不读 `_reports`），只要空 digest 以任何路径进入 `content/`（手工提交、日后 CI 改成 `continue-on-error`、`degraded` 阈值变化），首页即空。
- 违反“不得静默发布”的意图：失败产物不应进入发布目录。

### P1：质量报告统计与磁盘产物漂移，发布门禁基于陈旧数字

`pipeline/src/kaogong/pipeline.py` 的 `quality_gate` 用 `report = {defaults} | existing` 合并旧报告，**只重算** `schemaErrors` / `semanticErrors` / `volumeErrors`，**保留**旧报告里的 `articles` / `aiOk` / `aiError` / `locationErrors`。而 `clip_content` 会先把这几项重置为 0、再只累加本次运行的 `finished`，不统计目录里已存在的文章；唯一按目录真实重算的 `refresh_report_stats`（`reanalyze.py`）只在 `--reanalyze` 路径被调用。

实测当前仓库 `content/2026-08-15/`：磁盘有 15 个 `article-*.json`、`aiQuality.locationErrors` 求和为 12，但 `content/_reports/2026-08-15.json` 写的是 `articles: 5`、`locationErrors: 2`。`degraded`/`failed` 状态据此计算，意味着发布门禁可能基于过期统计放行或拦截。`content/2026-08-14/` 同样漂移：报告写 `aiError: 8` 并列出 8 个 `aiFailures`，但磁盘上只有 `article-458224d808.json` 一个文件带 `aiStatus: error`，其余 7 个文件根本没有 AI 字段，且该报告缺 `qualityStatus`。

### P1：`pubDate` 始终为空，违反“保留发布时间”边界

`pipeline/src/kaogong/clip.py` 的 `url_date()`（57–64 行）用两个正则从 URL 提取发布日期，但它们都不匹配真实源 URL 形态：`/20260813/`（YYYYMMDD 连续 8 位）、`/202608/`（YYYYMM）、`/2026/8/15/`（未补零的 Y/M/D）都不命中 `/YYYY/MMDD` 或 `/YYYY/MM/DD`。结果当前全部文章的 `pubDate` 都是 `""`（已核对 `content/2026-08-13/14/15` 的 article 文件），`article.schema.json` 里允许空串的“legacy 例外”变成了常态，AGENTS.md 非协商边界「普通文章必须保留来源、发布时间和官方原文链接」被破坏。发布页/审核 UI 因此永远拿不到原文发布日期。

**修复**：`url_date` 覆盖 `/YYYYMMDD/`、`/YYYYMM/`（回退到月份）与未补零 `/YYYY/M/D/` 三种形态，或在 `clip_article` 里从正文/元数据提取 `page_pub_date`；补一个“非 legacy 文章 pubDate 非空”的契约测试。

### P1：HTML 实体双编码未解干净，正文/标题残留字面实体且标注偏移基于脏文本

多个官方源对实体做了**双编码**（源码里是 `&amp;ldquo;`，浏览器显示 `&ldquo;`）。管道 `clip.py` 的 `_clean` / `article_ai.py` 的 `normalize_text` 都只做**一次** `html.unescape`，因此 `&amp;ldquo;` → `&ldquo;`（字面残留），而不是 `“`。实测 `content/2026-08-13/article-f534db6113.json` 标题、`article-1003b010b6.json` 与 `article-a9d0a92ec2.json` 段落开头的 `&emsp;&emsp;`、以及大量 `&nbsp;`/`&mdash;`/`&hellip;`/`&middot;` 都还在；且默认 clip→analyze 路径**从不调用 `normalize_article`**（只有 `--reanalyze` 会），AI 标注的 `start/end` 是相对“带实体”的脏文本计算的。

后果：前端构建时 `apps/web/src/lib/content.ts` 的 `unescapeArticle` 会把实体解码（文本变短），但**不重定位 `aiAnnotations` 偏移**，阅读页 `validAiAnnotations` 会把这些标注静默丢弃或错位；`title`/`keySentences` 同样未在管道侧归一化。Schema 只校验 `minLength`，质量门禁完全看不到这个问题。

**修复**：`_clean` / `normalize_text` 循环 unescape 直到稳定（`while html.unescape(s) != s`）；在 `analyze_article` 计算偏移前先归一化正文；前端 `unescapeArticle` 仅作向后兼容兜底；补“段落含双编码实体 + 有标注”的偏移校验测试。

### P1：日报有 N 条但剪藏全部失败时，质量门禁仍判 `ok`（静默不完整发布）

`pipeline/src/kaogong/pipeline.py` 的 `_clip_and_analyze`（113–125 行）直接丢弃剪藏失败的 clip，`clip_content` 只统计 `aiStatus`，报告里没有“剪藏失败”指标；`quality_gate`（251–256 行）只在 `sourcesOk==0`、`candidates==0`、schema/semantic/volume 出错时判 `failed`，而 `volume_errors` 依赖历史基线、首日无基线。因此“digest 有 N 条、但 `articles==0`（文章页全部抓取失败）”的第一天会被判为 `ok`，CLI 退出码 0、CI 照常发布——用户看到日报目录有链接却点不开任何原文。已用最小复现验证 `{sourcesOk:15, candidates:1, articles:0, aiError:0}` + 无历史报告 → `qualityStatus == "ok"`。

**修复**：当 `digest` 条目数 > 0 而 `articles == 0`（或 `articles < 条目数`）时判 `failed`/`degraded`；报告新增每篇剪藏失败的计数并把其纳入门禁。

### P1：`topic` 缺失/为空使整期 `practice.json` 过不了 Schema，阻断发布

`pipeline/src/kaogong/practice.py` 的 `parse_questions`（82 行）对 `q/options/answer/analysis` 都做了校验，唯独不校验 `topic`，而 `content/schema/practice.schema.json` 要求 `topic` 为 `minLength:1` 的字符串。AI 只要漏一个题的 `topic`，`parse_questions` 仍通过、写入 `practice.json`，质量门禁随即把**整个这一天判为 failed**（`schema:minLength`），CI 中止、审核服务拒绝发布——一个“看起来可选”的字段让其余正常内容全部无法上线。测试从未覆盖空 topic 场景。

**修复**：`parse_questions` 对空 `topic` 的题跳过（同 `analysis` 的处理），或给默认值 `"时政"`；补一个空 topic 的回归用例。

### P1：pubdate 源把站点导航标签（“头条”“南方快评”）当成文章标题

`pipeline/src/kaogong/sources.py` 的 `_extract_pubdate`（172 行）用 `title = min(ts, key=len)` 取最短锚文本当标题，导航标签比真实标题更短且未应用 `title_min` 过滤。实测 `content/2026-08-13/digest.json` 与 `2026-08-14/digest.json` 的「南方时评」栏目有标题为 `"头条"` / `"南方快评"` 的条目被发布——这些是页面导航文字，不是文章标题。

**修复**：丢弃过短锚文本（复用 `title_min`），或按 URL 去重后取最长锚文本为标题。

### P1：CLI 默认日期用机器本地 `today()`，UTC 上的定时 CI 总是落后北京一天

`pipeline/src/kaogong/__main__.py`（22 行）`dt.date.today()` 在 GitHub Actions UTC runner 上取的是 UTC 日期，而 `.github/workflows/daily.yml` 的 cron `0 22 * * *` 对应北京时间 06:00，且提交信息用 `TZ=Asia/Shanghai date`（daily.yml:57）。结果每天生成的是“昨天”的内容目录，却用“今天”的日期做提交信息，与 `review/server.py` 的 `beijing_today()` 约定不一致。

**修复**：`main()` 默认日期用 `ZoneInfo("Asia/Shanghai")`（复用 `review/server.py` 的写法），或在 workflow 里显式传入北京时间日期。

### P1：给重叠划线添加注释会静默丢失注释（用户数据丢失）

`apps/web/src/pages/read/[id].astro` 的 `reconcileParagraph`（约 212–229 行）用 `noteOverrides` 的 key `${start}:${end}` 精确匹配保存后的 span，但“注释”动作（约 412–420 行）传入的 key 是**用户选区范围**，而 `applyStyle` 会把选区在既有划线边界处切分，产出的 span 与选区 key 不再相等。例如对已有 `{2,5}` 的段落选 `{4,8}` 加注释，`applyStyle` 产出 `{2,4}/{4,5}/{5,8}` 三段，没有一个匹配 `"4:8"`，新注释落到 `inheritedNote` 分支——新注释永不保存，旧注释还被扩散到切分出的子段上。服务端 `PUT /api/highlights/paragraph` 整段替换，注释随之永久丢失，且保存返回成功、无错误提示。

**修复**：注释覆盖按「与 span 相交/覆盖」而非精确 key 匹配；`inheritedNote` 只在 span 是原注释区间的严格子段时继承。

### P1：元素锚定的选区（三击整段、从首行缩进空白处拖选）无法触发划线工具栏

`apps/web/src/pages/read/[id].astro` 的 `pointOffset`（252–261 行）用 `NodeFilter.SHOW_TEXT` 遍历，只匹配文本节点；当 `Selection` 的 `startContainer`/`endContainer` 是**元素节点**（如三击选择整段时 `startContainer = <p>`、`offset=0`，或拖选从 2em 缩进空白处开始）时返回 `null`，`selectionToOffsets`（273–294 行）随即丢弃整个合法选区。三击整段后点“荧光笔”等任何工具都不出现工具栏。

**修复**：`pointOffset` 对元素节点按“累积其后代文本长度”解释 offset（`offset=0` → 累计长度，`offset≥子节点数` → 累计长度+全部后代文本长度），或改用 `SHOW_ALL` 归一化。

### P2：阅读页工具栏“收藏”语义与页面收藏不一致，且失败也标记为已保存

`apps/web/src/pages/read/[id].astro` 工具栏“收藏”（410 行）用 `url: location.href`（内部 `/read/<id>/` 地址）、`title: 选中文本`，而页面右上角“☆ 收藏本文”（135–141 行）用官方原文 URL 与文章标题；服务端 `favorites.ts` 无去重，收藏页会出现同一篇文章的两条重复收藏，且工具栏那条存的是部署域名变化后即失效的内部 URL。同时 `reconcileParagraph` 里 `saved` 初始为 `true` 且 favorite 分支从不改回，POST 失败仍把工具栏标成 `saved` 并清空选区。

**修复**：工具栏收藏复用官方 URL/标题；`saved = env.ok`；服务端按 owner+url 去重。

### P2：`HIGHLIGHT_CONFLICT` 重载与并发保存存在竞态

`apps/web/src/pages/read/[id].astro` 冲突分支（237–243 行）`await loadHighlights()` 会**整体**重写 `records` 与 `paragraphVersions`，而保存互斥是“每段一个 `reconcileBusy`”。当段 A 冲突触发重载、段 B 的 PUT 尚未提交时，重载快照可能不含 B 刚保存的划线，随后 B 的响应已先写入 `records` 又被 A 的重载覆盖，B 的高亮从 UI 上消失（服务端仍在），下一次编辑 B 又触发一次 409。

**修复**：重载按段落合并（只替换冲突段），或对并发 reconcile 做排队/中止。

### P2：搜索命中数显示全量但只渲染前 100 条

`apps/web/src/pages/search.astro`（42–44 行）`count.textContent = 共 ${hits.length} 条`，但 `results.innerHTML = hits.slice(0, 100)`，无分页/提示，命中 >100 时数量与列表不一致。

### P2：注释超长无客户端校验、重复 span 未合并

注释 `prompt` 输入无长度上限，超过契约 `highlightSpanSchema.note` 的 2000 上限时 PUT 报 `INVALID_INPUT`，用户输入整体丢失；`spansFor` 对重叠区间可能发出 start/end 相同的重复 span。

### P2：生产构建缺少 `PUBLIC_API_BASE` 的 fail-fast

`apps/web/src/lib/api.ts`（29–34 行）在 `import.meta.env.PROD && !PUBLIC_API_BASE` 时仅 `console.error`，`astro build` 仍成功并把 `http://127.0.0.1:8787` 烤进产物——`docs/deployment.md` 承诺的“未设置即中止构建”并不存在，未配该变量时线上全部用户功能静默指向访客本机。

### P2：API 内存限流永不清理且跨 isolate 不可靠

`apps/api/src/routes/explain.ts` 的 `checkRateLimit` 用模块级 `Map` 按 `explain:<deviceId>` 计数，旧 key 从不淘汰——长期运行的 Worker isolate 内内存无界增长；且 Worker 多 isolate/多 colo 下该 Map 各算各的，限流形同虚设。更关键的是 `X-Device-Id` 由客户端自报、可任意轮换，配合每 isolate 独立 bucket，攻击者无需改 IP 即可绕过 10 次/分钟，直接打满付费 DeepSeek 调用（成本风险）。

### P2：验证码 `verify` 端点无 IP/设备限流，可被用来锁死账号

`apps/api/src/routes/auth.ts` 的 `/email/verify` 只依赖“每张验证码记录最多 5 次失败”的锁定，没有像 `/email/code` 那样的 IP/设备频控。知道受害者 QQ 邮箱的攻击者可持续请求新验证码（每 60 秒一次）并各自耗满 5 次失败尝试，使受害者始终无法用自己收到的验证码登录，同时邮箱被验证码持续轰炸。

### P2：`consumed_at` 预标记存在崩溃窗口，已发出的验证码可能永久不可用

`apps/api/src/routes/auth.ts` 的 `/email/code` 先以 `consumed_at = now` 插入记录，发信成功后再 `SET consumed_at = NULL`。若 Worker 在“发信成功后、清标记前”被回收/异常，该验证码将保持 consumed 状态，用户收到的验证码永远无法验证，只能重新请求。

### P2：每日一练接受 `correct > total`

`apps/api/src/routes/practice.ts` 的 `practiceSubmitSchema` 只校验 `correct >= 0`、`total >= 1`，不校验 `correct <= total`，可写入“答对数 > 总题数”的非法记录。

### P2：legacy `highlights` 行不可删除，`styles: []` 的旧划线静默不可见

旧版划线接口已 410 退役（`routes/highlights.ts` 的 `DELETE /:id`），且 `GET /paragraphs/:articleId` 的 legacy 回退会过滤掉 `styles.length === 0` 的记录——历史 `highlights` 表里那些无样式（或样式字段损坏）的行既无法由用户删除，也不在页面上显示，形成用户数据既看不到又清不掉的状态。

### P2：重复 `sourceUrl` 导致计数翻倍且后写覆盖前写

`pipeline/src/kaogong/pipeline.py` 的 `clip_content`（136–139 行）以 `md5(url)[:10]` 为 id 写文件，同一 URL 出现两次时第二次覆盖第一次，但 `articles` 与 `n` 都各加 1——计数虚高、内容被覆盖（手工改 digest 或跨源同 URL 时出现）。

### P2：slot 冲突把评论栏目混进“要闻动态”

`pipeline/src/kaogong/sources.py`（115–121 行）把「天府评论」「交汇点时评」分别挂到 `sc`/`js` slot，而 `build.py` 的 `REGION_SECTIONS` 把 `sc`→「四川要闻动态」、`js`→「江苏要闻动态」，导致评论类文章被错误标注为地区要闻、与新闻混排（对比「南方时评」「今日谈」是独立栏目）。

### P2：摘要/术语长度用 `len()` 按码点计，不校验“中文字符”

`pipeline/src/kaogong/article_ai.py`（244–251、266 行）与 schema 用 `len()` 统计码点而非 CJK 字符：一段 120 个 ASCII/标点的 summary（0 个中文字）也能通过 80–120 目标区间与 60–150 兜底；`term.explanation`（30–80）同理。

### P2：归一化重定位后 annotation `id` 仍内嵌旧偏移

`pipeline/src/kaogong/article_ai.py` 的 `normalize_article`（83 行）重定位标注时保留原 `id`（形如 `ai-{index}-{start}-{end}-{type}`），偏移变了 id 没变（如 `c4d5a2a5ae` 全部 id 偏移 +12、`6bfd683e03` 的 `ai-4-25-31-term` 实际是 19/25）。前端只用 `start/end` 渲染、暂无运行时影响，但 id 语义失真，属数据卫生问题。

### P2：本地审核服务无鉴权、可 CSRF 触发生产部署，且路径参数未校验

`pipeline/src/kaogong/review/server.py`（FastAPI）提供 `/api/publish`（构建并部署到生产 Cloudflare Pages）、`/api/fetch`、`/api/digest`（写文件）等状态变更端点，但无任何鉴权。若浏览器访问了恶意页面，可向 `http://127.0.0.1:<port>/api/publish` 发起跨站 POST，触发生产构建+部署。此外：

- `/api/digest/{date}`、`/api/article/{id}` 把路径参数直接拼进 `CONTENT / date / "digest.json"`，`date`/`id` 未校验（`../` 可穿越，虽需命中特定文件名才泄露，但属未校验输入）。
- `/api/digest` POST 把 `body.digest` 原样写入 `digest.json`，无 Schema 校验，可写出前端无法解析的坏日报。

### P3：跨源近似去重可能误杀不同文章

`pipeline/src/kaogong/dedupe.py` 的 `is_same_event` 用“`a` 的连续双字词是否都出现在 `b` 的 bigram 集合里”判定共享 ≥8 字，但该条件不保证存在真实连续公共子串，理论上有假阳性（`a="abcde"` 与 `b="XabXbcXcdXde"` 会被判为同事件）。对真实中文标题概率低，但属“宁多勿漏”的过保守实现，会静默丢弃本应收录的独立条目。

### P3：退订链接为 GET 且可被邮件预取触发

`apps/api/src/routes/subscription.ts` 的 `GET /api/subscription/unsubscribe?token=...` 是状态变更端点。邮件客户端 / 链接安全扫描器可能预取该 URL，导致用户未点击即被退订。应改为 POST（或至少增加二次确认页）。

### P3：AI 解释空 `choices` 时返回空串，且 Worker 侧无超时

`apps/api/src/lib/deepseek.ts` 的 `explainText` 在 `data.choices[0]` 缺失时返回空字符串，`/api/explain` 仍以 `ok: true` 返回，阅读页浮层显示空白；且该 `fetch` 未设 `AbortSignal.timeout`（对比管道侧 `deepseek.py` 有 `timeout=120`），上游 DeepSeek 卡住时请求会长时间悬挂。

### P3：会话/验证码/邮件投递等表无清理策略

`sessions`、`email_verification_codes`、`resend_webhook_events`、`mail_deliveries` 等表只有写入、没有定期清理任务，长期运行后无界增长；`newsletter_delivery` 里 `reconcileAttempts >= 5` 且仍带 `providerMessageId` 的 `processing` 行可能永久滞留（不再被候选查询拾取）。属运维卫生项，建议纳入后续清理计划。

## 决策

1. **空日报不进发布目录**：`build_content` 在 `candidates` 为空时不再写 `digest.json`（或写入 `_reports` 专属目录），避免“失败产物被当作最新一期”。前端 `listDigests` 不读取 `_reports`，只认非空、有内容的日报。
2. **质量报告以磁盘为准**：`quality_gate` 改为从 `content/{date}/` 目录重算 `articles` / `aiOk` / `aiError` / `locationErrors`，不再信任旧报告这几项；`clip_content` 的“重置为 0”语义改为“按目录累计”。补一个断言报告与目录一致的单测。
3. **实体规范化单点化**：把实体解码收敛到管道侧（`normalize_article` 同时规范化 `title` / `keySentences` 并在改动时重定位标注），前端 `unescapeArticle` 仅作向后兼容兜底；为“段落含实体 + 有标注”的场景补一个偏移校验测试。
4. **API 限流**：为 `explain` 限流增加基于时间的 bucket 淘汰（惰性清理），并在 Worker 侧接入 Cloudflare Rate Limiting binding 或持久化计数；至少在代码注释中明确当前实现为“尽力而为”。
5. **本地审核服务加固**：加一个本地口令（环境变量 + 头校验）与 CSRF 防护（自定义头或 token），校验 `date`/`id` 参数格式，`/api/digest` 保存前过 digest Schema。
6. **去重与退订**：`is_same_event` 改为真正的最长公共子串判定；退订改为 POST + 确认页。
7. **阅读页注释与选区**：注释覆盖改为按相交区间匹配；`pointOffset` 支持元素锚定选区；工具栏收藏统一用官方 URL 并正确回写 `saved`；冲突重载改为按段落合并。
8. **搜索与校验**：搜索命中数/渲染上限对齐（或补分页提示）；注释长度按契约限长；`spansFor` 合并重叠 span。
9. **构建契约**：`PUBLIC_API_BASE` 未设置时生产构建 fail-fast，兑现 `docs/deployment.md` 的承诺。
10. **内容门禁补漏**：剪藏失败数纳入门禁（`articles==0` 且 digest 有条目即 `failed`）；`parse_questions` 跳过空 `topic`；`_extract_pubdate` 过滤导航标签；`main()` 默认日期用北京时区。
11. **鉴权健壮性**：`/email/verify` 增加 IP/设备频控；`consumed_at` 状态机避免“已发信却永久 consumed”的崩溃窗口；`practice` 校验 `correct <= total`；为 legacy `highlights` 提供删除/可见性策略。
12. **内容正确性**：`clip_content` 按 id 去重；评论栏目独立 slot；摘要/术语长度按 CJK 字符统计；`normalize_article` 重定位时同步重写 annotation `id`。

## 实施阶段

### 阶段 A：发布正确性（P0/P1）

- 空 `digest.json` 不写发布目录；前端跳过空 sections 日报。
- `quality_gate` / `clip_content` 统计以磁盘为准 + 一致性单测。
- 实体规范化收敛到管道侧 + 标题/keySentences 一并处理。
- 修复重叠注释丢失；`pointOffset` 支持元素锚定选区。
- 剪藏失败纳入门禁；空 `topic` 跳过；导航标签过滤；CLI 北京时区。

### 阶段 B：安全与可靠性（P2）

- `explain` 限流 bucket 淘汰 + 抗 `X-Device-Id` 轮换。
- 审核服务口令 + CSRF + 路径校验 + 保存前 Schema 校验。
- 工具栏收藏统一 URL/状态；冲突重载按段落合并。
- 搜索上限对齐；注释限长；生产构建 `PUBLIC_API_BASE` fail-fast。
- `/email/verify` 频控；`consumed_at` 崩溃窗口；`practice` 校验；legacy highlights 策略。

### 阶段 C：健壮性与回归（P3）

- `dedupe` 最长公共子串。
- 退订 POST + 确认页。
- `explainText` 空结果显式报错。
- `clip_content` 去重；评论栏目独立 slot；CJK 计数；annotation id 同步。

## 验收标准

- [ ] 源失败日（0 候选）不再产生会被前端列为“最新一期”的空日报；首页在失败日仍有历史材料可看。
- [ ] 质量报告的 `articles` / `aiOk` / `aiError` / `locationErrors` 与 `content/{date}/` 实际文件一致（有自动化测试）。
- [ ] 含实体的 legacy 内容在补跑 AI 后，标注偏移与前端渲染文本一致，不丢失不错位。
- [ ] 重叠划线上新增注释保存后刷新不丢失（新增回归用例）。
- [ ] 三击整段选择后划线工具栏可用（新增 e2e 用例）。
- [ ] 收藏只产生一条官方 URL 记录；失败时工具栏不显示“已保存”。
- [ ] 本地审核服务的状态变更端点不可被跨站脚本触发，路径参数不越出 `content/`。
- [ ] 搜索命中数与渲染条数一致（或有明确截断提示）。
- [ ] 去重不再误杀独立文章（新增回归用例）。
- [ ] 退订不因邮件客户端预取而意外生效。
- [ ] digest 有条目但剪藏全部失败时门禁判非成功（新增回归用例）。
- [ ] 单个 `topic` 为空不会让整期 `practice.json` 阻断发布（新增回归用例）。
- [ ] `pubDate` 对非 legacy 文章非空；日报标题不再出现导航标签。
- [ ] `/email/verify` 无法被无 IP/设备频控地反复爆破；验证码不存在“已发信却永久不可用”窗口。
- [ ] 每日一练拒绝 `correct > total`。
