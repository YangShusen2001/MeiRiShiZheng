# 调研 0008：用 Crawl4AI 扩大内容爬取规模的可行性

- **状态**：调研结论（待拍板）
- **日期**：2026-08-16
- **范围**：`pipeline/src/kaogong/{sources,http,clip}.py`、`pipeline/pyproject.toml`、`.github/workflows/daily.yml`

## 一、现状：为什么「网页太少」

当前管道抓取链路（`sources.py` + `http.py` + `clip.py`）：

```text
httpx 抓列表页 HTML → 正则抽 <a href> → (pubdate 源再抓文章页取日期) → clip.py 抓文章页正则抽正文
```

核心约束：

1. **纯正则 + 无 JS 渲染**：`httpx` 只拿服务器返回的原始 HTML，不执行 JS。若列表页是前端 JS 动态加载（不少新闻频道是），初始 HTML 里根本没有 `<a>` 链接 → 正则抽 0 条。
2. **来源固定 + 不翻页**：`SOURCES` 硬编码约 15 个官方源，每个源 `limit` 3–12 条；除人民网走 `list_pages`（翻 3–6 页）外，**其余源都只抓频道首页一次**。
3. **只留当天**：`fetch_candidates` 只保留 `date == target` 的条目，进一步收窄。

实测：`content/` 目前 5 个日期目录、共 48 个 `article-*.json`，最新一天（2026-08-16）只有 `digest.json`，剪藏还没产出。

**瓶颈排序**：① 列表页不翻页 + 来源少（量上不去）→ ② JS 渲染列表页抓不到（漏源）→ ③ 正则脆弱（改版即失效）。

## 二、Crawl4AI 是什么

[Crawl4AI](https://github.com/unclecode/crawl4ai) 是开源（Apache-2.0）Python 库，底层用 Playwright（无头 Chromium），定位就是「面向 LLM 数据管道的网页爬取」。关键能力正好对症：

1. **JS 渲染**：真实浏览器渲染后再取 DOM/Markdown，解决「列表页无链接」。
2. **深度爬取**：`CrawlerRunConfig` + `CrawlerStrategy.BFS` + `css_selector`/链接过滤，沿链接多页爬，替代「只抓首页」。见[官方 Deep Crawling 文档](https://github.com/unclecode/crawl4ai/blob/1debe5f5/docs/md_v2/core/deep-crawling.md)。
3. **结构化抽取**：`JsonCssExtractionStrategy`（CSS 选择器，零 LLM 成本）或 `LLMExtractionStrategy`（schema 驱动，LLM 抽标题/日期/正文/摘要 JSON）。见[爬取策略与执行](https://deepwiki.com/unclecode/crawl4ai/2.2-crawler-strategy-and-execution)。
4. **异步并发 + 缓存**：`AsyncWebCrawler` / `arun_many` 批量并发，内置缓存，返回清洗后的 Markdown。

## 三、能不能解决「网页太少」：能，但要算代价

| 维度 | 评估 |
| --- | --- |
| 对症程度 | 高。直击瓶颈①（翻页/深爬）和②（JS 渲染） |
| 依赖成本 | 重。需 `crawl4ai` + `playwright install chromium`（约百 MB 浏览器），抓取速度慢于 httpx（渲染开销） |
| 部署可行性 | 可行。管道跑在 GitHub Actions `ubuntu-latest`，加一步 `playwright install --with-deps chromium` 即可（见 `daily.yml`） |
| LLM 成本 | 可选。基础标题/日期/正文用 CSS 选择器零成本；摘要/AI 标注仍走现有 DeepSeek 链路，不额外放大成本 |
| 架构边界 | 需遵守 AGENTS.md：AI 不得注入 HTML、返回结构化 JSON、程序负责定位校验。Crawl4AI 只做「取页面/取链接」，不越界 |

## 四、落地建议（三选一）

- **方案 A（零风险，先做）**：不改依赖。给 `Source` 加 `max_pages` 翻页支持（推广到所有源）、提高 `limit`、补充更多官方源。立竿见影，但治不了 JS 渲染。
- **方案 B（推荐，渐进）**：引入 Crawl4AI 作为**可选抓取引擎**，新增 `mode="crawl"` 适配器，先对 1–2 个 JS 渲染 / 多页源试点；httpx 链路保留不动。验证收益后再推广。
- **方案 C（激进）**：全面切到 Crawl4AI。收益大但改动面大、回归风险高，不建议一步到位。

**推荐**：先做 A（本周可见量提升、无风险），同时按 B 做一个小规模 PoC（1 个 JS 源），用数据对比「新增条数 / 成功率 / 耗时」再决定是否推广。

## 五、方案 B 的落地改动清单（参考）

1. `pipeline/pyproject.toml`：新增 `crawl4ai` 依赖（放可选 extra，避免强制所有人装浏览器）。
2. `.github/workflows/daily.yml`：管道步骤加 `python -m playwright install --with-deps chromium`。
3. `pipeline/src/kaogong/`：新增 `crawl.py` 适配器（`AsyncWebCrawler` + `CrawlerStrategy.BFS` + CSS 选择器抽链接/正文），对外输出现有 `Candidate` / `ClippedArticle` 形状，保持「抓取引擎可注入、可测试」的既有风格。
4. 测试：复用现有 mock 风格，给 crawl 适配器补单测；质量门禁沿用 `quality.py`。
5. 文档：若采纳，补 ADR（新增基础设施级依赖属于需 ADR 的变更）。

## 六、待你确认的问题

1. 优先解「量」（方案 A：多源 + 翻页）还是优先解「JS 漏抓」（方案 B：Crawl4AI）？还是两者都要？
2. 若上 Crawl4AI，是否接受「CI 拉取 Chromium + 抓取变慢」的代价？
3. 是否需要我先做方案 A 的「多源 + 翻页」快速版，Crawl4AI 之后再说？
