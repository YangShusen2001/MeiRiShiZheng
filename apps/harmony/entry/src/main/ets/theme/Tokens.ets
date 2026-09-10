/**
 * 考公云鸿蒙端 · 设计令牌（Design Tokens）
 *
 * ⚠️ 本文件是**鸿蒙端视觉的唯一事实源**。页面里不得再出现硬编码色值、字号、间距。
 *    新增视觉需求时，先在此加令牌，再在页面引用。
 *
 * 设计定位：暖米底 + 深绿的「护眼阅读」调性（native-first，不跟随 Web 的冷蓝体系）。
 * 与 Web 端**有意不共用**色板：原生端追求长时阅读的暖调与低蓝光，Web 端保持其品牌蓝。
 *
 * 对比度（WCAG 2.1，全部经计算，非估计）：
 *   ink  #1F2937 on bg #F5F1E8 → 13.02:1  ✅ AAA
 *   ink  #1F2937 on surface   → 13.90:1  ✅ AAA
 *   sub  #5F6875 on bg        →  5.00:1  ✅ AA
 *   sub  #5F6875 on surface   →  5.64:1  ✅ AA
 *   mut  #6A7280 on surface   →  4.85:1  ✅ AA（⚠️ 仅限白底使用；暖底上只有 4.30:1）
 *   pri  #4C795B on surface   →  5.01:1  ✅ AA
 *   priTx#456F53 on priSoft   →  4.89:1  ✅ AA（浅绿底上的文字必须用 priTx，不能用 pri）
 *
 * 修正说明：原实现的 #9CA3AF（次要信息）在白底仅 2.54:1、#6B7280 在暖底 4.29:1，
 * 均未达 AA。下面 mut / sub 的取值是在**保持原色相**的前提下加深，不是换色。
 */
export class KColor {
  // —— 底色与容器 ——
  /** 页面底色：暖米。 */
  static readonly BG: string = '#F5F1E8';
  /** 卡片/内容容器。 */
  static readonly SURFACE: string = '#FFFFFF';
  /** 次级容器（图例底、内嵌区块）：比 surface 略暖，避免大片纯白割裂。 */
  static readonly SURFACE_ALT: string = '#FAF7F0';

  // —— 文本三级 ——
  /** 正文与标题。 */
  static readonly INK: string = '#1F2937';
  /** 次要文本：来源、日期、摘要。两底皆达 AA。 */
  static readonly SUB: string = '#5F6875';
  /** 三级信息：序号、极次要标签。⚠️ 仅用于 surface 之上。 */
  static readonly MUT: string = '#6A7280';

  // —— 描边 ——
  /** 分隔线与描边：带暖调（原实现用冷灰 #E5E7EB 压在暖底上，色温冲突）。 */
  static readonly LINE: string = '#E6DFD0';
  /** 更浅的分隔线，用于卡片内部分隔。 */
  static readonly LINE_SOFT: string = '#F0EADD';

  // —— 品牌绿 ——
  /** 品牌色：用于填充、图标、进度等大色块。 */
  static readonly PRIMARY: string = '#4C795B';
  /** 品牌色上的文本/小字号标签：加深以保证对比度。 */
  static readonly PRIMARY_TEXT: string = '#456F53';
  /** 品牌浅底：胶囊标签背景。 */
  static readonly PRIMARY_SOFT: string = '#E6EFE8';

  // —— 语义色 ——
  static readonly DANGER: string = '#B91C1C';
  static readonly DANGER_SOFT: string = '#FEF2F2';
  /** 提示/警示（如未收录原文、未生成释义）。 */
  static readonly WARN_INK: string = '#8A5A0B';
  static readonly WARN_SOFT: string = '#FDF3DF';
  /** 释义浮层底（比 WARN_SOFT 更暖，用于强调）。 */
  static readonly HINT_SOFT: string = '#FFFBEB';
  /** 中性胶囊底（如「收起」按钮）。 */
  static readonly NEUTRAL_SOFT: string = '#ECEFF3';

  // —— AI 标注语义（四色，沿用既有配色）——
  /** 考点。 */
  static readonly ANN_EXAM: string = '#FFE7A0';
  /** 观点。 */
  static readonly ANN_VIEWPOINT: string = '#C8E6C9';
  /** 术语。 */
  static readonly ANN_TERM: string = '#BBDEFB';
  /** 数字指标。 */
  static readonly ANN_FIGURE: string = '#F8BBD0';

  // —— 装饰 ——
  /** 骨架屏/占位灰。 */
  static readonly SKELETON: string = '#EFEBE1';
  /** 浮层遮罩：轻微压暗即可，重遮罩会让暖底阅读界面显得脏。 */
  static readonly SCRIM: string = '#33000000';
}

/** 标注类型 → 高亮底色；未知类型返回空串（不猜颜色）。 */
export function annotationBg(type: string): string {
  if (type === 'exam_point') {
    return KColor.ANN_EXAM;
  }
  if (type === 'viewpoint') {
    return KColor.ANN_VIEWPOINT;
  }
  if (type === 'term') {
    return KColor.ANN_TERM;
  }
  if (type === 'figure') {
    return KColor.ANN_FIGURE;
  }
  return '';
}

/** 间距标尺：4 的倍数。原实现出现 2/6/10/13/14/18/21/26 等编外值，已全部归位。 */
export class KSpace {
  static readonly HAIR: number = 2;
  static readonly XS: number = 4;
  static readonly S: number = 8;
  static readonly M: number = 12;
  static readonly L: number = 16;
  static readonly XL: number = 20;
  static readonly XXL: number = 24;
  static readonly XXXL: number = 32;
  /** 页面左右安全边距。 */
  static readonly PAGE: number = 16;
  /** 区块之间的垂直间距。 */
  static readonly SECTION: number = 12;
}

/** 圆角标尺。 */
export class KRadius {
  static readonly XS: number = 4;
  static readonly S: number = 8;
  static readonly M: number = 10;
  /** 卡片。 */
  static readonly L: number = 14;
  static readonly XL: number = 20;
  /** 胶囊。 */
  static readonly FULL: number = 999;
}

/**
 * 字号标尺：以正文 17 为基准，比例约 1.2（12 / 14 / 17 / 20 / 24 / 28）。
 * 原实现为 12/13/14/15/16/17/22 —— 7 档无比例关系，13、15 为编外值。
 */
export class KFont {
  /** 序号、角标。 */
  static readonly CAPTION: number = 12;
  /** 来源、日期、标签。 */
  static readonly META: number = 14;
  /** 正文（阅读页）。 */
  static readonly BODY: number = 17;
  /** 卡片标题、列表标题。 */
  static readonly TITLE_S: number = 20;
  /** 区块标题。 */
  static readonly TITLE_M: number = 24;
  /** 页面大标题（文章标题）。 */
  static readonly TITLE_L: number = 28;
}

/** 行高：中文正文按 1.75 倍（30/17），标题收紧到 1.3。 */
export class KLine {
  static readonly TIGHT: number = 22;
  static readonly NORMAL: number = 24;
  /** 正文行高（配 KFont.BODY）。 */
  static readonly RELAXED: number = 30;
  /** 大标题行高（配 KFont.TITLE_L）。 */
  static readonly DISPLAY: number = 38;
}

/** 动效时长：与 Web 端档位保持一致（120 / 160 / 250 / 400ms）。 */
export class KDur {
  static readonly XS: number = 120;
  static readonly SM: number = 160;
  static readonly MD: number = 250;
  static readonly LG: number = 400;
}

/**
 * 阴影：暖调投影（原实现未用阴影，卡片靠纯白硬边区分，层次偏平）。
 * ArkUI 的阴影通过 .shadow({ radius, color, offsetY }) 使用。
 */
export class KShadow {
  /** 卡片默认。 */
  static readonly CARD_RADIUS: number = 14;
  static readonly CARD_COLOR: string = '#14000000';
  static readonly CARD_OFFSET_Y: number = 1;
  /** 浮层（释义卡）。 */
  static readonly POP_RADIUS: number = 24;
  static readonly POP_COLOR: string = '#1F000000';
  static readonly POP_OFFSET_Y: number = 4;
}
