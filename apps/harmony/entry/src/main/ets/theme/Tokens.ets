/**
 * 考公云鸿蒙端 · 设计令牌（Design Tokens）
 *
 * ⚠️ 本文件是**鸿蒙端视觉的唯一事实源**。页面里不得再出现硬编码色值、字号、间距。
 *    新增视觉需求时，先在此加令牌，再在页面引用。
 *
 * ## 为什么令牌是「方法」而不是「常量」
 * 需要支持运行时切换：
 * - **深浅色**：`darkMode` 改变后，页面因 `@StorageLink('darkMode')` 触发重建，
 *   `build()` 重新求值 → 颜色随之更新。若令牌是编译期常量就无法切换。
 * - **字号缩放**：阅读档位（小/标准/大/特大）按比例作用于内容文本，行高联动。
 * 二者都存在 `AppStorage`，由 `service/Settings.ets` 负责持久化。
 *
 * ## 设计定位
 * 暖米底 + 靛青的「书卷」调性。v3 起与 Web / 审核后台**共用同一套值**
 * （唯一源 packages/design-tokens/tokens.json）—— 此前「鸿蒙有意不共用色板」的结论已推翻。
 * 深色模式同理**不做反色**：反色会把米色变成脏灰，且纯黑底配暖色文本夜间过刺。
 * 暗色用独立的「深暖灰」体系，文字用暖白（不用纯白，避免眩光）。
 *
 * ## 对比度（WCAG 2.1，按相对亮度公式实算；与 packages/design-tokens 的测试向量同源）
 * 浅色：ink 13.19（暖底）/ sub 6.55 / mut 5.70 —— **双底都过 AA**（旧值只敢用在白卡上）
 *       primaryText 8.68（brandSoft 底；直接用 primary 也有 7.04）
 * 深色：ink 14.51 / sub 8.40 / mut 6.42 / primary 6.60（深底）/ primaryText 6.95
 * 标注：深色标注底对卡片面的**可见度** ≥1.65 —— 文字对比度合格不等于标记本身看得见
 */
export class KColor {
  /** 当前是否深色。由 Settings 写入 AppStorage；页面用 @StorageLink 订阅以便重建。 */
  static isDark(): boolean {
    const value: boolean | undefined = AppStorage.get<boolean>('darkMode');
    return value === true;
  }

  // —— 底色与容器 ——
  static bg(): string {
    return KColor.isDark() ? '#1A1815' : '#F5F1E8';
  }

  static surface(): string {
    return KColor.isDark() ? '#242220' : '#FFFDF6';
  }

  static surfaceAlt(): string {
    return KColor.isDark() ? '#2C2A26' : '#F0EADD';
  }

  // —— 文本三级 ——
  static ink(): string {
    return KColor.isDark() ? '#EDE8DE' : '#2A2723';
  }

  static sub(): string {
    return KColor.isDark() ? '#B8B2A6' : '#5A554E';
  }

  static mut(): string {
    return KColor.isDark() ? '#A29B8E' : '#635E56';
  }

  // —— 描边（浅色为暖调，非冷灰；深色同为暖灰）——
  static line(): string {
    return KColor.isDark() ? '#3A3732' : '#E4DCCB';
  }

  static lineSoft(): string {
    return KColor.isDark() ? '#2F2C28' : '#EFE9DC';
  }

  // —— 品牌靛 ——
  /** 填充、图标、进度等大色块。 */
  static primary(): string {
    return KColor.isDark() ? '#9099E0' : '#3A4785';
  }

  /** 小字号文本专用：压在 brandSoft 上（浅 8.68 / 深 6.95）；直接用 primary 也达标（浅 7.04）。 */
  static primaryText(): string {
    return KColor.isDark() ? '#A9B1EA' : '#2E3A72';
  }

  static primarySoft(): string {
    return KColor.isDark() ? '#252843' : '#E4E7F5';
  }

  // —— 语义色 ——
  static danger(): string {
    return KColor.isDark() ? '#F0A0A0' : '#AF2F26';
  }

  static dangerSoft(): string {
    return KColor.isDark() ? '#3A2422' : '#FEF2F2';
  }

  static warnInk(): string {
    return KColor.isDark() ? '#E8C98A' : '#8A5A0B';
  }

  static warnSoft(): string {
    return KColor.isDark() ? '#3A3222' : '#FDF3DF';
  }

  static hintSoft(): string {
    return KColor.isDark() ? '#332E22' : '#FFFBEB';
  }

  static neutralSoft(): string {
    return KColor.isDark() ? '#33302B' : '#EAE4D6';
  }

  // —— AI 标注四色 ——
  // 浅色用浅底 + 深字；深色改用暗底 + 暖白字（浅底在暗环境下会眩光）。
  static annExam(): string {
    return KColor.isDark() ? '#574818' : '#FFE7A0';
  }

  static annViewpoint(): string {
    return KColor.isDark() ? '#2C4C31' : '#C9E7CE';
  }

  static annTerm(): string {
    return KColor.isDark() ? '#285058' : '#B9DEE6';
  }

  static annFigure(): string {
    return KColor.isDark() ? '#653744' : '#F8C8D8';
  }

  // —— 装饰 ——
  static skeleton(): string {
    return KColor.isDark() ? '#2E2B27' : '#EFEBE1';
  }

  /** 浮层遮罩：浅色用轻遮罩（重遮罩让暖底显脏）；深色需更重才压得住。 */
  static scrim(): string {
    return KColor.isDark() ? '#80000000' : '#33000000';
  }

  /** 标注片段上的文字色：深色底必须配暖白字。 */
  static annInk(): string {
    return KColor.isDark() ? '#EDE8DE' : '#2A2723';
  }
}

/** 标注类型 → 高亮底色；未知类型返回空串（不猜颜色）。 */
export function annotationBg(type: string): string {
  if (type === 'exam_point') {
    return KColor.annExam();
  }
  if (type === 'viewpoint') {
    return KColor.annViewpoint();
  }
  if (type === 'term') {
    return KColor.annTerm();
  }
  if (type === 'figure') {
    return KColor.annFigure();
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
}

/** 圆角标尺。 */
export class KRadius {
  static readonly XS: number = 4;
  static readonly S: number = 8;
  static readonly M: number = 10;
  static readonly L: number = 14;
  static readonly XL: number = 20;
  static readonly FULL: number = 999;
}

/**
 * 字号标尺：以正文 17 为基准，比例约 1.2（12 / 14 / 17 / 20 / 24 / 28）。
 * 内容文本（正文、标题）随阅读档位缩放；界面文字（角标、来源）保持稳定，
 * 避免放大后导航与标签互相挤压。
 */
export class KFont {
  /** 阅读档位系数：0.88 小 / 1 标准 / 1.15 大 / 1.3 特大。 */
  static scale(): number {
    const value: number | undefined = AppStorage.get<number>('fontScale');
    if (value === undefined) {
      return 1;
    }
    return value;
  }

  /**
   * 全部字号档位都随设置缩放。
   *
   * ⚠️ 之前 `caption` 与 `meta` 是固定值（当时想"不影响导航标签"），
   * 但它们在首页占比最大——来源、日期、序号、关键词全在这两档，
   * 结果用户选「特大」时这些字纹丝不动，体感就是"字号调节无效"。
   * **用户选大字就是要都看得清**，所以内容文字一律跟随。
   * （真正的"导航标签"由框架绘制，本来就改不了，不在此列。）
   */
  static caption(): number {
    return Math.round(12 * KFont.scale());
  }

  static meta(): number {
    return Math.round(14 * KFont.scale());
  }

  static body(): number {
    return Math.round(17 * KFont.scale());
  }

  static titleS(): number {
    return Math.round(20 * KFont.scale());
  }

  static titleM(): number {
    return Math.round(24 * KFont.scale());
  }

  static titleL(): number {
    return Math.round(28 * KFont.scale());
  }
}

/** 行高：中文正文按 1.76 倍，标题收紧；全部跟随字号缩放，否则放大后文字会挤。 */
export class KLine {
  static tight(): number {
    return Math.round(KFont.meta() * 1.57);
  }

  static normal(): number {
    return Math.round(KFont.body() * 1.41);
  }

  static relaxed(): number {
    return Math.round(KFont.body() * 1.76);
  }

  static display(): number {
    return Math.round(KFont.titleL() * 1.36);
  }
}

/** 动效时长：与 Web 端档位一致（120 / 160 / 250 / 400ms）。 */
export class KDur {
  static readonly XS: number = 120;
  static readonly SM: number = 160;
  static readonly MD: number = 250;
  static readonly LG: number = 400;
}

/** 暖调投影（ArkUI 的 .shadow 需逐项传入）。 */
export class KShadow {
  static readonly CARD_RADIUS: number = 14;
  static readonly CARD_COLOR: string = '#14000000';
  static readonly CARD_OFFSET_Y: number = 1;
}

/** 无障碍硬指标：交互元素最小高度（vp）。 */
export class KSize {
  static readonly TOUCH_MIN: number = 44;
}
