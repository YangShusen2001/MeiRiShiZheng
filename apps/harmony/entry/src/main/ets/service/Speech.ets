import { textToSpeech } from '@kit.CoreSpeechKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Settings } from './Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongSpeech';
/** 段落之间的停顿：纯 TTS 连读没有换气感，听起来像机器报菜名。 */
const GAP_MS: number = 320;

/**
 * ⚠️ SDK 的取值语义**反直觉**，原文：
 * `The value 0 indicates online, value 1 indicates offline.`
 *
 * 此前的实现写的是 `online: 0` 并注释成"离线引擎"——**恰好写反了**，
 * 等于一直在用在线引擎却声称离线可用，没网时直接不可用。
 * 现在默认离线（通勤场景），在线音质由设置决定。
 */
const ENGINE_ONLINE: number = 0;
const ENGINE_OFFLINE: number = 1;

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
/** 设备上可用的发音人。 */
export interface VoiceOption {
  /** 传给 createEngine 的 person 值。 */
  person: number;
  /** 展示用名称（设备给的描述 + 性别/风格）。 */
  label: string;
}

export class Speech {
  private static engine: textToSpeech.TextToSpeechEngine | null = null;
  /** 当前引擎是在线还是离线——模式切换时必须重建引擎（online 是建引擎时的参数）。 */
  private static engineOnline: boolean = false;
  /** 当前引擎用的发音人——换发音人同样必须重建引擎（person 也是建引擎时的参数）。 */
  private static enginePerson: number = 0;
  /** 在线引擎不可用、已回退到离线。页面据此如实提示，不静默改变音色。 */
  private static usingOfflineFallback: boolean = false;
  /**
   * 本次会话内强制离线。
   *
   * 「在线」的失败**不在建引擎时发生**：引擎能建起来，但合成时因为没网而报错。
   * 所以回退必须由**朗读失败**触发；回退后本会话不再尝试在线，
   * 但**不改用户的设置**（设置是他的偏好，失败是当下环境的问题）。
   */
  private static forcedOffline: boolean = false;
  /** 本次朗读的起始段（用于判断"是否首段就失败"）。 */
  private static startCursor: number = 0;

  /** 上次启动是否发生了"在线 → 离线"回退。 */
  static didFallbackToOffline(): boolean {
    return Speech.usingOfflineFallback;
  }

  /**
   * 列出设备上可用的中文发音人。
   *
   * 为什么不预置一份"童声 / 女声"列表：**可用发音人由设备与系统版本决定**，
   * 写死的 person 值在别的机器上可能直接报 `1002300003 The person is not supported`。
   * 枚举出来让用户选，才是可用的做法。
   */
  static listVoices(): Promise<VoiceOption[]> {
    // 模块级 listVoices 只有 Promise 形式（回调形式在引擎实例上），
    // 所以这里不能照抄 createEngine 的回调写法（编译期已实测）。
    // online 同样必填，且**要与实际朗读用的模式一致**——否则列出的发音人可能用不了。
    const online: boolean = Settings.speakOnline() && !Speech.forcedOffline;
    return textToSpeech.listVoices({
      requestId: `kaogong-voices-${Date.now()}`,
      online: online ? ENGINE_ONLINE : ENGINE_OFFLINE,
    }).then(
      (voices: textToSpeech.VoiceInfo[]): VoiceOption[] => {
        const out: VoiceOption[] = [];
        if (voices === undefined) {
          return out;
        }
        for (const voice of voices) {
          if (voice.language !== 'zh-CN') {
            continue;
          }
          const bits: string[] = [];
          const desc: string = voice.description === undefined ? '' : voice.description;
          if (desc.length > 0) {
            bits.push(desc);
          }
          const gender: string = voice.gender === undefined ? '' : voice.gender;
          if (gender.length > 0) {
            bits.push(gender);
          }
          const style: string = voice.style === undefined ? '' : voice.style;
          if (style.length > 0) {
            bits.push(style);
          }
          const label: string = bits.length > 0 ? bits.join(' · ') : `发音人 ${voice.person}`;
          out.push({ person: voice.person, label: label });
        }
        return out;
      },
      (err: Error): VoiceOption[] => {
        hilog.warn(DOMAIN, TAG, '枚举发音人失败：%{public}s', err.message);
        return [];
      },
    );
  }
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
    Speech.startCursor = Speech.cursor;
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
    // 本会话已判定在线不可用 → 直接离线，不再重试（否则每段都白等一次超时）
    const wantOnline: boolean = Settings.speakOnline() && !Speech.forcedOffline;
    const existing: textToSpeech.TextToSpeechEngine | null = Speech.engine;
    const wantPerson: number = Settings.speakPerson();
    if (existing !== null) {
      // online 与 person 都只在 createEngine 时生效，任一变化都要重建
      if (Speech.engineOnline === wantOnline && Speech.enginePerson === wantPerson) {
        return existing;
      }
      Speech.shutdown();
    }
    Speech.usingOfflineFallback = false;
    const engine: textToSpeech.TextToSpeechEngine | null = await Speech.create(wantOnline);
    if (engine === null && wantOnline) {
      // 在线引擎依赖华为云端语音服务：无网或服务不可用时**回退离线**，
      // 而不是让"朗读"整个不可用。页面据 didFallbackToOffline() 如实提示。
      hilog.warn(DOMAIN, TAG, '在线引擎不可用，回退离线引擎');
      const fallback: textToSpeech.TextToSpeechEngine | null = await Speech.create(false);
      if (fallback !== null) {
        Speech.usingOfflineFallback = true;
        Speech.engine = fallback;
        Speech.engineOnline = false;
      }
      return fallback;
    }
    if (engine !== null) {
      Speech.engine = engine;
      Speech.engineOnline = wantOnline;
      Speech.enginePerson = wantPerson;
    }
    return engine;
  }

  /** 创建引擎（回调形式；失败返回 null，不抛）。 */
  private static create(online: boolean): Promise<textToSpeech.TextToSpeechEngine | null> {
    // 必须用**回调形式**：createEngine 的重载里既有回调版也有 Promise 版，
    // 直接 await 会得到 `void & Promise<TextToSpeechEngine>`，取不到正确类型
    // （编译期已实测）。
    return new Promise<textToSpeech.TextToSpeechEngine | null>((resolve) => {
      try {
        textToSpeech.createEngine(
          // person 由设置决定（默认 0 = 系统默认发音人）；可用发音人由设备决定，
          // 用 listVoices 枚举后让用户选，不写死。
          // online：**0 = 在线，1 = 离线**（见文件头注释）。
          {
            language: 'zh-CN',
            person: Settings.speakPerson(),
            online: online ? ENGINE_ONLINE : ENGINE_OFFLINE,
          },
          (err: BusinessError, created: textToSpeech.TextToSpeechEngine) => {
            if (err) {
              hilog.error(DOMAIN, TAG, 'TTS 引擎创建失败（online=%{public}s）：%{public}s',
                online ? 'true' : 'false', err.message);
              resolve(null);
              return;
            }
            created.setListener(Speech.listener());
            resolve(created);
          },
        );
      } catch (err) {
        const cause: Error = err as Error;
        hilog.error(DOMAIN, TAG, 'TTS 引擎创建异常：%{public}s', cause.message);
        resolve(null);
      }
    });
  }

  private static listener(): textToSpeech.SpeakListener {
    return {
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
        // 在线的失败发生在**合成**阶段（引擎能建起来，没网时朗读才报错），
        // 所以回退必须由这里触发，而不是建引擎失败时。
        hilog.warn(DOMAIN, TAG, '朗读失败（在线=%{public}s，第 %{public}d 段）',
          Speech.engineOnline ? 'true' : 'false', Speech.cursor);
        if (Speech.engineOnline && Speech.cursor === Speech.startCursor) {
          // 首段就失败 → 判定在线不可用：回退离线并从同一段重来（不让用户白点一次）
          Speech.relaunchOffline(Speech.cursor);
          return;
        }
        // 其它情况：单段失败不该让整篇静默中断，跳过这一句继续
        Speech.advance();
      },
    };
  }

  /** 回退到离线引擎，并从 `resumeAt` 段重新开始。 */
  private static async relaunchOffline(resumeAt: number): Promise<void> {
    const chunks: string[] = Speech.chunks;
    const speed: number = Speech.speed;
    const onIndex: (index: number) => void = Speech.onIndex;
    const onFinish: () => void = Speech.onFinish;
    Speech.shutdown();
    Speech.forcedOffline = true;
    Speech.usingOfflineFallback = true;
    const engine: textToSpeech.TextToSpeechEngine | null = await Speech.create(false);
    if (engine === null) {
      onFinish();
      return;
    }
    Speech.engine = engine;
    Speech.engineOnline = false;
    Speech.enginePerson = Settings.speakPerson();
    Speech.chunks = chunks;
    Speech.cursor = resumeAt;
    Speech.startCursor = resumeAt;
    Speech.speed = speed;
    Speech.onIndex = onIndex;
    Speech.onFinish = onFinish;
    Speech.active = true;
    // 通知一次当前段，页面据此把高亮挪回来
    onIndex(resumeAt);
    Speech.speakCursor();
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
