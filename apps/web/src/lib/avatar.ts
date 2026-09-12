/**
 * 头像（画布 3:2027 Web 64 / 3:1937 手机 56）：身份底色圆 + 品牌字形。
 *
 * 为什么不用 emoji：emoji 是彩色位图 —— 颜色跟不了令牌、切主题不跟随、
 * 三端（Web / 鸿蒙 / 后台）形状还不一样。画布全篇一个 emoji 都没有，
 * 头像也是矢量字形 + 浅色圆（`3:1938` 圆 + `3:1939`/`3:1940` 两笔描边）。
 *
 * 底色六档见 `tokens.json` 的 `avatar_1..6`（画布 `3:2043`-`3:2048` 的六个色块），
 * 由 `check_panel_invariance` 强制两套主题同值 —— 那是用户自己挑的那一格，
 * 切主题时不该变成另一种颜色。
 */

/** 身份色档数。画布画了 6 格；线上原有 8 个 emoji 头像，按画布收敛为 6。 */
export const AVATAR_COUNT = 6;

/**
 * 品牌字形（两笔）：画布 `3:2029`/`3:2030`（头像）与 `3:6`/`3:7`（顶栏标识）
 * 是同一支图形按比例缩放 —— 左笔陡、右笔平，合起来是个「人」字。
 *
 * ⚠️ 画布的矢量路径读不出来（`fillGeometry` 只回二进制 commandsBlob），
 * 这条是按两笔的**包围盒比例**重画的：左笔 11.27×30、右笔 12.6×8.4（64 盒），
 * 换算到 24 viewBox 得 x 8.25–12.48 / y 6.0–17.25 与 x 12.0–16.73 / y 13.1–16.3。
 * 页脚原先那支 `M8 7.5v9M16 7.5v9M8 12h8`（像个 H）是早期手绘的近似，已一并纠正。
 */
export const BRAND_MARK_PATH = "M12 7L8.8 16.4M12.1 13.7L16.4 15.6";

/** 头像用的品牌字形：只出两笔，底色方块／圆由外层容器提供。 */
export const AVATAR_MARK =
  '<svg viewBox="0 0 24 24" aria-hidden="true">'
  + `<path d="${BRAND_MARK_PATH}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"></path>`
  + "</svg>";

/**
 * 把用户存下来的 `avatar` 解析成 0..5 的下标。
 *
 * 老数据存的是 emoji（`"😀"` 之类）—— 那批值在改成色块后无法对应任何一格，
 * 所以识别不出来时用邮箱哈希兜底：同一个邮箱永远得到同一格，头像不会跳。
 */
export function avatarIndex(stored: string | null | undefined, seed: string): number {
  const matched = /^avatar-(\d+)$/.exec(stored ?? "");
  if (matched) return (Number(matched[1]) - 1 + AVATAR_COUNT) % AVATAR_COUNT;
  let hash = 0;
  for (const ch of seed) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return hash % AVATAR_COUNT;
}

/** 该下标的 CSS 底色变量，给 `style="--av: …"` 用。 */
export const avatarVar = (index: number): string => `var(--avatar-${index + 1})`;
