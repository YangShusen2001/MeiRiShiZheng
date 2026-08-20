// 本地收藏（未登录可用）：localStorage 存储，登录后与云端收藏并存（阅读页显示云端优先）。
// 形状与云端 Favorite 兼容（id = url），收藏页本地模式直接复用 rowHtml 渲染。
export interface LocalFavorite {
  id: string; // = url
  url: string;
  title: string;
  kind: "article";
  createdAt: number;
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
      .map((f) => ({ id: f.url, url: f.url, title: f.title ?? "", kind: "article" as const, createdAt: f.createdAt ?? Date.now() }));
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
  return loadLocalFavorites().some((f) => f.url === url);
}

/** toggle 本地收藏，返回操作后是否已收藏。 */
export function toggleLocalFavorite(url: string, title: string): boolean {
  const list = loadLocalFavorites();
  const exists = list.some((f) => f.url === url);
  if (exists) {
    save(list.filter((f) => f.url !== url));
    return false;
  }
  list.push({ id: url, url, title, kind: "article", createdAt: Date.now() });
  save(list);
  return true;
}

export function removeLocalFavorite(url: string): void {
  save(loadLocalFavorites().filter((f) => f.url !== url));
}
