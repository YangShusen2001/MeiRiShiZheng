import { preferences } from '@kit.ArkData';
import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongSettings';
const STORE_NAME: string = 'kaogong_settings';

/**
 * 用户偏好（阅读档位 / 深浅色）。
 *
 * 设计约束：
 * - **必须持久化**——否则每次冷启动都复位，字号设置形同虚设；
 * - **必须写进 AppStorage**——令牌层（`theme/Tokens.ets`）是纯函数式读取 AppStorage 取当前值，
 *   页面再用 `@StorageLink` 订阅重建，这样一套令牌同时支持运行时切换；
 * - **不强制浅色**——首版在 EntryAbility 里固定了浅色，那会让系统深色失效，已移除。
 *
 * 存储失败不阻断功能：只打日志，内存态照常生效（宁可"这次不记住"，也不要崩）。
 */
export class Settings {
  static readonly KEY_DARK: string = 'darkMode';
  static readonly KEY_FONT_SCALE: string = 'fontScale';
  static readonly KEY_LAST_ID: string = 'lastReadId';
  static readonly KEY_LAST_INDEX: string = 'lastReadIndex';

  /** 阅读档位系数（与 DESIGN.md 的档位表一致）。 */
  static readonly FONT_STEPS: number[] = [0.88, 1, 1.15, 1.3];
  /** 档位名称。 */
  static readonly FONT_LABELS: string[] = ['小', '标准', '大', '特大'];
  /** 标准档在 FONT_STEPS 中的下标。 */
  static readonly FONT_STEP_DEFAULT: number = 1;

  private static store: preferences.Preferences | null = null;
  private static appContext: common.UIAbilityContext | null = null;

  /**
   * 应用级 context（EntryAbility 已持有）。
   * 供需要 context 的能力复用（如系统分享），避免在组件内使用获取 hostContext 的那套
   * API——它跨版本行为不一致。
   */
  static context(): common.UIAbilityContext | null {
    return Settings.appContext;
  }

  /** 在 `EntryAbility.onCreate` 调用（只有那里拿得到 context）。 */
  static init(context: common.UIAbilityContext): void {
    Settings.appContext = context;
    try {
      Settings.store = preferences.getPreferencesSync(context, { name: STORE_NAME });
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '偏好存储不可用，本次运行不持久化：%{public}s', cause.message);
      Settings.store = null;
    }
    Settings.syncToAppStorage();
  }

  /** 读取持久化值 → 写入 AppStorage。 */
  private static syncToAppStorage(): void {
    const dark: boolean = Settings.readBool(Settings.KEY_DARK, false);
    const scale: number = Settings.readNumber(Settings.KEY_FONT_SCALE, 1);
    AppStorage.setOrCreate<boolean>('darkMode', dark);
    AppStorage.setOrCreate<number>('fontScale', scale);
    Settings.applyColorMode(dark);
  }

  static isDark(): boolean {
    const value: boolean | undefined = AppStorage.get<boolean>('darkMode');
    return value === true;
  }

  static fontScale(): number {
    const value: number | undefined = AppStorage.get<number>('fontScale');
    return value === undefined ? 1 : value;
  }

  /** 当前档位下标（无法匹配时回落到标准档）。 */
  static fontStepIndex(): number {
    const current: number = Settings.fontScale();
    for (let index = 0; index < Settings.FONT_STEPS.length; index++) {
      if (Math.abs(Settings.FONT_STEPS[index] - current) < 0.001) {
        return index;
      }
    }
    return Settings.FONT_STEP_DEFAULT;
  }

  static setDark(dark: boolean): void {
    AppStorage.setOrCreate<boolean>('darkMode', dark);
    Settings.writeBool(Settings.KEY_DARK, dark);
    Settings.applyColorMode(dark);
  }

  /** 按档位下标设置字号。 */
  static setFontStep(stepIndex: number): void {
    if (stepIndex < 0 || stepIndex >= Settings.FONT_STEPS.length) {
      return;
    }
    const scale: number = Settings.FONT_STEPS[stepIndex];
    AppStorage.setOrCreate<number>('fontScale', scale);
    Settings.writeNumber(Settings.KEY_FONT_SCALE, scale);
  }

  /**
   * 记录阅读位置。
   * 只在**离开阅读页时**写一次（而非滚动中每次写）——滚动中频繁落盘既无必要也伤 IO。
   * 只保留最近一篇：单点续读即可满足「接着上次看」的真实需求，且存储不随阅读量增长。
   */
  static saveReadingPosition(articleId: string, paragraphIndex: number): void {
    Settings.writeString(Settings.KEY_LAST_ID, articleId);
    Settings.writeNumber(Settings.KEY_LAST_INDEX, paragraphIndex);
  }

  static lastReadId(): string {
    return Settings.readString(Settings.KEY_LAST_ID, '');
  }

  static lastReadIndex(): number {
    return Settings.readNumber(Settings.KEY_LAST_INDEX, 0);
  }

  /**
   * 同步系统级配色模式，让框架自带组件（加载指示、系统弹窗）一起跟随。
   * 令牌层不依赖它——令牌读的是 AppStorage，二者互为补充。
   */
  private static applyColorMode(dark: boolean): void {
    const context: common.UIAbilityContext | null = Settings.appContext;
    if (context === null) {
      return;
    }
    try {
      const mode: ConfigurationConstant.ColorMode = dark
        ? ConfigurationConstant.ColorMode.COLOR_MODE_DARK
        : ConfigurationConstant.ColorMode.COLOR_MODE_LIGHT;
      context.getApplicationContext().setColorMode(mode);
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, 'setColorMode 失败（不影响令牌生效）：%{public}s', cause.message);
    }
  }

  private static readBool(key: string, fallback: boolean): boolean {
    const store: preferences.Preferences | null = Settings.store;
    if (store === null) {
      return fallback;
    }
    try {
      return store.getSync(key, fallback) as boolean;
    } catch (err) {
      return fallback;
    }
  }

  private static readNumber(key: string, fallback: number): number {
    const store: preferences.Preferences | null = Settings.store;
    if (store === null) {
      return fallback;
    }
    try {
      return store.getSync(key, fallback) as number;
    } catch (err) {
      return fallback;
    }
  }

  private static writeBool(key: string, value: boolean): void {
    const store: preferences.Preferences | null = Settings.store;
    if (store === null) {
      return;
    }
    try {
      store.putSync(key, value);
      store.flush();
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '写入偏好失败：%{public}s', cause.message);
    }
  }

  private static writeNumber(key: string, value: number): void {
    const store: preferences.Preferences | null = Settings.store;
    if (store === null) {
      return;
    }
    try {
      store.putSync(key, value);
      store.flush();
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '写入偏好失败：%{public}s', cause.message);
    }
  }

  private static readString(key: string, fallback: string): string {
    const store: preferences.Preferences | null = Settings.store;
    if (store === null) {
      return fallback;
    }
    try {
      return store.getSync(key, fallback) as string;
    } catch (err) {
      return fallback;
    }
  }

  private static writeString(key: string, value: string): void {
    const store: preferences.Preferences | null = Settings.store;
    if (store === null) {
      return;
    }
    try {
      store.putSync(key, value);
      store.flush();
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '写入偏好失败：%{public}s', cause.message);
    }
  }
}
