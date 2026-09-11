import { preferences } from '@kit.ArkData';
import { common, ConfigurationConstant } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { util } from '@kit.ArkTS';

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
  static readonly KEY_DEVICE_ID: string = 'deviceId';
  static readonly KEY_SPEAK_SPEED: string = 'speakSpeed';
  static readonly KEY_SPEAK_ONLINE: string = 'speakOnline';

  /** 朗读速度档位。通勤场景下 1.25 倍是刚需——省时间且不失可懂度。 */
  static readonly SPEED_STEPS: number[] = [0.8, 1, 1.25, 1.5];
  static readonly SPEED_LABELS: string[] = ['0.8×', '1.0×', '1.25×', '1.5×'];

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
   * 匿名设备标识。服务端用它做配额与限流（`X-Device-Id`，要求 `[a-zA-Z0-9_-]{8,64}`）。
   *
   * 首次调用生成并持久化——**必须持久化**，否则每次冷启动都算新设备，
   * 会绕过配额（对服务端不友好）也会丢掉已激活的邀请码额度。
   */
  static deviceId(): string {
    const existing: string = Settings.readString(Settings.KEY_DEVICE_ID, '');
    if (existing.length >= 8) {
      return existing;
    }
    const generated: string = util.generateRandomUUID(false);
    Settings.writeString(Settings.KEY_DEVICE_ID, generated);
    return generated;
  }

  /** 朗读速度（倍速）。默认 1.0。 */
  static speakSpeed(): number {
    return Settings.readNumber(Settings.KEY_SPEAK_SPEED, 1);
  }

  /** 当前速度档位下标（无法匹配时回落到 1.0 档）。 */
  static speedStepIndex(): number {
    const current: number = Settings.speakSpeed();
    for (let index = 0; index < Settings.SPEED_STEPS.length; index++) {
      if (Math.abs(Settings.SPEED_STEPS[index] - current) < 0.001) {
        return index;
      }
    }
    return 1;
  }

  static setSpeedStep(stepIndex: number): void {
    if (stepIndex < 0 || stepIndex >= Settings.SPEED_STEPS.length) {
      return;
    }
    Settings.writeNumber(Settings.KEY_SPEAK_SPEED, Settings.SPEED_STEPS[stepIndex]);
  }

  /**
   * 朗读是否用在线引擎。
   *
   * **默认 false（离线）**：目标场景是通勤，地铁里没网——
   * 在线引擎在没网时直接不可用，那是致命的。
   * 在线引擎音色更自然（走云端发音人），愿意用流量/有网的用户可以打开。
   *
   * 注意 SDK 的取值语义是**反直觉**的：
   * `The value 0 indicates online, value 1 indicates offline.`
   * （此前的实现把 0 当成离线，等于一直在用在线引擎却声称离线。）
   */
  static speakOnline(): boolean {
    return Settings.readBool(Settings.KEY_SPEAK_ONLINE, false);
  }

  static setSpeakOnline(online: boolean): void {
    Settings.writeBool(Settings.KEY_SPEAK_ONLINE, online);
  }

  /**
   * 同步系统级配色模式，让框架自带组件（加载指示、系统弹窗）一起跟随。
   * 令牌层不依赖它——令牌读的是 AppStorage，二者互为补充。
   */  private static applyColorMode(dark: boolean): void {
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
