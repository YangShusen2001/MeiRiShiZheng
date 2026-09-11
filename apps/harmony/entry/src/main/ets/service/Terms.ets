import { fileIo as fs } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Endpoints } from '../config/Endpoints';
import { HttpClient } from './Http';
import { Settings } from './Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongTerms';
const FILE: string = 'terms.json';
/** 收藏上限。够了就够——收藏夹不是仓库，超出时淘汰最旧的。 */
const MAX_TERMS: number = 200;
/** 服务端 `termText` 上限（契约 max 200）。 */
const TERM_TEXT_LIMIT: number = 200;

/** 上行请求体。必须显式声明接口：ArkTS 禁止无类型对象字面量（`Record` 不算接口）。 */
interface FavoritePayload {
  url: string;
  title: string;
  kind: string;
  termText: string;
  termExplanation: string;
  articleId: string;
  note: string;
}

interface FavoriteEnvelope {
  ok: boolean;
}

/** 同步结果。 */
export interface TermsSyncResult {
  ok: boolean;
  /** 成功上行条数。 */
  uploaded: number;
  /** 跳过条数（超长等）。 */
  skipped: number;
  /** 失败说明；成功为空串。 */
  message: string;
}

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

  /**
   * 上行到服务端（跨端同步）。
   *
   * ## 为什么可以无脑重试
   * 服务端对术语按 `(owner, url, termText)` **幂等**：重复上行只会返回已存在的那条。
   * 所以中断后重试是安全的——文案里也如实这么告诉用户，而不是让他"小心别重复点"。
   *
   * ## 超长的跳过而不是截断
   * 服务端 `termText` 上限 200 字。截断会改变术语本身（那正是这条内容的意义），
   * 所以计入 skipped 并如实报出来。
   *
   * ## 上行过去有什么用
   * 网页端本来就有收藏页（`/favorites`），所以同步后**在网页上就能看到这些术语**
   * ——这才是"跨端"的实际收益，不是把数据搬到另一个看不见的地方。
   */
  static async sync(): Promise<TermsSyncResult> {
    const list: SavedTerm[] = Terms.list();
    if (list.length === 0) {
      return { ok: true, uploaded: 0, skipped: 0, message: '' };
    }
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-Device-Id': Settings.deviceId(),
    };
    let uploaded: number = 0;
    let skipped: number = 0;
    for (const item of list) {
      const text: string = item.text.trim();
      if (text.length === 0 || text.length > TERM_TEXT_LIMIT) {
        skipped += 1;
        continue;
      }
      const payload: FavoritePayload = {
        url: item.articleId.length > 0
          ? `${Endpoints.CONTENT_BASE}/read/${item.articleId}`
          : Endpoints.CONTENT_BASE,
        title: text,
        kind: 'term',
        termText: text,
        termExplanation: item.explanation,
        articleId: item.articleId,
        note: item.note,
      };
      try {
        await HttpClient.postJson<FavoriteEnvelope>(
          Endpoints.favoritesUrl(), JSON.stringify(payload), headers);
        uploaded += 1;
      } catch (err) {
        const cause: Error = err as Error;
        return {
          ok: false,
          uploaded: uploaded,
          skipped: skipped,
          message: `上行中断：${cause.message}（已成功 ${uploaded} 条；服务端按术语去重，可直接重试）`,
        };
      }
    }
    return { ok: true, uploaded: uploaded, skipped: skipped, message: '' };
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
