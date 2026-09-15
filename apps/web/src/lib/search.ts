// 搜索索引：构建时把全部日报 + 剪藏原文 + 政策档案扁平化成可检索条目，供搜索页客户端全文过滤。
import { listArticles, listDigests } from "./content";
import { getArchive, listArchiveMonths } from "./archive";

export interface SearchEntry {
  date: string;
  section: string;
  title: string;
  sourceUrl: string;
  summary: string;
  href: string;
  external: boolean;
  body: string;
  /**
   * 结果筛选用（画布 3:1167 的三个胶囊：「全部 / 文章 / 政策」）。
   * ⚠️ 政策档案原先**不在索引里** —— 那会让政策档案页的搜索框变成假入口
   * （搜「十五五」只出文章、搜政策标题 0 结果）。这里补上。
   */
  type: "article" | "policy";
}

export function buildSearchIndex(): SearchEntry[] {
  const articleByUrl = new Map(listArticles().map((a) => [a.url, a]));

  const articles: SearchEntry[] = listDigests().flatMap((d) =>
    d.sections.flatMap((s) =>
      s.items.map((it) => {
        const article = articleByUrl.get(it.sourceUrl);
        const body = article
          ? [article.aiSummary ?? "", ...(article.keySentences ?? []), ...(article.paragraphs ?? [])].join(" ")
          : "";
        return {
          date: d.date,
          section: s.title,
          title: it.title,
          sourceUrl: it.sourceUrl,
          summary: it.summary ?? "",
          href: article ? `/read/${article.id}/` : it.sourceUrl,
          external: !article,
          body,
          type: "article" as const,
        };
      }),
    ),
  );

  // 政策档案：全月台账条目。标题/要点/考点/来源都进可检索字段，
  // href 直指官方原文（政策没有站内详情页）。
  const policies: SearchEntry[] = listArchiveMonths().flatMap((month) => {
    const doc = getArchive(month);
    return (doc?.items ?? []).map((it) => ({
      date: it.date,
      section: "政策档案",
      title: it.title,
      sourceUrl: it.url,
      summary: it.gist ?? "",
      href: it.url,
      external: true,
      body: [it.gist ?? "", it.topic ?? "", it.lib ?? ""].join(" "),
      type: "policy" as const,
    }));
  });

  return [...articles, ...policies];
}
