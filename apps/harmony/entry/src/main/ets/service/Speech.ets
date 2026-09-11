import { ReadStateCode, TextReader } from '@kit.SpeechKit';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongReader';

/**
 * 朗读（**官方 Speech Kit 朗读控件 TextReader**）。
 *
 * ## 为什么从裸 TTS 迁到朗读控件
 * 原来用 `@kit.CoreSpeechKit` 的 `textToSpeech` 自己拼段落朗读，查官方文档后确认三个硬约束：
 * 1. **Core Speech Kit 只有 3 个音色**（聆小珊 / 劳拉 / 凌飞哲），没有更多可选；
 * 2. **在线合成暂不支持**（原文：`0 为在线（暂不支持），1 为离线`）；
 *    后台运行 `keepBackgroundRunning` 也只是"预留参数"。
 * 3. 自己按段落串行提交，**段间音频管线会排空** → 卡顿 + 每段重新起音。
 *
 * 朗读控件是官方为"不方便看屏幕时朗读新闻"这一场景提供的组件：
 * 自带**断句、连续播放、播放面板（上下一句 / 快进 15 秒）、音色与语速调节**，
 * 且播报品牌信息**默认就是「小艺朗读」**。上述三个问题它一并解决。
 *
 * ## 代价（如实说明）
 * 控件**不暴露"当前读到文本哪个位置"**（只有播放时长与文章级状态），
 * 所以迁移后失去"读到哪一段"的自定义高亮跟随；换来的是官方面板与更稳的播放。
 */
export class Speech {
  private static inited: boolean = false;
  private static playing: boolean = false;
  private static stateListener: (playing: boolean) => void = () => {
  };

  /** 初始化一次（应用启动或首次朗读时）。失败不阻断阅读，只是"听"不可用。 */
  static async init(context: common.UIAbilityContext): Promise<boolean> {
    if (Speech.inited) {
      return true;
    }
    const params: TextReader.ReaderParam = {
      isVoiceBrandVisible: true,
      businessBrandInfo: {
        panelName: '考公云',
        panelIcon: $r('app.media.startIcon'),
      },
    };
    try {
      await TextReader.init(context, params);
      Speech.inited = true;
      Speech.registerEvents();
      return true;
    } catch (err) {
      const cause: BusinessError = err as BusinessError;
      hilog.warn(DOMAIN, TAG, '朗读控件初始化失败：%{public}s', cause.message);
      return false;
    }
  }

  static isAvailable(): boolean {
    return Speech.inited;
  }

  static isPlaying(): boolean {
    return Speech.playing;
  }

  /** 播放状态变化回调（页面据此更新按钮与提示）。 */
  static onStateChange(listener: (playing: boolean) => void): void {
    Speech.stateListener = listener;
  }

  /** 未初始化则先初始化。 */
  static async ready(context: common.UIAbilityContext): Promise<boolean> {
    return Speech.inited ? true : await Speech.init(context);
  }

  /**
   * 开始朗读。
   *
   * `fromIndex` 起（含）的段落拼成正文——**保留"从当前读到的地方继续"**：
   * 控件只能从文章开头播，所以先把前面已读过（或用户已看过）的部分截掉。
   */
  static async start(
    title: string,
    paragraphs: string[],
    fromIndex: number,
    articleId: string,
  ): Promise<boolean> {
    if (!Speech.inited || paragraphs.length === 0) {
      return false;
    }
    const begin: number = Math.max(0, Math.min(fromIndex, paragraphs.length - 1));
    const body: string = paragraphs.slice(begin).join('\n');
    if (body.trim().length === 0) {
      return false;
    }
    const info: TextReader.ReadInfo = {
      id: articleId,
      title: { text: title, isClickable: false },
      bodyInfo: body,
    };
    try {
      await TextReader.start([info]);
      return true;
    } catch (err) {
      const cause: BusinessError = err as BusinessError;
      hilog.error(DOMAIN, TAG, '起播失败：%{public}s（code=%{public}d）', cause.message, cause.code);
      return false;
    }
  }

  static stop(): void {
    TextReader.stop().catch((err: BusinessError) => {
      hilog.warn(DOMAIN, TAG, '停止失败：%{public}s', err.message);
    });
  }

  /** 注册控件事件。同一类型监听只第一次注册有效，所以只注册一次。 */
  private static registerEvents(): void {
    try {
      TextReader.on('stateChange', (state: TextReader.ReadState) => {
        const playing: boolean = state.state === ReadStateCode.PLAYING;
        Speech.playing = playing;
        Speech.stateListener(playing);
      });
    } catch (err) {
      const cause: BusinessError = err as BusinessError;
      hilog.warn(DOMAIN, TAG, '注册状态监听失败：%{public}s', cause.message);
    }
  }
}
