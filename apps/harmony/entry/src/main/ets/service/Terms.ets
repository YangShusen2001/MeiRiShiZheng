import { fileIo as fs } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Settings } from './Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongTerms';
const FILE: string = 'terms.json';
/** 收藏上限。够了就够——收藏夹不是仓库，超出时淘汰最旧的。 */
const MAX_TERMS: number = 200;

/** 一条收藏的术语。 */
export interface SavedTerm {
  /** 术语原文（也算去重键）。 */
  text: string;
  /** 出处文章 id；空串表示没有出处。 */
  articleId: string;
  /** 手动备注。 */
  note: string;
  /** 当时拿到的 AI 解析；空串表示收藏时还没解析。 */
  explanation: string;
  /** 收藏时间（ms）。 */
  savedAt: number;
}

/**
 * 术语收藏（本地）。
 *
 * ## 为什么先做本地
 * 端上此前**完全没有收藏能力**（只有分享），"收藏页 + 术语解析"缺的是前提而不是页面。
 * 先落地本地闭环：离线可用、不依赖登录、不涉及配额。
 * 服务端已有 `/api/highlights`（契约字段与"收藏一个术语"天然吻合：
 * articleId + text + 段落/偏移 + explanation），跨端同步是下一步，
 * 届时把本地条目上行即可——**不返工**。
 *
 * ## 持久化约定（ArkTS 限制下）
 * 用「数组持久化 + Map 查询」：ArkTS 禁止索引签名与下标访问属性，
 * 不能写 `{[text]: SavedTerm}` / `map[key]`。Map 也不能直接 JSON.stringify。
 */
export class Terms {
  /** 全部收藏，按收藏时间倒序（新的在前）。 */
  static list(): SavedTerm[] {
    const path: string | null = Terms.path();
    if (path === null) {
      return [];
    }
    try {
      if (!fs.accessSync(path)) {
        return [];
      }
      const parsed: SavedTerm[] = JSON.parse(fs.readTextSync(path)) as SavedTerm[];
      return parsed.sort((left: SavedTerm, right: SavedTerm) => right.savedAt - left.savedAt);
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '读取收藏失败（视为空）：%{public}s', cause.message);
      return [];
    }
  }

  static has(text: string): boolean {
    for (const item of Terms.list()) {
      if (item.text === text) {
        return true;
      }
    }
    return false;
  }

  /** 收藏一条；已存在则更新解析与备注，不重复入库。 */
  static save(term: SavedTerm): void {
    const list: SavedTerm[] = Terms.list();
    let replaced: boolean = false;
    for (const item of list) {
      if (item.text === term.text) {
        item.explanation = term.explanation.length > 0 ? term.explanation : item.explanation;
        item.note = term.note.length > 0 ? term.note : item.note;
        item.articleId = term.articleId.length > 0 ? term.articleId : item.articleId;
        item.savedAt = term.savedAt;
        replaced = true;
        break;
      }
    }
    if (!replaced) {
      list.push(term);
    }
    // 超出上限淘汰最旧的
    list.sort((left: SavedTerm, right: SavedTerm) => right.savedAt - left.savedAt);
    Terms.write(list.slice(0, MAX_TERMS));
  }

  static remove(text: string): void {
    const kept: SavedTerm[] = [];
    for (const item of Terms.list()) {
      if (item.text !== text) {
        kept.push(item);
      }
    }
    Terms.write(kept);
  }

  private static write(list: SavedTerm[]): void {
    const path: string | null = Terms.path();
    if (path === null) {
      return;
    }
    try {
      const file: fs.File = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      try {
        fs.writeSync(file.fd, JSON.stringify(list));
      } finally {
        fs.closeSync(file);
      }
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '写入收藏失败：%{public}s', cause.message);
    }
  }

  private static path(): string | null {
    const context = Settings.context();
    if (context === null) {
      return null;
    }
    return `${context.filesDir}/${FILE}`;
  }
}
