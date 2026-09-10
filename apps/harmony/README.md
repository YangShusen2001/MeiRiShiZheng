# apps/harmony — 考公云 HarmonyOS 原生客户端

纯原生 ArkTS 客户端（**不是 WebView 壳**），直连云端已部署服务，复用现有内容层与用户数据 API。
决策依据见 `docs/adr/0009-harmonyos-native-client.md`，任务见 `docs/tasks/0027-harmonyos-native-client.md`。

## 云端端点（开发期直连，不在本地起服务）

| 用途 | 地址 | 来源 |
|---|---|---|
| 内容 | `https://www.meirishizheng.cn` | Cloudflare Pages；`/content/*` 由 `apps/web/scripts/build-content-api.mjs` 构建期生成 |
| 用户数据 | `https://api.meirishizheng.cn` | Cloudflare Worker（Hono + Drizzle + D1） |

端点集中定义在 `entry/src/main/ets/config/Endpoints.ets`，改地址只改那一处。

> ⚠️ **前置条件**：`/content/*` 是 Phase 0 新增的分发层，**需要先部署一次 Pages 构建**才会在线上可用。
> 未部署时首页会显示「内容通道尚未部署到线上（404）」并给出重试按钮，不会白屏。
> 部署：`pnpm --filter @kaogong/web build` → `npx wrangler pages deploy dist --project-name kaogong-web`。

## 打开与构建

用 DevEco Studio 打开 **本目录**（`apps/harmony`），等待 Sync 完成后：

```sh
# 命令行构建（工程根目录下）
hvigorw assembleHap --mode module -p product=default --no-daemon

# 安装到真机（nova 14 Pro）
hdc install -r entry/build/default/outputs/default/entry-default-signed.hap
hdc shell aa start -a EntryAbility -b cn.meirishizheng.kaogong
```

> 真机安装需要签名。DevEco → File → Project Structure → Signing Configs → 勾选 **Automatically generate signature**（首次需登录华为开发者账号）。

### 若 Sync 报错，需要校对的三处

本工程骨架是手写的，以下字段依赖本机 SDK，DevEco 版本不同可能需调整：

1. `build-profile.json5` → `products[].compatibleSdkVersion`
   当前为 `"5.0.5(17)"`（兼容面广）。若本机未安装该 SDK，改为已装版本（如 `"6.0.0(20)"`）。
   最快的对照办法：DevEco 新建一个空工程，抄它的 `compatibleSdkVersion`。
2. `build-profile.json5` / `hvigor/hvigor-config.json5` → `modelVersion`（当前 `5.0.0`）。
3. `entry/src/main/module.json5` 的 `deviceTypes` 当前只有 `phone`。

## 目录结构

```
apps/harmony/
├── AppScope/                        应用级配置与图标
├── entry/                           主模块（entry HAP）
│   └── src/main/
│       ├── module.json5             权限（INTERNET）、Ability 注册
│       ├── resources/               字符串 / 颜色 / 图标 / main_pages
│       └── ets/
│           ├── theme/Tokens.ets         设计令牌（视觉唯一事实源）
│           ├── config/Endpoints.ets     云端端点集中配置
│           ├── model/Content.ets        领域模型（对齐 packages/contracts）
│           ├── service/Http.ets         JSON HTTP 客户端
│           ├── service/ContentService.ets  取数入口 + aiStatus 门控
│           ├── view/ReaderSegments.ets  标注切片（纯函数）
│           ├── view/HomePage.ets        首页：日期切换 + 今日速览 + 日报分栏
│           ├── view/ReadPage.ets        阅读页：分段 + 四色标注 + 标注清单
│           ├── pages/Index.ets          Navigation 容器
│           └── entryability/EntryAbility.ets
└── ...
```

## 设计规范

**视觉的唯一事实源是 `entry/src/main/ets/theme/Tokens.ets`。**
页面里不允许出现硬编码色值、字号、间距；新增视觉需求先在 Tokens 加令牌。

调性：暖米底 `#F5F1E8` + 深绿 `#4C795B` 的护眼阅读配色（**有意不跟随 Web 的冷蓝体系**，
理由与完整令牌表、**WCAG 对比度实算审计**、交互清单见 [`DESIGN.md`](DESIGN.md)）。

自检（期望输出 `硬编码色值: 0 ✓`）：

```bash
cd apps/harmony/entry/src/main/ets
python -c "
import os,re
bad=[]
for dp,_,fs in os.walk('.'):
    for f in fs:
        if not f.endswith('.ets'): continue
        p=os.path.join(dp,f)
        if p.endswith('Tokens.ets'): continue
        for m in re.finditer(r'#[0-9A-Fa-f]{6,8}', open(p,encoding='utf-8').read()):
            bad.append(f'{p}: {m.group(0)}')
print('硬编码色值:', len(bad) or '0 ✓')
"
```

## 分层纪律

- **model/** 字段必须与 `packages/contracts/src/content.ts` 一一对应，不得另立字段；
  契约变更先改 contracts，再同步这里。
- **service/ContentService** 是唯一取数入口，并在这里收口渲染门控：
  `aiSummary` / `aiAnnotations` **仅在 `aiStatus === 'ok'` 时可用**（对齐 Web 端
  `apps/web/src/pages/read/[id].astro:10-11`）。页面不得自行判断。
- 不使用已废弃的 `@ohos.router`，统一用 `Navigation` + `NavPathStack`。

## 当前状态（Phase 1）

已完成：

- [x] 工程骨架（DevEco 可直接打开）
- [x] 云端端点配置、HTTP 层、内容服务 + 门控
- [x] 首页：今日速览（一句话 + 关键词）+ 日报分栏列表，点击进阅读页
- [x] 阅读页：原文分段 + 考点/观点/术语/数字指标四色标注，点击看释义

未包含（按 Phase 1 范围明确不做）：

- [ ] 登录 / 收藏 / 划线 / 每日一练 / 错题本 / AI 解析
- [ ] 离线缓存、桌面卡片、实况窗、推送
- [ ] 平板与折叠屏适配、横屏

## 已知风险

1. `Span.textBackgroundStyle` 用于内联高亮底色。若本机 SDK 不支持，删除该行即降级为
   仅文字颜色/字重区分（`view/ReadPage.ets` 中已就地注释标记）。
2. `Span.onClick` 用于点击术语看释义；同版本差异。
3. `Text() { ForEach(...) { Span(...) } }` 用于动态分段高亮。若编译器不接受
   `ForEach` 作为 `Text` 的子节点，改用 `MutableStyledString` + `Text(styledString)`。
4. 内容为**部署时快照**：线上内容 = 最近一次 Pages 部署。更新内容需重新构建部署。

## 契约一致性门禁

`apps/harmony` 不是 pnpm 包，不参与 `pnpm -r test`。为避免 ArkTS 模型与
`packages/contracts` 静默漂移（曾发生：contracts 把 `ContentManifestDay.articleIds`
改为 `articles`，鸿蒙模型未同步，直到编译期才报 `arkts-no-any-unknown`），
一致性检查放在 **`apps/web/test/harmony-contract-parity.test.ts`**，随 `pnpm -r test` 执行。

规则：客户端消费的接口（`ContentManifest` / `ContentManifestDay` / `ContentManifestArticle` /
`TodaySummary` / `DigestItem` / `DigestSection` / `DailyDigest` / `AiAnnotation`）
必须与 contracts **逐字段与顺序完全一致**；`ClippedArticle` 允许为有意子集，
但不得出现 contracts 之外的字段。

**改契约时**：先改 `packages/contracts/src/content.ts`，再同步本工程的
`entry/src/main/ets/model/Content.ets`，然后跑 `pnpm --filter @kaogong/web test` 验证。
