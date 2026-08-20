// 本地收藏（未登录可用）：localStorage 存储，登录后与云端收藏并存（阅读页显示云端优先）。
// 形状与云端 Favorite 兼容（id = url），收藏页本地模式直接复用 rowHtml 渲染。
export interface LocalFavorite {
  id: string; // = url
  url: string;
  title: string;
  kind: "article" | "term";
  createdAt: number;
  termText?: string;       // kind=term：术语文本
  termExplanation?: string; // kind=term：AI 释义
  articleId?: string;      // kind=term：来源文章阅读页 id
}

const KEY = "kaogong.localFavs";

export function loadLocalFavorites(): LocalFavorite[] {
  try {
    const raw = localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((f): f is LocalFavorite =>
        Boolean(f && typeof f === "object" && typeof (f as LocalFavorite).url === "string"))
      .map((f) => ({
        id: f.url,
        url: f.url,
        title: f.title ?? "",
        kind: (f.kind === "term" ? "term" : "article") as LocalFavorite["kind"],
        createdAt: f.createdAt ?? Date.now(),
        termText: f.termText ?? "",
        termExplanation: f.termExplanation ?? "",
        articleId: f.articleId ?? "",
      }));
  } catch {
    return [];
  }
}

function save(list: LocalFavorite[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    /* 隐私模式/存储满：静默降级 */
  }
}

export function isLocalFavorite(url: string): boolean {
  return loadLocalFavorites().some((f) => f.kind === "article" && f.url === url);
}

/** toggle 文章收藏，返回操作后是否已收藏。 */
export function toggleLocalFavorite(url: string, title: string): boolean {
  const list = loadLocalFavorites();
  const exists = list.some((f) => f.kind === "article" && f.url === url);
  if (exists) {
    save(list.filter((f) => !(f.kind === "article" && f.url === url)));
    return false;
  }
  list.push({ id: url, url, title, kind: "article", createdAt: Date.now() });
  save(list);
  return true;
}

export function removeLocalFavorite(url: string): void {
  save(loadLocalFavorites().filter((f) => f.url !== url));
}

/** 删除指定术语的本地收藏（不动同文章的其他收藏）。 */
export function removeLocalTermFavorite(url: string, termText: string): void {
  save(loadLocalFavorites().filter((f) => !(f.kind === "term" && f.url === url && f.termText === termText)));
}

/** 本地是否已收藏该术语（url + 术语文本）。 */
export function isLocalTermFavorite(url: string, termText: string): boolean {
  return loadLocalFavorites().some((f) => f.kind === "term" && f.url === url && f.termText === termText);
}

/** toggle 术语收藏，返回操作后是否已收藏。 */
export function toggleLocalTermFavorite(
  url: string,
  title: string,
  termText: string,
  termExplanation: string,
  articleId: string,
): boolean {
  const list = loadLocalFavorites();
  const exists = list.some((f) => f.kind === "term" && f.url === url && f.termText === termText);
  if (exists) {
    save(list.filter((f) => !(f.kind === "term" && f.url === url && f.termText === termText)));
    return false;
  }
  list.push({ id: url, url, title, kind: "term", termText, termExplanation, articleId, createdAt: Date.now() });
  save(list);
  return true;
}
