import { ContentArchiveItem, ContentArchiveMonthRow } from '../model/Content';

/**
 * 政策档案分级取值。
 *
 * ⚠️ 为什么是常量类而不是字面量联合类型：ArkTS **不支持字面量类型**
 * （迁移指南规则 `arkts-no-as-const`：「ArkTS 不支持 as const 断言和字面量类型」）。
 * contracts 里写的是 `"高" | "中" | "低"`，到了 ArkTS 只能退化成 `string`——
 * 于是用这个常量类把取值收口，页面里不得出现裸的 '高' / '中' / '低'。
 *
 * 取值必须与 `packages/contracts/src/content.ts` 的 `ContentArchiveImportance` 一致；
 * 构建期门禁会拒绝未知分级（见 `build-content-api.mjs` 的自校验）。
 */
export class ArchiveTier {
  /** 核心考点：建议优先通读。 */
  static readonly CORE: string = '高';
  static readonly MEDIUM: string = '中';
  static readonly LOW: string = '低';
}

/**
 * 政策档案的纯逻辑（分组 / 标签 / 计数）。
 *
 * 单独成文件而不是写进页面：这些规则**每个端都必须一致**
 * （Web 端同一套在 `apps/web/src/components/PolicyArchive.astro`），
 * 散在页面里就没法单独核对。
 */
export class Archive {
  static isCore(item: ContentArchiveItem): boolean {
    return item.importance === ArchiveTier.CORE;
  }

  /** 核心考点（importance=高）。 */
  static coreOf(items: ContentArchiveItem[]): ContentArchiveItem[] {
    return items.filter((it: ContentArchiveItem) => Archive.isCore(it));
  }

  /** 了解 · 细则（中 + 低）。 */
  static restOf(items: ContentArchiveItem[]): ContentArchiveItem[] {
    return items.filter((it: ContentArchiveItem) => !Archive.isCore(it));
  }

  /**
   * 关键数字整行文案；没有可量化指标时返回空串（调用方据此条件渲染，不补空行）。
   *
   * 为什么不写在页面里：`figures` 是可选字段（2026-09-15 之前的档案没有），
   * ArkTS 对 `item.figures !== undefined` 之后的属性收窄不可靠；
   * 可选值的判空统一收在这里，页面只判断"整行文案是否为空"。
   */
  static figuresLine(item: ContentArchiveItem): string {
    const raw: string | undefined = item.figures;
    if (raw === undefined || raw.length === 0) {
      return '';
    }
    return `关键数字：${raw}`;
  }

  /**
   * 某月「了解 · 细则」份数。
   * 索引行刻意不带 medium / low（见 contracts 的 `ContentArchiveMonthRow`）——
   * 分级只有三档且构建期拒绝未知分级，所以 `count - high` 恒成立。
   */
  static restCount(row: ContentArchiveMonthRow): number {
    return row.count - row.high;
  }

  /** "2026-09" → "2026 年 9 月"（月份去前导零）。 */
  static monthLabel(month: string): string {
    if (month.length !== 7) {
      return month;
    }
    return `${month.substring(0, 4)} 年 ${Archive.monthNumber(month)} 月`;
  }

  /** "2026-09" → "9 月"（月份条上的胶囊标签）。 */
  static monthShort(month: string): string {
    return `${Archive.monthNumber(month)} 月`;
  }

  /** "2026-09" → "2026"。 */
  static yearOf(month: string): string {
    return month.length === 7 ? month.substring(0, 4) : month;
  }

  /** "2026-09-11" → "09-11"（细则行左侧的日期，省掉重复的年份）。 */
  static dayOf(date: string): string {
    return date.length === 10 ? date.substring(5) : date;
  }

  /**
   * 月份去前导零。
   * 不用 Number()/parseInt：只是去掉一个 '0'，字符串操作足够且没有解析分支。
   */
  private static monthNumber(month: string): string {
    if (month.length !== 7) {
      return month;
    }
    const raw: string = month.substring(5, 7);
    return raw.startsWith('0') ? raw.substring(1) : raw;
  }
}
