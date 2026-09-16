import { Endpoints } from '../config/Endpoints';
import {
  AiAnnotation,
  ClippedArticle,
  ContentArchiveIndex,
  ContentArchiveMonth,
  ContentManifest,
  DailyDigest,
  TodaySummary,
} from '../model/Content';
import { Cache, CacheEntry } from './Cache';
import { HttpClient } from './Http';

/**
 * 取数结果。
 * `cached = true` 表示网络不可用、数据来自本地缓存——页面必须**如实告知用户**
 * （显示「离线内容」），否则用户会以为看到的是最新内容。
 */
export interface Loaded<T> {
  data: T;
  /** true = 用的是本地缓存（网络失败兜底）。 */
  cached: boolean;
  /** 缓存写入时间（ms）；非缓存路径为 0。 */
  savedAt: number;
}

/**
 * 内容服务：原生端唯一的取数入口。
 *
 * 四件事在这里收口：
 * 1. **端点拼装**——页面不碰 URL；
 * 2. **离线缓存**——先网络、失败回落本地缓存，成功则顺手写缓存；
 * 3. **冷启动秒开**——提供**同步**读缓存入口（`cachedXxx()`），
 *    页面首帧直接渲染，再后台刷新（异步读会先闪一帧空白）；
 * 4. **渲染门控**——`aiSummary` / `aiAnnotations` 只在 `aiStatus === 'ok'` 时可用
 *    （对齐 Web 端 `apps/web/src/pages/read/[id].astro:10-11`），页面不得自行判断。
 */
export class ContentService {
  static loadManifest(): Promise<Loaded<ContentManifest>> {
    return ContentService.loadWithCache<ContentManifest>(Endpoints.manifestUrl());
  }

  static loadSummary(date: string): Promise<Loaded<TodaySummary>> {
    return ContentService.loadWithCache<TodaySummary>(Endpoints.summaryUrl(date));
  }

  static loadDigest(date: string): Promise<Loaded<DailyDigest>> {
    return ContentService.loadWithCache<DailyDigest>(Endpoints.digestUrl(date));
  }

  static loadArticle(articleId: string): Promise<Loaded<ClippedArticle>> {
    return ContentService.loadWithCache<ClippedArticle>(Endpoints.articleUrl(articleId));
  }

  /** 政策档案索引（月份列表 + 全馆合计）。 */
  static loadArchiveIndex(): Promise<Loaded<ContentArchiveIndex>> {
    return ContentService.loadWithCache<ContentArchiveIndex>(Endpoints.archiveIndexUrl());
  }

  /** 某月政策台账。 */
  static loadArchiveMonth(month: string): Promise<Loaded<ContentArchiveMonth>> {
    return ContentService.loadWithCache<ContentArchiveMonth>(Endpoints.archiveMonthUrl(month));
  }

  // —— 同步缓存读：供冷启动首帧使用 ——

  static cachedManifest(): Loaded<ContentManifest> | null {
    return ContentService.readCached<ContentManifest>(Endpoints.manifestUrl());
  }

  static cachedSummary(date: string): Loaded<TodaySummary> | null {
    return ContentService.readCached<TodaySummary>(Endpoints.summaryUrl(date));
  }

  static cachedDigest(date: string): Loaded<DailyDigest> | null {
    return ContentService.readCached<DailyDigest>(Endpoints.digestUrl(date));
  }

  static cachedArticle(articleId: string): Loaded<ClippedArticle> | null {
    return ContentService.readCached<ClippedArticle>(Endpoints.articleUrl(articleId));
  }

  static cachedArchiveIndex(): Loaded<ContentArchiveIndex> | null {
    return ContentService.readCached<ContentArchiveIndex>(Endpoints.archiveIndexUrl());
  }

  static cachedArchiveMonth(month: string): Loaded<ContentArchiveMonth> | null {
    return ContentService.readCached<ContentArchiveMonth>(Endpoints.archiveMonthUrl(month));
  }

  /** 可用的 AI 标注；`aiStatus !== 'ok'` 时返回空数组（不伪造、不降级猜测）。 */
  static usableAnnotations(article: ClippedArticle): AiAnnotation[] {
    if (article.aiStatus !== 'ok') {
      return [];
    }
    const raw: AiAnnotation[] | undefined = article.aiAnnotations;
    return raw === undefined ? [] : raw;
  }

  /** 可用的 AI 概括；`aiStatus !== 'ok'` 时返回空串。 */
  static usableSummary(article: ClippedArticle): string {
    if (article.aiStatus !== 'ok') {
      return '';
    }
    const raw: string | undefined = article.aiSummary;
    return raw === undefined ? '' : raw.trim();
  }

  private static readCached<T>(url: string): Loaded<T> | null {
    const entry: CacheEntry | null = Cache.read(url);
    if (entry === null) {
      return null;
    }
    try {
      const data: T = JSON.parse(entry.text) as T;
      return { data: data, cached: true, savedAt: entry.savedAt };
    } catch (parseErr) {
      // 缓存内容损坏：当作没有缓存，交给网络路径
      return null;
    }
  }

  /**
   * 先网络后缓存。
   * 缓存是**兜底**不是**优先**——在线时必须拿最新内容，时政的时效性不允许吃缓存。
   */
  private static loadWithCache<T>(url: string): Promise<Loaded<T>> {
    return HttpClient.getJson<T>(url).then(
      (data: T): Loaded<T> => {
        Cache.write(url, JSON.stringify(data));
        return { data: data, cached: false, savedAt: Date.now() };
      },
      (err: Error): Loaded<T> => {
        const fallback: Loaded<T> | null = ContentService.readCached<T>(url);
        if (fallback !== null) {
          return fallback;
        }
        throw err;
      },
    );
  }
}
