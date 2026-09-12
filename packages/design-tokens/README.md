# @kaogong/design-tokens

考公云统一设计令牌 v3。**`tokens.json` 是三端唯一的数值源**，其余产物都是生成物。

规范正文（值与理由）：`docs/design/design-system-v3.md`
架构取舍：`docs/adr/0010-design-token-pipeline.md`

## 改一个颜色要做什么

```bash
# 1. 改 tokens.json
# 2. 重跑生成器（产物必须一起提交）
pnpm --filter @kaogong/design-tokens generate
# 3. 审计（会拦截「改了源没重跑」、WCAG 不达标、色相环撞色）
python scripts/audit-tokens.py
```

## 文件

| 文件 | 角色 |
|---|---|
| `tokens.json` | 唯一数值源。含审计策略（路径、色相环约束、Tabler 覆盖键清单） |
| `generate.mjs` | 生成两份 CSS（Web / 后台）。`--check` 只校验不写盘，用于 CI |
| `wcag.mjs` | WCAG 2.1 相对亮度 / 对比度 / 色相距离（**JS 侧**） |
| `test-vectors.json` | 对比度测试向量 + 阈值 —— JS 与 Python 共用的契约 |
| `vectors.mjs` | 跑向量的 CLI（`pnpm -r test` 会调它） |

产物（生成，勿手改）：

- `apps/web/src/styles/tokens.generated.css` —— Web。⚠️ **尚未接入 `global.css`**，见 ADR 后果 ①。
- `pipeline/src/kaogong/review/ui/tokens.css` —— 后台，经 `GET /review/tokens.css` 提供，必须置于 Tabler CDN 之后。

## 两条容易踩的规则

1. **产物入库**：CSS 里带 `SOURCE_SHA256` 指纹。改了 `tokens.json` 却不重跑生成器 → 审计直接失败。这是刻意的。
2. **对比度公式是双实现**：`wcag.mjs`（浏览器/彩蛋页）与 `scripts/audit-tokens.py`（CI）必须给出同一组比值。改任何一侧，都跑 `pnpm -r test` 和 `python scripts/audit-tokens.py` 两头验证，否则会出现「网页显示 7.70、脚本说 7.68」这类最难查的不一致。

## 鸿蒙为什么不生成

`apps/harmony/.../theme/Tokens.ets` 手写，只受审计约束，**不做生成覆盖**。它承载不可再生的踩坑注释（`fontScale` 的 ArkUI 依赖追踪陷阱、`MUT` 仅限白卡、"深色不做反色"的理由）。审计会逐项比对色值并报告漂移（当前 23/36 项待对齐，属规范 §8 第 3 步的收口范围）。
