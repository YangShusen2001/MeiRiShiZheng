# 精品阅读站落地方案（Precision Pivot Plan）v2.1

- 日期：2026-09-11（v2.1 修订：配额顺序缺陷修复；v2 依据黄金样本 `_review/gold-2026-09-11.json`，40 条全标注）
- 作者：高见远（架构师）
- 输入：`docs/product/product-diagnosis-and-ai-strategy.md`、调研一/二/三、**黄金样本标注（40 条：8 in / 32 out，全部带用户原话理由）**
- 目标：把「时政考点记忆系统」定位忠实落地为**精品阅读站** —— 少而深、考什么学什么、记得住。
- 纪律：**不写代码，只出方案**；所有结论具体到「文件:行号 / 数据结构 / 伪代码 / 依赖 / 工时 / 验收」。

> **v2 修订记录**（相对 v1）：
> 1. §2 源清单从「源级 tier」改为「**栏目级白名单/黑名单**」——黄金样本证明同源两种命运（四川在线 ggxw 垃圾 vs 新思想自习室精品）。
> 2. §3 配额对象从「源全量」改为「栏目过滤后的每源净流量」。
> 3. **新增 §5 内容密度门禁**——黄金样本证明「有正文但全是图注/纯数据」的载体缺陷无法靠现有 video_no_text/too_short 抓住。
> 4. §7.2 AI 语义判据从「C 级过滤」细化为**7 类进池信号 + 8 类不进池信号**（全部提取自用户原话），并新增 needsHuman 人审标记。
> 5. **新增 §8 人审位设计**——用户原话「发布会这个度机器把持不好」。
> 6. §10 拍板项更新；任务框架与 sparse 状态不变，工时 20h → 26h。
>
> v1 两大假设被黄金样本推翻（详见 §1.1）：**「地方源整体砍掉」与「领导人活动是核心考点」均不成立**。判据不在「源」级、不在「级别」级，而在「**栏目 + 内容形态 + 信息密度**」级。

> **v2.1 修订记录**（相对 v2，修复配额顺序缺陷；T01-T03 交付后由主理人复演发现、架构师复演确认并扩大范围）：
> 1. **§3 配额 + CAPS 从 fetch 层后移至密度门禁之后**——v2 把配额放在 fetch 层（标题层），先于密度门禁（正文层）执行，且按列表序（= 发布时间倒序，与价值无关）截断，回放误杀 3 篇 IN（政绩观/塞上江南/琴澳）。v2「T04 密度门禁可覆盖配额风险」在物理执行序上不成立。
> 2. **A1 修正：CAPS 必须同步后移**——`_pick_top`（pipeline.py:66-84）无 DeepSeek key 时退化为列表序（`:69` 注释自认），pol 池 12 > CAPS 8，仅移配额救不了政绩观/塞上江南。
> 3. **A2 修正：后移后的配额/CAPS 截断按 `total_chars` 降序**——复用密度指标做弱价值代理，防残余列表序风险。
> 4. §5.4 密度门禁接入点改为**两阶段剪藏**；§1.2/§5.5/§7.4/§8.4/§9/§10⑨/§11/附录 A/B/C 联动更新；附录 B 新增全链路硬断言「**8/8 IN 在含配额的全链路存活**」。
> 5. 工时 26h → 30h（T02 返工 +1h，T04 扩容 +3h）。

---

## 1. TL;DR

### 1.1 黄金样本推翻的两个假设（v2 的出发点）

| v1 假设 | 黄金样本证据 | 修正后的判据 |
|---|---|---|
| 「地方源整体砍掉」 | 用户在 40 篇里留 8 篇，其中 **3 篇来自 v1 要砍的源**：大洋网（黄坤明调研✅、琴澳✅）、四川在线 ggxw（AI 全球治理✅「新思想自习室」、追星✅「天府新视界」） | 判据在**栏目级**：四川在线「新思想自习室/天府新视界」是理论栏目要保留，同 URL 前缀的 ggxw 快讯是垃圾；大洋网 5 篇留 2 篇（40% 精品率），靠密度门禁+AI+人审 |
| 「领导人活动是核心考点」 | 用户砍掉金砖会晤（「就非常短的一句话…没什么用」）、丁薛祥 APEC（「不是特别大的会议…更多体现的是一种形式」）、王小洪（「谈话太宏大了，除了谈话以外就没有别的信息」） | 判据是**信息密度**而非出席人级别：短讯式通稿无论多高级别都砍；「AI 治理」（习近平讲话全文金句）反而 IN |

### 1.2 推荐路线（v2.1）

**四道纯规则零 AI 成本闸门，按信息充分度排序：栏目白名单（标题层）→ 簇去重 → 内容密度门禁（正文层）→ 每源配额 + CAPS（正文层、密度之后、total_chars 降序）+ 一次 AI 语义评级（7 进 8 出判据）+ needsHuman 人审兜底。**

> v2.1 关键修正：v2 把配额放在 fetch 层（标题层、列表序截断），先于密度门禁执行，回放误杀 3 篇 IN。**闸门顺序必须与信息充分度一致**——只有拿到正文，才知道该留谁砍谁。详见 §3。

用黄金样本回放验证：规则层（栏目 + 簇去重 + 密度 + 配额）可杀掉 32 篇 OUT 中的 **25-27 篇**（v2 口径的栏目+密度下限 22 篇 + 配额层新增 ~3-5 篇，精确归属以 T04 全量回放为准），且 **8 篇 IN 在含配额的全链路全部存活**（附录 B 硬断言）；剩余 5-7 篇 OUT（人民网形式性短讯、人文纪实、疑似错标项）交给 AI 评级判 C 级 + needsHuman 人审。

**AI 成本量级（v2.1 口径）**：新增闸门 **0 次调用**（后移版配额按 total_chars 排序，不再经 `_pick_top` 调 judge_item）；`assign_grades` 每天仍 **1 次批量调用**；`analyze_article` 因两阶段剪藏（先密度/配额、后分析）从 28-59 篇缩到 **~15 篇**，**调用数下降 ~60-75%**。剪藏 HTTP 量 15→22 条/天（~48s，可接受）。**净效果：AI 总成本显著下降，而不是上升。**

**总工时：30h（≈3.75 人日）**，5 个任务。T01-T03 为 P0 纯规则零 AI 成本（T02 需 +1h 返工摘除 fetch 层配额/CAPS，见 §9）。

---

## 2. 源与栏目清单改造（栏目级白名单/黑名单）

### 2.1 生产侧事实（v1 已核实，不变）

- 生产配置 = `pipeline/config.json`（`config.py:13` `CONFIG_PATH`），**不是 D1**（`apps/api/src/db/schema.ts` 无 site_config 表，Worker 代码零处引用 sources）。
- 管理后台 `POST /api/config`（`review/server.py:709-729`）写回的也是这个仓库文件。
- **改法 = 改 `pipeline/config.json` + 同步 `sources.py:DEFAULT_SOURCES`，两处必须一致**（一致性测试防漂移，见 T01）。

### 2.2 黄金样本的源级精品率（新证据）

| 源（host） | 样本数 | IN | OUT | 精品率 | 关键观察 |
|---|---|---|---|---|---|
| sichuan.scol.com.cn | 20 | 2 | 18 | 10% | **同源两种命运**：2 篇 IN 全是理论栏目（新思想自习室/天府新视界），18 篇 OUT 全是 ggxw 快讯（遂宁×6、强相关×11、天天学习×1） |
| news.dayoo.com | 5 | 2 | 3 | 40% | 黄坤明调研/琴澳 IN（结构价值），纯数据/发布会介绍/广告 OUT |
| politics.people.com.cn | 5 | 0 | 5 | 0% | 全是领导人短讯/部门工作报告（金砖/丁薛祥/王小洪/谌贻琴/火灾批示） |
| news.cn | 7 | 2 | 5 | 29% | 政绩观/塞上江南 IN，载体缺陷×2（溇港诗行、产业蝶变图注）+ 发布会介绍 + 粒度太细 OUT |
| banyuetan.org | 2 | 1 | 1 | 50% | 学医 IN（分析深度），麻风村 OUT（人文纪实无政策） |
| qstheory.cn | 1 | 1 | 0 | 100% | 救治善后 IN（分省做法） |
| opinion.southcn.com | 1 | 0 | 1 | 0% | 横琴 OUT（⚠️ 标注理由疑似与 banyuetan 麻风村错位，见 §10-⑦） |
| jiangsu.gov.cn / gd.gov.cn / comment.scol / xhby.net | 0 | 0 | 0 | 无样本 | 无新证据，沿用调研三处置（整体移出，可逆） |

### 2.3 机制设计：Source 增加栏目级正则

在 `sources.py:68-82` 的 `Source` dataclass 新增两个字段（与 v1 的 `tier` 并存，`tier` 只用于「整源移出」）：

```python
@dataclass(frozen=True)
class Source:
    ...
    tier: str = "core"              # 整源级：core 进池 / background 移出（可逆）
    column_keep_re: str = ""        # 栏目白名单：命中才进池（如四川在线理论栏目）
    column_drop_re: str = ""        # 栏目黑名单：命中即丢弃
```

**过滤位置**：三处提取器统一在标题清洗后过滤（`extract` 的 `sources.py:247-251` 之后、`_extract_pubdate` 的 `:280-282` 之后、`list_pages` 模式在 `fetch_source` 的 `:314-318`）：

```python
def _column_ok(source: Source, title: str) -> bool:
    """栏目级过滤：白名单未命中或黑名单命中 → 丢弃。空正则 = 不过滤。"""
    if source.column_keep_re and not re.search(source.column_keep_re, title):
        return False
    if source.column_drop_re and re.search(source.column_drop_re, title):
        return False
    return True
```

**同时**：`source_to_dict`/`source_from_dict`（`sources.py:100-135`）补三个字段的 JSON 往返；`load_sources`（`:138-150`）保留 `tier=="core"` 过滤。

### 2.4 逐源处置清单（v2 最终版）

| # | 源名 | slot（新） | 处置 | 配置要点 | 依据 |
|---|---|---|---|---|---|
| 1 | 求是网 | `qst` | ✅ 核心 | 不变（limit 12） | 1/1 IN（救治善后，分省做法） |
| 2 | 半月谈今日谈 | `byt` | ✅ 核心 | 不变（limit 8） | 1/2 IN（学医）；麻风村由 AI 判 |
| 3 | 新华时评 | `xh` | ✅ 核心 | 不变 | 调研三核心 |
| 4 | 新华网评论 | `xh` | ✅ 核心 | 不变 | 同上 |
| 5 | 人民日报评论 | `rm` | ✅ 核心 | 不变 | 同上 |
| 6 | 人民网时评 | `shi` | ✅ 核心 | 不变 | 同上 |
| 7 | 南方时评 | `nf` | ⚠️ 降配保留 | limit 10→3 | 1 样本 OUT（疑似错标，§10-⑦）；等更多证据 |
| 8 | 中国政府网政策 | `gov` | ✅ 核心 | 不变 | 调研三核心 |
| 9 | 广东政策解读 | `gdp` | ⚠️ 降配保留 | limit 15→5 | 无当日样本；是「政策解读」非地方要闻 |
| 10 | 人民网时政 | `pol` | 🟡 保留严限 | limit 20→8, max_pages 8→2, **配额≤3** | 当天 0/5，但样本仅一天；有实质内容的领导人活动仍需此源，短讯由密度门禁 G1 + AI 判杀 |
| 11 | 新华网时政 | `pol` | 🟡 保留严限 | limit 15→8, max_pages 6→2, **配额≤3** | 同上（政绩观/塞上江南 2 篇 IN 出自此源） |
| 12 | **四川全媒快讯** | `sc`→**`essay`** | 🔄 **栏目白名单保留** | `column_keep_re = r"丨(新思想自习室|天府新视界)"`，limit 12 不变（白名单做裁剪），**配额≤3** | 2/20 IN 全在理论栏目；ggxw 快讯 18 篇全灭；天天学习（视频稿）不在白名单，自然淘汰 |
| 13 | **大洋网广东** | `gd`→**`essay`** | 🔄 **保留降配** | limit 8→6，**配额≤3**，`column_drop_re = r"(消费券|优惠券)"` | 2/5 IN（黄坤明调研、琴澳，结构价值）；OUT 3 篇中纯数据由 G2 杀、广告由 drop_re 杀、APEC 发布会由人审 |
| 14 | 江苏政府网要闻 | `js` | ❌ 移出 | `tier="background"` | 无样本；调研三地方要闻结论 |
| 15 | 广东政府网要闻 | `gd` | ❌ 移出 | `tier="background"` | 同上 |
| 16 | 天府评论 | `sc` | ❌ 移出 | `tier="background"` | 同上（地方评论） |
| 17 | 交汇点时评 | `js` | ❌ 移出 | `tier="background"` | 同上 |

**slot 重映射说明**：四川理论栏目（新思想自习室/天府新视界）本质是**申论理论/评论**内容；大洋网黄坤明调研/琴澳被用户留下的理由是**结构价值**（「结构非常好，非常值得去看」）—— 都是精读素材，映射到 `essay`（申论精读）。`sc`/`gd`/`js` 三个 slot 随地方分节删除而废弃（§6）。

### 2.5 为什么保留「tier + 栏目正则」双机制而非只用栏目正则

- **tier（整源）**：适用于「整个源无精品证据」的 4 源（江苏/广东政府网、天府、交汇点）。它们没有栏目后缀可依托，写正则 = 伪精确。
- **column_keep_re（栏目）**：适用于「同源分裂」的四川在线——20 条里 18 条垃圾 2 条精品，只有栏目名是稳定判据。
- **column_drop_re（黑名单）**：适用于大洋网广告类（消费券）这种标题模式明确的垃圾。
- 三者正交、可组合，且都是**纯规则零成本**。

### 2.6 改动清单（照此实施）

| 文件:位置 | 改动 |
|---|---|
| `sources.py:68-82` | `Source` 新增 `tier` / `column_keep_re` / `column_drop_re` 三字段 |
| `sources.py:100-117` | `source_to_dict` 输出三字段 |
| `sources.py:120-135` | `source_from_dict` 读取三字段（默认 core/空） |
| `sources.py:138-150` | `load_sources` 末尾过滤 `tier=="core"` |
| `sources.py:229-265` | `extract` 增加 `_column_ok` 过滤（标题清洗后） |
| `sources.py:268-306` | `_extract_pubdate` 同上 |
| `sources.py:309-322` | `fetch_source` 的 list_pages 分支同上 |
| `sources.py:181-223` | `DEFAULT_SOURCES` 按 §2.4 表改（tier/slot/limit/column_re） |
| `pipeline/config.json:2-237` | 同步 §2.4 全部改动 |
| `sources.py:164-167` | `DEFAULT_NOISE_TITLE` 追加 `"消费券"`（大洋网广告兜底，双保险） |

---

## 3. 每源配额 + CAPS（v2.1：后移至密度门禁之后，按 total_chars 降序截断）

### 3.1 顺序缺陷复盘（v2 → v2.1 的动因）

v2 把配额设计在 fetch 层（`fetch_candidates` 内、`pipeline.py:121`，T02 已按此交付），存在两个叠加缺陷：

1. **执行序缺陷**：fetch 层只有标题，配额在密度门禁（clip 层，§5）**之前**执行——v2「T04 密度门禁可覆盖配额风险」的说法在物理执行序上不成立，密度救不回已被配额杀掉的条目。
2. **排序缺陷**：`_quota_per_source` 按列表序截断（`group[:n]`），而列表序 = 发布时间倒序，**与价值无关**。复演（黄金样本日）：fetch 层配额杀 7 条，其中 **3 条是 IN**——政绩观（news.cn 列表第 5）、塞上江南（news.cn 第 6）、琴澳（dayoo 第 4）。

**根因**：闸门顺序必须与「信息充分度」一致。标题层只能做标题级判断（栏目白名单）；「留谁砍谁」的配额决策需要正文信息（密度、字数），必须放到拿到正文之后。

### 3.2 方案比选（三选一 + 两处修正，选定 A）

| 方案 | 内容 | 结论 |
|---|---|---|
| **A（选定）** | 配额后移到剪藏 + 密度门禁之后执行 | ✅ 主理人复演 8/8 IN 全复活，剪藏量 15→22（HTTP ~48s，可接受） |
| B | 配额仍在 fetch 层，但配额内按标题信号排序 | ❌ 否决：news.cn 6 条候选（溇港/知识产权/海上数据集/政绩观/塞上江南/产业蝶变）标题均无「发布会/短讯」类可分辨信号，标题层排序救不了 IN |
| C | 差异化配额（按源/栏目配不同额） | ❌ 主理人已验证不解决问题（价值差异在同一源内部，不在源之间） |

**A1 修正（CAPS 必须同步后移，架构师复演新发现，主理人未覆盖）**：CAPS 在 fetch 层经 `_pick_top`（`pipeline.py:66-84`）应用，其 `:69` 注释自认「无 DeepSeek key 或评分失败时 score=0，稳定排序退化为列表顺序」——与配额同源的值盲截断。若只移配额不移 CAPS：pol 池 = 人民网时政 5 + 新华网时政 7 = 12 > CAPS[pol]=8，且合并迭代序人民网在前，**政绩观（第 9）/塞上江南（第 10）会死在 CAPS 层**。⇒ 配额与 CAPS 一起后移，合并为 `_apply_quota_and_caps` 单一执行点。

**A2 修正（后移后按 total_chars 降序截断）**：后移消除了「无正文」问题，但若仍按列表序截断，残余风险仍在——如 news.cn 5 条过密度，配额 3 按列表序仍可能杀掉塞上江南。⇒ 截断排序键 = `total_chars` 降序：**复用密度门禁已算出的字数指标，零新增启发式、零 AI 成本**，是弱但非零的价值代理（黄金样本 IN 均为 800-4000+ 字长文，被列表序误杀的多为短稿）。

### 3.3 新执行序（两阶段剪藏）

```
fetch：tier → column_re → 日期/噪声 → MAX_PRECLIP 安全阀（全局 ≤48；正常日 ~22，远不触发）
  ↓                                    【无配额、无 CAPS】
build_content：簇去重 → 写临时 digest.json（~22 条）
  ↓
clip_content pass-1：全量剪藏（线程池，仅 HTTP，~48s）
  ↓
密度门禁（density_gate，§5）：淘汰载体缺陷稿 → densityRejected 落 report
  ↓
_apply_quota_and_caps：每源配额（total_chars 降序）→ 槽位 CAPS（total_chars 降序）→ quotaRejected 落 report
  ↓
重写 digest.json（最终 ~15 条）
  ↓
clip_content pass-2：仅对最终存活者做 analyze_article（AI 调用锁定 ~15 次/天）
  ↓
curate_content：AI 评级（7 进 8 出）→ picks
```

### 3.4 伪代码（v2.1 版）

```python
# pipeline.py —— fetch 层（T02 返工）
MAX_PRECLIP = 48   # 安全阀：防单日刷屏拖垮剪藏；正常日 ~22，远不触发

def fetch_candidates(...):
    ...
    out = _noise_filter(out)                    # 既有链路保留到日期/噪声过滤
    out = _preclip_ceiling(out, MAX_PRECLIP)    # ← 替代原 :121 配额 + :127-128 CAPS
    return out                                  # source_name 回填保留（后移配额仍需分组键）

# pipeline.py —— clip 层（T04 新增，密度门禁之后调用）
def _apply_quota_and_caps(clipped: list[dict]) -> tuple[list, list]:
    """clipped = 密度已通过的剪藏产物，携带 source_name / slot / total_chars
    （total_chars 与 density_gate 同源，零额外计算）。返回 (final, cut)。"""
    by_source: dict[str, list[dict]] = {}
    for it in clipped:
        by_source.setdefault(it["source_name"] or _host_of(it["url"]), []).append(it)
    kept, cut = [], []
    for name, group in by_source.items():
        group.sort(key=lambda it: -it["total_chars"])           # A2：字数降序
        n = QUOTA_OVERRIDES.get(name, PER_SOURCE_QUOTA)
        kept.extend(group[:n]); cut.extend(group[n:])
    by_slot: dict[str, list[dict]] = {}
    for it in kept:
        by_slot.setdefault(it["slot"], []).append(it)
    final = []
    for slot, group in by_slot.items():
        group.sort(key=lambda it: -it["total_chars"])           # CAPS 同口径
        cap = CAPS.get(slot, 20)
        final.extend(group[:cap]); cut.extend(group[cap:])
    return final, cut
```

### 3.5 v2 原始动机重估：配额后移是否破坏其设计目的

v2 §3.2 的配额动机有两个，逐一重估（**结论：均不受破坏，其一反而更精准**）：

| 动机 | v2 实现 | v2.1 后 | 结论 |
|---|---|---|---|
| **控剪藏量**（HTTP 成本） | fetch 层先砍再剪 | 剪藏 15→22 条/天（~48s HTTP） | ✅ 可接受——安全阀改由 `MAX_PRECLIP` 承担（防刷屏），正常日不绑定 |
| **控 AI 分析量**（配额的真实成本大头） | 间接（digest 小 → 分析少） | 直接——analyze 仅对配额后存活者执行（~15 次/天） | ✅ 更精准：AI 花在「密度过关且为同源最长」的条目上 |
| CAPS 口径 | fetch 层 `_pick_top`（无 key 退化列表序） | 后移并入 `_apply_quota_and_caps`，total_chars 排序 | ✅ 值不变（pol 8 / essay 10 / gdp 5，删 gd/sc/js），语义从「控抓取」变「控 digest 规模」 |
| 报告字段 | `candidates` = fetch 后数量 | **`candidates` = 最终 digest 条数**；新增 `candidatesRaw` / `densityRejected` / `quotaRejected` | ✅ 见 §3.6 兼容性分析 |

### 3.6 报告字段兼容性（硬约束）

`quality.py:138-168` `volume_errors` 取**最近 5 份 ok/degraded 报告**的 `candidates` / `articles` 中位数做基线，低于一半报 `below_half_baseline`；`quality_gate` 另有 `candidates==0` 空检查。因此：

- **`report["candidates"]` 必须继续填「最终 digest 条数」（~15）**，不能改成 fetch 原始量——否则基线比较失真、空检查语义漂移。
- fetch 原始量改记 `report["fetch"]["candidatesRaw"]`；密度淘汰记 `report["clip"]["densityRejected"]`（含 reason）；配额淘汰记 `report["clip"]["quotaRejected"]`（含 source/total_chars）——工作台可据此展示「被机器淘汰但可救」的条目（§10-⑨）。
- **基线重置**：pivot 上线日，历史报告 `candidates`（28-59）会使新常态（~15）触发 `below_half_baseline` 误报。T05 验收含「基线重置或阈值调整」（清空 5 份窗口内的旧报告，或对 pivot 日打标跳过）。

### 3.7 配额/CAPS 取值（不变，仅执行位置与排序变）

| 级 | 机制 | 作用域 | 取值 |
|---|---|---|---|
| 1 | `_apply_quota_and_caps` 配额段 | 每源（密度过滤后净流量） | 默认 ≤3，理论源（求是/半月谈/中国政府网）≤4 |
| 2 | `_apply_quota_and_caps` CAPS 段 | 每槽位大盘 | `pol` **8**；`essay` **10**（承接大洋网+四川理论栏目）；删 `gd/sc/js`；`gdp` **5**；其余不变 |

**规模预估**（黄金样本日回放）：fetch 后 ~22 → 密度 -4 → 配额/CAPS -3 → **最终 digest ~15 条**（vs 现状 28-59），AI 分析 ~15 次/天。

---

## 4. 簇去重机制（v1 设计保留）

v1 §4 全部保留：`dedupe.py` 新增 `cluster_dedupe()`（判据：同 host + 同日 + (现有 `is_same_event` ≥8 字 ∨ LCS≥6 字 ∧ URL 序号差≤2)；每簇保留列表首条；`build.py:56` 入口接入）。**黄金样本佐证**：遂宁 7 条（`83320358/61/64/65/57/60/59` 相邻序号）→ 簇去重聚合为 1；且这 7 条全在 `column_keep_re` 白名单外（ggxw 快讯），**栏目白名单已先行全灭**——簇去重是双保险（若未来理论栏目也出拆条，仍能聚合）。

（判据细节、伪代码、误合并风险分析见 v1 §4，未改动。）

---

## 5. 内容密度门禁（新增）

### 5.1 问题定义

黄金样本中有三类「**剪藏成功、有正文，但用户判垃圾**」的载体缺陷，现有门禁抓不住：

| 案例 | 用户原话 | 现有门禁表现 |
|---|---|---|
| 产业蝶变（`2a713d887b`） | 「大部分都是一张图片配一小行的文字」 | 剪藏成功 12 段，`video_no_text`/`too_short` 均未触发 |
| 大湾区进出口（`333b9d6044`） | 「全是数据，没有分析」 | 剪藏成功 4 段，无门禁可拦 |
| 金砖短讯（`0bd839c1d9`） | 「就非常短的一句话…没什么用」 | 2 段恰好绕过 `too_short`（`clip.py:206` 要求 <2 段） |

### 5.2 阈值校准（用黄金样本实测，这是本节的核心价值）

我逐篇读取了 `content/2026-09-11/article-*.json` 的剪藏正文，实测指标：

| 文章 | 判定 | 总字数 | 段数 | 数字占比 | 分析词¹ | 规则门禁结果 |
|---|---|---|---|---|---|---|
| 金砖短讯 | OUT | ~130 | 2 | 低 | 0 | ✂ **G1 杀** |
| 大湾区数据 | OUT | ~430 | 4 | **~0.15** | **0** | ✂ **G2 杀** |
| 产业蝶变 | OUT | ~700 | 12 | 0.03 | **0** | ✂ **G4 杀** |
| 丁薛祥 APEC | OUT | ~800 | 5 | 低 | ~2 | 规则放行 → AI 层（形式性致辞） |
| **AI 治理（新思想自习室）** | **IN** | **~800** | 4 | 低 | ~3 | ✅ 通过（**约束 G1 阈值 ≤600**） |
| 学医 | IN | ~4000 | 17 | 中 | **多** | ✅ 通过（分析词保护） |
| 政绩观 | IN | ~4000+ | 15+ | 低 | 有 | ✅ 通过 |
| 塞上江南 | IN | ~3000 | 20 | 低 | 有（含"分析"） | ✅ 通过 |
| **救治善后（求是）** | **IN** | ~2000 | — | 低 | **有（"推动"）** | ✅ 通过（**约束 G4 不得用"地名多"单独判杀**——它是用户点名要的多省做法文章） |

¹ 分析词表：`因为|由于|意味着|反映|表明|分析|剖析|原因|得益于|推动|支撑|背后|折射|为何|为什么`

**三条校准红线**（阈值必须同时满足）：
1. **G1 下限 ≤600 字**——AI 治理（IN）只有 ~800 字，阈值高于 600 会误杀精品。
2. **G4 不得用「地名离散度」单独判杀**——救治善后（IN）就是多省文章，用户明确要「广东、河北、天津具体怎么做」；判杀必须叠加「零分析词 ∧ 字数上限」。
3. **G2 必须双条件合取**——学医（IN）数字也多，靠「分析词=0」保护。

### 5.3 四条判据（纯规则，全部可单测）

```python
# 新模块 pipeline/src/kaogong/density.py
DENSITY_MIN_CHARS     = 400    # G1：总字数下限（金砖130✂，AI治理800✅）
DENSITY_DIGIT_RATIO   = 0.12   # G2：数字+百分号占比阈值（大湾区~0.15✂，学医有分析词✅）
DENSITY_SHORT_RATIO   = 0.60   # G3：短段(<35字)占比阈值（诗行/图注稿）
DENSITY_SHORT_PARA    = 35     # "短段"定义（字）
DENSITY_PANCHA_CHARS  = 1500   # G4：拼盘稿字数上限（产业蝶变700✂，政绩观/学医4000✅）
DENSITY_PANCHA_PARAS  = 6      # G4：拼盘稿段数下限

ANALYSIS_WORDS = re.compile(r"因为|由于|意味着|反映|表明|分析|剖析|原因|得益于|推动|支撑|背后|折射|为何|为什么")

def density_gate(paragraphs: list[str]) -> str | None:
    """返回拒绝原因（'shallow_notice'|'pure_data'|'caption_style'|'patchwork'），通过返回 None。"""
    text = "".join(paragraphs)
    total = len(text)
    n = len(paragraphs)
    if total == 0:
        return "empty"
    # G1 浅讯稿：领导人短讯/一句话通稿
    if total < DENSITY_MIN_CHARS:
        return "shallow_notice"
    analysis_hits = len(ANALYSIS_WORDS.findall(text))
    # G2 纯数据稿：数字密集且零分析词
    digit_ratio = len(re.findall(r"[0-9.%％]", text)) / total
    if digit_ratio >= DENSITY_DIGIT_RATIO and analysis_hits == 0:
        return "pure_data"
    # G3 图注/诗行稿：短段占绝对多数（溇港诗句、真·图注）
    short = sum(1 for p in paragraphs if len(p) < DENSITY_SHORT_PARA)
    if n >= 3 and short / n >= DENSITY_SHORT_RATIO:
        return "caption_style"
    # G4 零分析拼盘稿：段多、字少、无分析词（产业蝶变：多地掠影）
    if analysis_hits == 0 and n >= DENSITY_PANCHA_PARAS and total < DENSITY_PANCHA_CHARS:
        return "patchwork"
    return None
```

### 5.4 接入位置（v2.1）：两阶段剪藏的 pass-1 之后、配额之前

v2 原设计「`_clip_and_analyze` 内逐条拦截」随配额后移一并升级为**两阶段结构**（§3.3）：pass-1 全量剪藏 → 密度门禁 → 配额/CAPS → digest 重写 → pass-2 仅对存活者做 `analyze_article`。密度拒绝的落地方式：

```python
# clip_content 内（pass-1 与配额之间）
survivors, density_rejected = [], []
for clip in clipped:                                   # pass-1 产物
    reason = density_gate(clip.get("paragraphs") or [])
    if reason:
        clip["error"] = f"density_low:{reason}"        # 既有错误前缀约定保留
        density_rejected.append({"id": clip["id"], "title": clip["title"],
                                 "reason": reason, "source": clip.get("source_name")})
    else:
        survivors.append(clip)
report["clip"]["densityRejected"] = density_rejected   # 工作台可见（§3.6）
# → 接 _apply_quota_and_caps(survivors)（§3.4）→ 重写 digest → pass-2 分析
```

**零新增管道**：拒绝仍以 `density_low:<reason>` 前缀进 `clipDetails`/report 流（`pipeline.py:195-201`）；最终 digest 只含存活者，`coarse_filter`（`curation.py:61` 要求 `aiStatus=="ok"`）双保险挡在 picks 之外。**AI 省钱效果不变**：密度不过关的条目永不进入 pass-2 分析。

### 5.5 黄金样本回放预期（验收基准）

| 门禁 | 杀掉的 OUT | 放行的 IN（须全数验证） |
|---|---|---|
| G1 浅讯 | 金砖（130字） | AI 治理（800字）✓ |
| G2 纯数据 | 大湾区数据 | 学医（有分析词）✓ |
| G3 图注/诗行 | 溇港（若剪藏出诗行短段） | — |
| G4 拼盘 | 产业蝶变（0分析词/12段/700字） | 救治善后（有"推动"）✓、政绩观/学医（>1500字）✓ |
| **合计（栏目+密度）可杀** | **22/32**（含栏目白名单 18 + 密度 3~4） | **8/8 IN 过密度门禁** |

密度之后再经 §3 配额/CAPS（total_chars 降序）淘汰 ~3 条最短 OUT（回放预期：火灾批示/海上数据集/知识产权或 APEC 深圳之一二）→ **规则层合计 ~25-27/32**；剩余 5-7 篇 OUT（人民网形式性短讯 2-3、麻风村、横琴、配额幸存的发布会类）→ §7 AI 评级 + §8 人审。

---

## 6. 分节与槽位新结构（v1 保留 + slot 重映射增量）

v1 §5 的结论全部保留（前端动态渲染已核实：`index.astro:55`、`HomePage.ets:659`；删除地方分节风险低；`digest.py:26-39` SECTION_SLUG 清理死映射）。**v2 增量**：

| 项 | v1 | v2（依据 §2.4 slot 重映射） |
|---|---|---|
| 分节集合 | national / essay / policy | **不变**（3 个） |
| `essay` 内容来源 | shi+qst+xh+rm+byt(≤2)+nf | + **大洋网、四川理论栏目**（slot 已改 essay）——黄坤明调研/琴澳/AI 治理/追星四篇 IN 自然流入申论精读 |
| `build.py:19-32` SLOT_SOURCE | 清理 gd/sc/js | 同 v1；`essay` 的来源名描述补「大洋网/川观理论栏目」 |
| CAPS | essay 18 | essay **10**（§3.7） |

地方保留栏目的文章在 `essay` 分节内按 DigestItem 的 `source` 字段区分来源，无需前端改动。

---

## 7. 宁缺勿滥的机制化 + AI 语义判据（7 进 8 出）

### 7.1 v1 保留部分（不动）

- **删除历史补剧**（`curation.py:342-355`），改记 `slots["sparse"]=True`；`history` 参数保留但传 `[]`（保留 `_load_history` 函数体，减 diff 面）。
- **MIN_PICKS 2→0**；「0 篇 = 不写 picks.json」（沿用 `curation.py:519`，schema 零改动，方案 α）。
- **sparse 状态**（`pipeline.py:416-421` 新增分支）：`articles>0 ∧ picked≤1` → `qualityStatus="sparse"`，不阻止发布；**保留** `picks_slots_all_empty` 的 degraded 语义（两者正交：sparse=缺料合法，slots_all_empty=有料分配异常）。

### 7.2 AI 语义判据（替换 v1 的「C 级过滤」）

黄金样本的 40 条理由构成完整的判据体系。**全部写进 `curation.py:94-123` `_grade_messages` 的 system prompt**（v1 只有一句「S=当日必须精读…」，v2 换成下表判据 + 输出扩展）：

**进池 7 类信号 → 等级映射**：

| 信号（用户原话） | 等级 | 黄金样本例 |
|---|---|---|
| 1. 金句密度：「这一整篇文章都是金句啊，非常值得背诵」 | **S** | AI 全球治理 |
| 2. 常考性：「历年来常考的面试题，申论都会有的内容」 | **S** | 政绩观与军队现代化 |
| 3. 分析深度：「以数据来推断宏观…思维上的提升，深度剖析」 | **A** | 学医 |
| 4. 结构价值：「结构非常好，非常值得借鉴/去看」 | **A** | 黄坤明调研、琴澳 |
| 5. 分省做法罗列：「广东、河北、天津具体怎么做的…分论点素材」 | **A** | 全力救治善后 |
| 6. 社会舆情：「社会舆情舆论，非常好的时政文章」 | **A** | 追星制度边界 |
| 7. 段落级金子：「严格来说并不能入选，但最后两三段有非常好的政策介绍」 | **B**（需给 focus 段落范围） | 塞上江南 |

**不进池 8 类信号 → 一律 C**：

| # | 信号 | 黄金样本例 |
|---|---|---|
| 1 | 空壳领导人短讯/形式性致辞（会见/出席/致辞，无实质内容） | 金砖、丁薛祥 APEC、王小洪 |
| 2 | 地方强绑定（一地成果/活动/风物介绍） | 遂宁×6、丰收节、年画村 |
| 3 | 载体缺陷（视频/图配文/诗行——规则层已拦，AI 兜底） | 产业蝶变、溇港、天天学习 |
| 4 | 纯数据无分析 | 大湾区进出口 |
| 5 | 发布会通稿介绍（无实质政策内容） | 知识产权案例发布、APEC 深圳 |
| 6 | 粒度太细（相关但过细） | 海上保护区数据集 |
| 7 | 广告/服务信息 | 文旅消费券 |
| 8 | 案件结果/人事任免/部门工作报告 | 猫池案、黎明任职、谌贻琴表彰 |

**输出扩展**（`_json_object` 解析 + `assign_grades` 透传）：

```json
{"items": [{
  "index": 0, "grade": "B", "policyLine": null,
  "reason": "结尾三段有政策干货",
  "signals": ["partial_gold"],          // 7 类信号的英文枚举
  "needsHuman": false,                   // 发布会/调研类模糊地带 = true
  "focus": {"from": 17, "to": 19}       // 仅段落级金子（signal=partial_gold）时输出
}]}
```

**needsHuman 判定规则（写进 prompt）**：「标题或正文命中 发布会/峰会/招商活动/调研座谈会 等发布会-通稿形态，且文章可能含实质政策内容时，不要自行判 C，输出 needsHuman=true 交人审」——直接落实用户原话「像黄坤明的必须保留，这个（APEC 深圳）必须去除，**这个度机器把持不好**」。

**程序侧消费**（`curation.py`）：
- `grade == "C"` → 不进 picks 池（v1 的 C 级过滤保留，判据升级）。
- `needsHuman == true` → **留在 digest（原文照发）、不进 picks（宁缺勿滥）、写入 report 待人审**（§8）。
- `signals` / `focus` / `reason` → 写入 `report["curation"]["needsHuman"]` 与 `assignments`，供工作台展示与人审上下文。

**无 key 降级**：沿用 `_program_fallback`（权威性×密度排序），但**全部标 needsHuman=true**（人审兜底，与「不确定就不硬判」哲学一致）——这是 §10-③ 拍板项。

### 7.3 段落级金子 → 标注层（塞上江南需求）

用户原话：「正式生成我们的文章时，我希望前面的可以不用标注那么多，**重点在最后这三段**。这也是人工审核的一个非常的价值所在。」

落地：`article_ai.py:212-232` `_messages` 的 system prompt 增加指令（`PROMPT_VERSION` v1→v2）：

> 「若文章仅部分段落有政策干货（如结尾的政策建议段、分省做法段），优先在这些段落生成标注，并输出 `focus: {"from": 起始段下标, "to": 结束段下标}`。」

- `analyze_article`（`article_ai.py:235+`）解析并持久化 `aiFocus` 字段（校验 0≤from≤to<len(paragraphs)）。
- `content/schema/article.schema.json` 新增可选字段 `aiFocus`（object: from/to, integer, minimum 0）。
- `curation.py` B 级（partial_gold）文章的 `refine_cards` 抽卡锚定段落优先取 `aiFocus` 范围（`card_ai.py` 的 anchor 偏好，1 行改动）。
- **0 次新增 AI 调用**（标注时模型自行识别 focus，评级阶段直接读）。

### 7.4 AI 成本量级（v2.1 最终核算）

| 环节 | 现状 | v2.1 后 | 说明 |
|---|---|---|---|
| `analyze_article` | 28-59 次/天 | **~15 次/天** | 两阶段剪藏：pass-2 仅对密度+配额后存活者分析 |
| `assign_grades` | 1 次/天 | **1 次/天** | prompt 变长（判据表），max_tokens 900→1200，单次成本略升但总量不变 |
| `_pick_top` judge_item | 候选>cap 时逐篇 | **0** | CAPS 改用 total_chars 排序（§3.4），不再调 judge_item |
| 卡片/一练/速览 | 1+1+1 | 不变 | — |
| **合计** | 32-63+ | **~19** | **净下降 ~40-70%** |

---

## 8. 人审位设计（新增）

### 8.1 用户的定位原话

「发布会介绍，**应该让人来审**，像刚刚黄坤明的一个发布会报道，就必须保留，这个（APEC 深圳）必须去除，**他这个度机器把持不好**。」「（塞上江南段落取舍）这也是**人工审核的一个非常的价值所在**。」

→ 人审不是兜底的临时手段，是**发布会/调研类与段落取舍的终审位**。

### 8.2 现有工作台能力盘点（已核实）

`pipeline/src/kaogong/review/`（FastAPI + Tabler UI）：

| 能力 | 位置 | 状态 |
|---|---|---|
| 每日条目列表 + 状态过滤 | `server.py:296` `/api/items/{date}`；`ui/index.html:190` 过滤按钮（全部/剪藏失败/AI失败/已排除） | ✅ 已有 |
| 单条排除（带理由） | `server.py:366` `/api/items/{date}/{id}/exclude`；UI `:381` 🗑 排除按钮 | ✅ 已有 |
| 强制收录 / 恢复 | `server.py:348/:395` force-include / restore | ✅ 已有 |
| AI 审核（判+改+回退） | `server.py:956-1069` review-agent 三件套 | ✅ 已有（判据需同步 §7.2） |
| 报告读取 | `server.py:441` `/api/reports/{date}` | ✅ 已有 |

**缺的只有一件事：把 needsHuman 队列从 report 里捞出来变成一等公民过滤器。**

### 8.3 增量改动（全部在现有工作台上加，不新建系统）

1. **`curation.py:462-474`**：`report["curation"]["needsHuman"] = [{id, title, reason, signals, grade}]`（report 已并入 `_reports/{date}.json`，`/api/reports/{date}` 自动带出，**零 schema 改动**）。
2. **`ui/index.html:190`**：过滤按钮组追加「待人审」（读 report 的 needsHuman 列表与 items 求交集）；行级 badge「🤖 待人审」+ AI reason tooltip。
3. **`ui/index.html:381`**：待人审行的「排除」按钮预填 AI reason 作为排除理由（现有 exclude body 已支持 reason）。
4. **发布不被人审阻塞**：needsHuman 文章留在 digest、不进 picks；用户审完可用 force-include/排除调整 digest。发布流程（`/api/publish`）不变。
5. **（可选增强，本轮不做）**「提升进 picks」按钮：把人审通过的 needsHuman 文章写入 picks.json 的 extra 槽——留待用户验证人审流量后再决定。

### 8.4 每日人审流量核算（v2.1 口径，可持续性论证）

```
40 条候选（现状）
→ 栏目白名单/tier -18~19（四川 ggxw 18 + 天天学习；当日无 background 源样本）
→ 簇去重（遂宁类拆条聚合）
→ MAX_PRECLIP 安全阀（正常日 ~22，不触发）→ 临时 digest ~22 条
→ 剪藏 pass-1 全量（HTTP ~48s）
→ 密度门禁 -3~4（金砖/大湾区/产业蝶变/溇港）
→ 配额 + CAPS（total_chars 降序）-3~4
→ 最终 digest ~15 条 → pass-2 AI 分析 + 评级
→ AI 判 C -4~6 条（不出 picks）
→ needsHuman：发布会/调研类模糊地带 ≈ 1-3 条/天（配额淘汰的发布会类经 report quotaRejected 也可人审救回，§10-⑨）
→ **人审负担：每天 1-3 篇 × 1-2 分钟 = 3-6 分钟**（黄金样本日用户判 40 条用了约半小时，缩到个位数后完全可持续）
```

---

## 9. 有序任务列表（框架不变；v2.1：T02 返工、T04 扩容）

> 仍为 5 个任务（硬上限）；每任务 ≥3 文件；T01 基础设施；依赖极浅。**v2.1 增量：T02 已交付需 +1h 返工；T04 吸收两阶段剪藏与后移配额（9h→12h）。**

### T01 源与栏目改造（P0，纯规则）
- **文件**：`pipeline/src/kaogong/sources.py`、`pipeline/config.json`、`pipeline/tests/test_sources.py`
- **内容**：§2.3 三字段 + §2.4 处置表 + `_column_ok` 三处提取器接入 + noiseTitle 追加「消费券」 + 一致性测试
- **依赖**：无
- **工时**：4h
- **验收**：`load_sources({})` 返回 11 源；四川在线配置含 `column_keep_re`，模拟 20 条 ggxw 标题（含遂宁 7 条/天天学习/新思想自习室/天府新视界）仅后 2 类通过；`config.json` 与 `DEFAULT_SOURCES` 源名集合相等（新测试）；现有测试全绿。

### T02 配额 + CAPS + Candidate.source_name（P0，纯规则）——已交付，v2.1 需 +1h 返工
- **文件**：`pipeline/src/kaogong/pipeline.py`、`pipeline/src/kaogong/models.py`、`pipeline/tests/test_pipeline.py`
- **已交付内容（保留）**：`Candidate.source_name` 回填（后移配额仍需分组键）；CAPS 新值常量；`QUOTA_OVERRIDES` 常量。
- **v2.1 返工内容（~1h）**：摘除 fetch 层 `pipeline.py:121` 的 `_quota_per_source(out)` 调用与 `:127-128` 的 CAPS/`_pick_top` 循环，替换为 `_preclip_ceiling(out, MAX_PRECLIP=48)`（§3.4）；`test_pipeline.py` 原 fetch 层配额断言改为「同源 >3 条可穿过 fetch 层 + MAX_PRECLIP 生效」。
- **依赖**：T01
- **工时**：4h（已交付）+ 1h 返工
- **验收**：fetch 层不再截断同源候选（同源 20 条全过）；`MAX_PRECLIP=48` 全局上限生效；`source_name` 回填不变；全量测试绿。

### T03 簇去重 + 分节重构（P1，纯规则）
- **文件**：`pipeline/src/kaogong/dedupe.py`、`pipeline/src/kaogong/build.py`、`pipeline/src/kaogong/digest.py`、`pipeline/tests/test_dedupe.py`、`pipeline/tests/test_build.py`
- **内容**：v1 §4 簇去重 + §6 分节（REGION_SECTIONS 删除、guangdong-policy→policy、SECTION_SLUG 清理、SLOT_SOURCE 更新含 essay 新来源描述）
- **依赖**：T01
- **工时**：4h
- **验收**：遂宁 7 条拆条聚合 1；分节序列 `["national","essay","policy"]`；大洋网/四川理论栏目候选出现在 essay 分节。

### T04 两阶段剪藏 + 密度门禁 + 后移配额 + AI 判据改写 + 宁缺勿滥（P0，语义核心）
- **文件**：新建 `pipeline/src/kaogong/density.py`、`pipeline/src/kaogong/pipeline.py`（**两阶段 clip_content 重构 + `_apply_quota_and_caps` + digest 重写 + 报告字段**）、`pipeline/src/kaogong/curation.py`（prompt 判据 + needsHuman + 删补剧 + sparse）、`pipeline/src/kaogong/article_ai.py`（aiFocus）、`content/schema/article.schema.json`（aiFocus 字段）、`pipeline/tests/test_density.py`（新建）、`pipeline/tests/test_pipeline.py`（两阶段/配额后移用例）、`pipeline/tests/test_curation.py`、`pipeline/tests/test_article_ai.py`
- **内容**：§3.3-3.4 两阶段剪藏 + 后移版 `_apply_quota_and_caps`（total_chars 降序）+ digest 重写 + §3.6 报告字段（candidatesRaw/densityRejected/quotaRejected）；§5 密度门禁（四判据+阈值，**用黄金样本校准值**）；§7.2 prompt 重写（7 进 8 出 + signals/needsHuman/focus 输出）；§7.3 aiFocus；§7.1 删补剧 + MIN_PICKS=0 + sparse
- **依赖**：T02 返工完成（fetch 层无配额后，两阶段结构才成立）
- **工时**：12h（v2 为 9h；+3h 来自两阶段剪藏重构、digest 重写、配额后移与报告字段）
- **验收**：黄金样本**全链路**回放——**8/8 IN 在「栏目→簇去重→密度→配额→CAPS」全链路存活（含配额，附录 B 硬断言）**（`test_gold_replay.py`：读 `_review/gold-2026-09-11.json` + `content/2026-09-11/article-*.json`，逐条跑规则门禁断言，见附录 B 矩阵）；金砖/大湾区/产业蝶变/溇港死于密度判据；火灾批示/海上数据集等最短 OUT 死于配额层（quotaRejected 落 report）；`density_low:*` 出现在 clipDetails；needsHuman 写入 report；最终 digest ~15 条、AI 分析 ≤16 次；无补剧；sparse 状态正确。

### T05 人审工作流 + 前端占位 + 端到端（P2）
- **文件**：`pipeline/src/kaogong/review/ui/index.html`、`pipeline/src/kaogong/review/server.py`（report-agent 判据同步）、`pipeline/src/kaogong/review_agent.py`（`_SYSTEM` 同步 7 进 8 出，`:21-35`）、`apps/web/src/pages/index.astro`、`apps/harmony/entry/src/main/ets/view/HomePage.ets`
- **内容**：§8.3 待人审过滤器/badge/预填理由；review-agent 判据同步；Web/端上 sparse 占位文案；§3.6 volume_errors 基线重置（上线日清 5 份窗口或 pivot 日打标）；用 2026-09-11 全量回放做端到端验收
- **依赖**：T03、T04
- **工时**：5h
- **验收**：工作台「待人审」过滤可见 1-3 条（回放日）；排除带预填理由；`/api/stats` 区分 sparse；基线重置后无 `below_half_baseline` 误报；端上/Web 精品空档日不报错。

**总工时：4+4(+1 返工)+4+12+5 = 30h ≈ 3.75 人日**（v2 为 26h；v2.1 增量来自 T02 返工 1h + 两阶段剪藏/配额后移/报告字段 3h）。

---

## 10. 待明确事项（需用户拍板）

| # | 事项 | 我的建议 | 状态 |
|---|---|---|---|
| ① | ~~nf/gdp 留砍~~ | 南方时评横琴 OUT（但标注理由疑似与麻风村错位）→ **降配保留 limit=3**；gdp 无样本 → **降配保留 limit=5** | 部分回答，维持建议 |
| ② | sparse 日首页是否上 | 显示占位文案 + 引导看历史 | 未变 |
| ③ | **AI 不可用时（额度耗尽）的默认行为** | 无 key → 程序兜底排序 + **全部标 needsHuman**（人审兜底，不硬判）；备选：全部拦下不进 picks | **新增**（今天额度刚耗尽，明天可能复现） |
| ④ | 本轮是否新增精品源 | 不加（闸门未上线先加水 = 往漏水的桶里加水） | 未变 |
| ⑤ | tier/栏目正则是否要后台可切换 | 纯代码常量（后台切换暂不需要） | 未变 |
| ⑥ | **栏目白名单初始清单** | 首批只放「新思想自习室 / 天府新视界」；「天天学习」暂不放（本次因视频稿 OUT，待密度门禁稳定后可试放） | **新增** |
| ⑦ | **南方时评横琴标注确认** | 该条 verdict=out 但理由是「和上面的一篇是一样的，麻风村里的点灯人」——理由与标题错位，疑似复制失误。若实为误标，nf 精品率需重估 | **新增（一句话即可确认）** |
| ⑧ | 地方保留栏目文章进 essay 还是保留精简地方分节 | 进 essay（申论精读语义自洽：理论栏目+结构范文）；若用户想保留「广东观察」视角可改回，前端动态渲染两种都支持 | **新增** |
| ⑨ | **配额淘汰条目是否可救**：后移配额会把「密度过关但非同源最长」的条目（含部分发布会类）挡在 digest 外，与「发布会类交人审」的哲学有张力 | 先只落 report `quotaRejected` 供工作台展示（T04），观察一周流量后决定是否加「提升进 digest」按钮（同 §8.3-5 模式）；MAX_PRECLIP/配额值可调 | **新增（v2.1）** |

---

## 11. 风险与已知代价（v2.1 更新）

| 风险 | 等级 | 缓解 |
|---|---|---|
| **栏目白名单漏杀**：新思想自习室/天府新视界某天发垃圾 | 中 | 配额≤3 + AI 评级 + 密度门禁三重兜底；白名单是**必要条件不是充分条件** |
| **后移配额的残余误杀**：total_chars 只是弱价值代理，同源出现 >配额条更长候选时短精品（如 AI 治理 800 字 IN）仍可能被截 | 中 | 黄金样本日各源过密度净流量 ≤ 配额（sichuan 2、dayoo 3、news.cn 5>3 但两条 IN 恰为最长两条），正常日配额不绑定；quotaRejected 落 report 可追溯可救（§10-⑨）；AI 层兜底 |
| **MAX_PRECLIP 盲截**：单源刷屏（>48）时安全阀按列表序截断，仍是值盲 | 低 | 正常日 ~22 远低于 48，仅异常日触发；report `candidatesRaw` 监控，触发即报警（触发 = 源异常，本就该查） |
| **volume_errors 基线失配**：pivot 后 candidates ~15 vs 历史中位 28-59，`below_half_baseline` 每日误报 | 确定 | 上线日重置基线（清 5 份窗口旧报告或 pivot 日打标跳过），T05 验收项（§3.6） |
| **两阶段剪藏重构引入回归**：clip/analyze 从交错改两轮，时序与报告字段都变 | 中 | T04 含 test_pipeline 两阶段用例 + 全链路回放测试；结构反而更简单（每轮单一职责） |
| **G1/G4 阈值误杀短精品**（AI 治理仅 ~800 字；G4 上限 1500 字同理） | 中 | 阈值已用黄金样本校准（§5.2 三条红线）；`test_gold_replay.py` 固化为回归测试；阈值全部常量化可调 |
| **G4 依赖分析词表**，表外分析词可能误杀 | 中 | 词表常量化 + 回放测试监控；G4 三条件合取（零分析词 ∧ 段数≥6 ∧ 字数<1500）已是保守设计，宁可漏杀（AI 层再判）不可误杀 |
| **needsHuman 依赖用户每天 3-6 分钟**，长期疲劳后积压 | 中 | 流量已压到 1-3 条/天；工作台一键排除；默认行为本就「不出 picks」，积压无额外风险 |
| **assign_grades prompt 变长导致评级质量漂移** | 低 | 7/8 判据全部来自用户原话语料，语义锚定强；`test_curation.py` 补 signals/needsHuman 解析用例；上线后前 3 天人工抽检 reason 字段 |
| **AI 评级误杀 C 级**（把好文判 C） | 中 | reason 全量落 report 可回溯；工作台 force-include 可救回；sparse 状态显式暴露空档而非静默 |
| **人民网时政 0/5 精品率样本偏差**（单日样本） | 中 | 保留该源 + 配额严限；连续 7 天回放观察后再决定去留（数据说话，不凭一日拍板） |
| 精品日可能 0-1 篇 → sparse | 设计意图 | §7.1 机制化，前端占位 |
| `test_build.py:21` 等断言需改 | 确定工作量 | T03 清单已列 |
| `article.schema.json` 新增 aiFocus | 低 | 可选字段（非 required），历史内容零迁移 |

**已知代价（明确接受）**：
1. 遂宁式地方通稿、地方丰收节/年画村类内容**彻底消失**（用户已拍板「地方的就不要了」）。
2. 人民网时政的短讯式领导人动态**基本消失**（用户已用金砖/丁薛祥/王小洪三例表明立场）；有实质内容的领导人讲话（如 AI 治理）仍保留。
3. 每天 3-6 分钟人审成为**固定成本**（发布会/调研类的终审位，用户明言「机器把持不好」）。
4. 首页可能长期只有 2-4 篇精选——这是「精品」的定义，不是缺陷。

---

## 附录 A：模块影响面（v2.1）

```mermaid
graph LR
    subgraph 规则闸门（零AI成本，按信息充分度排序）
        S[sources.py<br/>tier + column_keep/drop_re<br/>标题层]
        PC[pipeline.py<br/>MAX_PRECLIP 安全阀]
        D[dedupe.py<br/>cluster_dedupe]
        DN[density.py 新增<br/>density_gate 四判据<br/>正文层·两阶段剪藏 pass-1 后]
        Q[pipeline.py<br/>_apply_quota_and_caps<br/>正文层·密度之后<br/>total_chars 降序]
    end
    subgraph AI语义层
        CU[curation.py<br/>7进8出 prompt<br/>needsHuman/focus]
        AA[article_ai.py<br/>aiFocus 段落定位<br/>pass-2 仅存活者]
    end
    subgraph 人审与呈现
        RW[review/ui/index.html<br/>待人审队列]
        WEB[index.astro sparse占位]
        HM[HomePage.ets sparse占位]
    end
    S --> PC --> D --> DN --> Q
    Q --> CU
    CU --> AA
    CU --> RW
    CU --> WEB
    CU --> HM
```

## 附录 B：黄金样本回放矩阵（T04 验收基准，v2.1 全链路口径）

> **v2.1 修正**：已交付的 fetch 层配额曾按列表序误杀 3 篇 IN（政绩观 news.cn 列表#5、塞上江南 #6、琴澳 dayoo #4）。配额后移至密度之后并按 total_chars 降序后，3 篇全部复活。下表「规则闸门预期」列 = **栏目 → 簇去重 → 密度 → 配额/CAPS 全链路**的预期归属。

| id | 标题（截断） | 用户判定 | 规则闸门预期（全链路） | 归属层 |
|---|---|---|---|---|
| dd07743aa5 | AI治理丨新思想自习室 | IN | 栏目白名单✓ 密度✓ 配额✓ | AI 评级 S（金句密度） |
| 5fe7d58ab7 | 追星丨天府新视界 | IN | 栏目白名单✓ 密度✓ 配额✓ | AI 评级 A（社会舆情） |
| 828772806c | 黄坤明到广州调研 | IN | 密度✓ 配额✓（dayoo 过密度 3≤3） | **needsHuman→人审保**（发布会类） |
| 6fc7bb2b94 | 琴澳五载同心同行 | IN | 密度✓ **配额✓（v2 fetch 层曾误杀，后移后存活）** | AI 评级 A/B（结构价值） |
| 1428152df1 | 正确政绩观…军队现代化 | IN | 密度✓ **配额✓（news.cn 最长；v2 fetch 层曾误杀）** | AI 评级 S（常考性） |
| ded9ac3b03 | 塞上江南 | IN | 密度✓ **配额✓（news.cn 第二长；v2 fetch 层曾误杀）** | AI 评级 B + **aiFocus 尾段** |
| 42b52e2f23 | 全力救治善后 | IN | 密度✓（"推动"保护）配额✓ | AI 评级 A（分省做法） |
| 4851b2d233 | 年轻人不愿意学医了吗 | IN | 密度✓（分析词保护）配额✓ | AI 评级 A（分析深度） |
| 0bd839c1d9 | 习近平将赴印度出席金砖 | OUT | **G1 杀**（130字） | — |
| 333b9d6044 | 大湾区进出口值增长 | OUT | **G2 杀**（数字0.15/0分析词） | — |
| 2a713d887b | 看产业蝶变 | OUT | **G4 杀**（12段/700字/0分析词） | — |
| ec808afa83 | 千年溇港 | OUT | **G3 杀**（诗行短段）或 video_no_text | — |
| bb04d1699b 等 17 条 | 遂宁×6/强相关×11 | OUT | **栏目白名单杀** | — |
| ab75a2de64 | 天天学习（视频） | OUT | **栏目白名单杀**（不在白名单） | — |
| 83532f1e7b | 文旅消费券 | OUT | **column_drop_re 杀** | — |
| 50fb91dd80 等 4 条 | 丁薛祥APEC/王小洪/谌贻琴/火灾批示 | OUT | 过密度 4 条 → **配额 3 淘汰最短（预期火灾批示）** | 余 3 条 **AI 评级 C**（空壳短讯/形式性/工作报告） |
| 5686e3b171 | 知识产权十大案例 | OUT | **配额层（news.cn，去留回放实测）** | 若存活：**needsHuman→人审杀**（发布会介绍） |
| fbb4608760 | APEC 工商领导人峰会 | OUT | **配额层（news.cn，去留回放实测）** | 若存活：**needsHuman→人审杀**（发布会通稿） |
| ef44cf6075 | 海上保护区数据集 | OUT | **配额层淘汰（news.cn 最短预期）** | —（若存活则 AI 评级 C，粒度太细） |
| 4a47f6951f | 麻风村里的点灯人 | OUT | 规则放行（byt 配额 4 未绑定） | AI 评级 C（人文纪实无政策） |
| 9c52f627e4 | 3万澳门人选择横琴 | OUT(⚠️疑似错标) | 规则放行（nf 配额未绑定） | 待 §10-⑦ 确认后归层 |

**全链路断言（v2.1 新增，硬性）**：**8/8 IN 在「栏目 → 簇去重 → 密度 → 配额 → CAPS → AI」全链路含配额存活**——含曾被 fetch 层配额误杀的政绩观/塞上江南/琴澳。`test_gold_replay.py` 逐条断言。

**规则闸门（栏目+密度+配额）杀 ~25-27/32 · AI 评级杀 ~3-5 · needsHuman 人审杀 ~1-2 · IN 全链路存活 8/8 · 最终 digest ~15 条 · AI 分析 ≤16 次** —— 这就是本方案的全部验收基准（精确归属以 T04 全量回放实测为准）。

## 附录 C：测试影响清单（v2.1）

| 测试文件 | 影响 | 处理 |
|---|---|---|
| `test_sources.py` | 新增 tier/column 过滤、config 一致性用例 | T01 |
| `test_pipeline.py` | v2.1：fetch 层配额断言改为 MAX_PRECLIP 口径（T02 返工）；新增两阶段剪藏 + `_apply_quota_and_caps` 用例（T04） | T02/T04 |
| `test_dedupe.py` | 新增 cluster_dedupe 用例 | T03 |
| `test_build.py:21/:17` | 分节断言改（policy/essay 新来源） | T03 |
| **`test_density.py`（新建）** | 四判据 × 黄金样本校准值 | T04 |
| **`test_gold_replay.py`（新建）** | 40 条回放矩阵（附录 B，全链路含配额断言） | T04 |
| `test_curation.py` | 补剧删除、sparse、signals/needsHuman/focus 解析 | T04 |
| `test_article_ai.py` | aiFocus 字段校验 | T04 |
| `test_content_schema.py` | article.schema 增 aiFocus（可选字段） | T04 |
| 其余 190+ 用例 | 不受影响 | — |

**底线：T01-T05 完成后全量测试绿，且黄金样本全链路回放 8/8 IN 存活（含配额）、≥22/32 OUT 规则击杀（预期 25-27）。**
