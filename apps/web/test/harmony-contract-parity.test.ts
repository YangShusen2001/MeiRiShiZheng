// 契约一致性门禁：鸿蒙端（ArkTS）的领域模型必须与 packages/contracts 保持同步。
//
// 为什么放在 web 测试套件里：`apps/harmony` 不是 pnpm 包，不参与 `pnpm -r test`；
// 而契约漂移的代价很高（曾发生：contracts 把 ContentManifestDay.articleIds 改成 articles，
// 鸿蒙模型未同步 → 编译期才暴露 arkts-no-any-unknown）。放在这里才能真正进 CI 门禁。
//
// 规则：
// - 客户端消费的接口 → 与 contracts **逐字段完全一致**；
// - `ClippedArticle` → 允许是有意子集，但不允许出现 contracts 里没有的字段。
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const REPO_ROOT = fileURLToPath(new URL("../../..", import.meta.url));
const CONTRACTS = join(REPO_ROOT, "packages/contracts/src/content.ts");
const HARMONY_MODEL = join(REPO_ROOT, "apps/harmony/entry/src/main/ets/model/Content.ets");

/** 取出某个 `export interface X { ... }` 的字段名（顺序保持声明顺序）。 */
function interfaceFields(source: string, name: string): string[] | null {
  const match = new RegExp(`export interface ${name}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(source);
  if (!match?.[1]) return null;
  const fieldPattern = /^\s*([A-Za-z_][A-Za-z0-9_]*)\??\s*:/gm;
  return [...match[1].matchAll(fieldPattern)].map((m) => m[1] as string);
}

/** 客户端消费的接口：必须与 contracts 完全一致。 */
const EXACT = [
  "ContentManifest",
  "ContentManifestDay",
  "ContentManifestArticle",
  "ContentArchiveScale",
  "ContentArchiveItem",
  "ContentArchiveMonth",
  "ContentArchiveMonthRow",
  "ContentArchiveTotals",
  "ContentArchiveIndex",
  "TodaySummary",
  "DigestItem",
  "DigestSection",
  "DailyDigest",
  "AiAnnotation",
];

/** 允许为有意子集的接口（不得多出 contracts 没有的字段）。 */
const SUBSET_ALLOWED = ["ClippedArticle"];

const harmonyExists = existsSync(HARMONY_MODEL);
const cases: string[] = [...EXACT, ...SUBSET_ALLOWED];

describe("鸿蒙端模型与 contracts 的一致性", () => {
  it.skipIf(!harmonyExists)("contracts 与 ArkTS 模型都能被解析", () => {
    const contracts = readFileSync(CONTRACTS, "utf-8");
    const harmony = readFileSync(HARMONY_MODEL, "utf-8");
    for (const name of cases) {
      expect(interfaceFields(contracts, name), `contracts 缺少 ${name}`).not.toBeNull();
      expect(interfaceFields(harmony, name), `ArkTS 模型缺少 ${name}`).not.toBeNull();
    }
  });

  it.skipIf(!harmonyExists)("客户端消费的接口逐字段一致（字段名与顺序）", () => {
    const contracts = readFileSync(CONTRACTS, "utf-8");
    const harmony = readFileSync(HARMONY_MODEL, "utf-8");
    for (const name of EXACT) {
      expect(interfaceFields(harmony, name), `${name} 字段与 contracts 不一致`).toEqual(
        interfaceFields(contracts, name),
      );
    }
  });

  it.skipIf(!harmonyExists)("子集接口不得引入 contracts 之外的字段", () => {
    const contracts = readFileSync(CONTRACTS, "utf-8");
    const harmony = readFileSync(HARMONY_MODEL, "utf-8");
    for (const name of SUBSET_ALLOWED) {
      const contractFields = interfaceFields(contracts, name) ?? [];
      const harmonyFields = interfaceFields(harmony, name) ?? [];
      const extra = harmonyFields.filter((field) => !contractFields.includes(field));
      expect(extra, `${name} 出现了 contracts 未定义的字段`).toEqual([]);
    }
  });
});
