import { textToSpeech } from '@kit.CoreSpeechKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongSpeech';
/** 段落之间的停顿：纯 TTS 连读没有换气感，听起来像机器报菜名。 */
const GAP_MS: number = 320;

/**
 * 朗读（系统 TTS）。
 *
 * ## 为什么按段落逐句朗读，而不是整篇一次提交
 * 整篇提交只能拿到"开始/结束"两个信号，**无法知道当前读到哪一段**——
 * 而"听"的核心体验恰恰是**跟随高亮 + 自动滚动**（用户在地铁上不方便看屏幕，
 * 需要随时能瞄一眼确认位置）。逐段提交让我们完全掌控进度。
 *
 * ## 边界（如实说明）
 * - 依赖系统 TTS 引擎，`createEngine` 失败时返回 false，页面如实提示，不静默失败。
 * - **不做后台播放**：应用退到后台即停止。真正的后台朗读需要 AVSession +
 *   长时任务，属于另一个量级的改造。
 * - **不做锁屏控制**。
 *
 * ## 线程注意
 * TTS 回调可能不在 UI 线程。这里直接回调页面，与官方样例一致；
 * 若真机上出现状态更新异常，需要改为 `setTimeout` 投递回 UI 线程。
 */
export class Speech {
  private static engine: textToSpeech.TextToSpeechEngine | null = null;
  private static chunks: string[] = [];
  private static cursor: number = 0;
  private static active: boolean = false;
  private static speed: number = 1;
  private static onIndex: (index: number) => void = () => {
  };
  private static onFinish: () => void = () => {
  };

  static isActive(): boolean {
    return Speech.active;
  }

  static currentIndex(): number {
    return Speech.cursor;
  }

  /**
   * 从 `from` 段开始朗读。
   * @returns 是否成功开始（引擎创建失败返回 false，调用方需如实提示）
   */
  static async start(
    chunks: string[],
    from: number,
    speed: number,
    onIndex: (index: number) => void,
    onFinish: () => void,
  ): Promise<boolean> {
    Speech.stop();
    if (chunks.length === 0) {
      return false;
    }
    Speech.chunks = chunks;
    Speech.cursor = Math.max(0, Math.min(from, chunks.length - 1));
    Speech.speed = speed;
    Speech.onIndex = onIndex;
    Speech.onFinish = onFinish;

    const engine: textToSpeech.TextToSpeechEngine | null = await Speech.ensureEngine();
    if (engine === null) {
      return false;
    }
    Speech.active = true;
    Speech.speakCursor();
    return true;
  }

  /** 停止朗读并释放引擎（离开页面必须调用，否则会继续说）。 */
  static stop(): void {
    const engine: textToSpeech.TextToSpeechEngine | null = Speech.engine;
    Speech.active = false;
    Speech.chunks = [];
    Speech.cursor = 0;
    if (engine === null) {
      return;
    }
    try {
      engine.stop();
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '停止朗读失败：%{public}s', cause.message);
    }
  }

  /** 彻底释放引擎（应用退出/长时间不用时）。 */
  static shutdown(): void {
    Speech.stop();
    const engine: textToSpeech.TextToSpeechEngine | null = Speech.engine;
    Speech.engine = null;
    if (engine === null) {
      return;
    }
    try {
      engine.shutdown();
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '释放引擎失败：%{public}s', cause.message);
    }
  }

  private static async ensureEngine(): Promise<textToSpeech.TextToSpeechEngine | null> {
    const existing: textToSpeech.TextToSpeechEngine | null = Speech.engine;
    if (existing !== null) {
      return existing;
    }
    // 必须用**回调形式**：createEngine 的重载里既有回调版也有 Promise 版，
    // 直接 await 会得到 `void & Promise<TextToSpeechEngine>`，取不到正确类型
    // （编译期已实测）。
    const engine: textToSpeech.TextToSpeechEngine | null =
      await new Promise<textToSpeech.TextToSpeechEngine | null>((resolve) => {
        try {
          textToSpeech.createEngine(
            // person 为必填（0 = 默认发音人）；online: 0 = 离线引擎，
            // 离线是硬要求：通勤场景经常没网。
            { language: 'zh-CN', person: 0, online: 0 },
            (err: BusinessError, created: textToSpeech.TextToSpeechEngine) => {
              if (err) {
                hilog.error(DOMAIN, TAG, 'TTS 引擎创建失败：%{public}s', err.message);
                resolve(null);
                return;
              }
              resolve(created);
            },
          );
        } catch (err) {
          const cause: Error = err as Error;
          hilog.error(DOMAIN, TAG, 'TTS 引擎创建异常：%{public}s', cause.message);
          resolve(null);
        }
      });

    if (engine === null) {
      return null;
    }
    engine.setListener({
      onStart: () => {
        // 段落开始播报不需要额外动作：当前段落索引在 speak() 时已回调页面
      },
      onComplete: () => {
        Speech.advance();
      },
      onStop: () => {
        // 引擎被外部停止（含 stop()）：状态由调用方维护，这里不重复改
      },
      onError: () => {
        // 单段失败不应该让整篇静默中断：跳过这一句继续，并留日志
        hilog.warn(DOMAIN, TAG, '某一段朗读失败，跳过继续');
        Speech.advance();
      },
    });
    Speech.engine = engine;
    return engine;
  }

  /** 播下一段；已到末尾则收尾。 */
  private static advance(): void {
    if (!Speech.active) {
      return;
    }
    Speech.cursor = Speech.cursor + 1;
    if (Speech.cursor >= Speech.chunks.length) {
      Speech.active = false;
      Speech.onFinish();
      return;
    }
    const gap: number = GAP_MS;
    setTimeout(() => {
      if (Speech.active) {
        Speech.speakCursor();
      }
    }, gap);
  }

  private static speakCursor(): void {
    const engine: textToSpeech.TextToSpeechEngine | null = Speech.engine;
    if (engine === null || !Speech.active) {
      return;
    }
    const text: string = Speech.chunks[Speech.cursor];
    if (text === undefined || text.trim().length === 0) {
      Speech.advance();
      return;
    }
    try {
      engine.speak(text, {
        requestId: `kaogong-${Speech.cursor}-${Date.now()}`,
        extraParams: {
          'speed': Speech.speed,
          'volume': 1,
          'pitch': 1,
          'queueMode': 0,
        },
      });
      Speech.onIndex(Speech.cursor);
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '提交朗读失败：%{public}s', cause.message);
      Speech.advance();
    }
  }
}
