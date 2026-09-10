import { Endpoints } from '../config/Endpoints';
import { AiAnnotation, ClippedArticle, ContentManifest, DailyDigest, TodaySummary } from '../model/Content';
import { HttpClient } from './Http';

/**
 * 内容服务：原生端唯一的取数入口。
 *
 * 渲染门控必须在这里收口（对齐 Web 端 `apps/web/src/pages/read/[id].astro:10-11`）：
 * `aiSummary` 与 `aiAnnotations` **只在 `aiStatus === 'ok'` 时才可使用**，
 * 否则应只显示原文。把该规则放在服务层，保证任何页面都不会绕过它。
 */
export class ContentService {
  static loadManifest(): Promise<ContentManifest> {
    return HttpClient.getJson<ContentManifest>(Endpoints.manifestUrl());
  }

  static loadSummary(date: string): Promise<TodaySummary> {
    return HttpClient.getJson<TodaySummary>(Endpoints.summaryUrl(date));
  }

  static loadDigest(date: string): Promise<DailyDigest> {
    return HttpClient.getJson<DailyDigest>(Endpoints.digestUrl(date));
  }

  static loadArticle(articleId: string): Promise<ClippedArticle> {
    return HttpClient.getJson<ClippedArticle>(Endpoints.articleUrl(articleId));
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
}
