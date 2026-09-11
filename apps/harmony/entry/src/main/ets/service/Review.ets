import { fileIo as fs } from '@kit.CoreFileKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { Endpoints } from '../config/Endpoints';
import { Cache, CacheEntry } from './Cache';
import { Loaded } from './ContentService';
import { HttpClient } from './Http';
import { Settings } from './Settings';

const DOMAIN: number = 0x0000;
const TAG: string = 'KaogongReview';
const STATE_FILE: string = 'review-state.json';

/** 一张考点卡片（分发产物 `content/cards.json`）。 */
export interface ReviewCard {
  id: string;
  question: string;
  answer: string;
  tags: string[];
}

/** 单卡复习进度。 */
export interface CardState {
  /** 下次到期时间（ms 时间戳）。 */
  due: number;
  /** 当前间隔（天）。 */
  intervalDays: number;
  /** 难度系数（SM-2 的 EF）。 */
  ease: number;
  /** 连续答对次数。 */
  reps: number;
}

/** 评分档位。 */
export const GRADE_FORGOT: number = 0;
export const GRADE_RECALLED: number = 1;
export const GRADE_EASY: number = 2;

/**
 * 单卡的进度记录。
 * 用「数组 + Map」而不是 `{[id]: state}`：ArkTS 禁止索引签名
 * （`arkts-no-indexed-signatures`）与下标访问属性（`arkts-no-props-by-index`），
 * 编译期已实测。数组负责 JSON 持久化，Map 负责查询。
 */
export interface CardProgress {
  id: string;
  state: CardState;
}

/** 本次会话要复习的卡（卡片 + 它的到期状态）。 */
export interface DueCard {
  card: ReviewCard;
  state: CardState;
  /** 是否首次复习（从未评过分）。 */
  fresh: boolean;
}

/**
 * 考点复习（间隔重复）。
 *
 * ## 为什么调度器放在端上、进度也存端上
 * 服务端 `/api/review` 是**按登录用户**的。原生端当前没有登录入口，
 * 走服务端就得先做全套账号体系。而复习这件事**天然适合本地**：
 * 离线可用（通勤场景）、零延迟、不依赖账号。
 * 跨端同步留到有账号体系之后再做——那时把本地进度上行即可。
 *
 * ## 调度算法：v1 用 SM-2，不是 FSRS
 * 产品文档写的是 FSRS。这里先用 SM-2，理由是**可验证**：
 * SM-2 规则确定、无参数拟合，好核对；FSRS 需要一组训练好的参数，
 * 而且**必须与 Web 端 `ts-fsrs` 对齐**，否则同一个人在两端会看到不同的排程。
 * 对齐工作留到下一步，不在这里半途实现一个"像 FSRS 但不是 FSRS"的东西。
 */
export class Review {
  /** 当天开始时间（复习到期以"天"为粒度，同一天内不该反复变）。 */
  private static dayStart(): number {
    const now: Date = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  }

  /** 全新卡片：当天到期（新卡当天就该学）。 */
  static freshState(): CardState {
    return { due: Review.dayStart(), intervalDays: 0, ease: 2.5, reps: 0 };
  }

  /**
   * SM-2 排程。`grade` 用三档，映射到 SM-2 的 quality：
   * 忘了→2、想起→4、太简单→5。
   *
   * 「忘了」不排到明天：间隔归零并在 **10 分钟后**再出现——
   * 当天就补一次，比"明天再说"有效得多（也符合 Anki 的做法）。
   */
  static schedule(state: CardState, grade: number, now: number = Date.now()): CardState {
    const quality: number = grade === GRADE_FORGOT ? 2 : (grade === GRADE_RECALLED ? 4 : 5);
    if (quality < 3) {
      return {
        due: now + 10 * 60 * 1000,
        intervalDays: 0,
        ease: state.ease,
        reps: 0,
      };
    }
    let reps: number = state.reps + 1;
    let intervalDays: number;
    if (reps === 1) {
      intervalDays = 1;
    } else if (reps === 2) {
      intervalDays = 6;
    } else {
      intervalDays = Math.max(1, Math.round(state.intervalDays * state.ease));
    }
    let ease: number = state.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02));
    if (ease < 1.3) {
      ease = 1.3;
    }
    return {
      due: now + intervalDays * 24 * 60 * 60 * 1000,
      intervalDays: intervalDays,
      ease: ease,
      reps: reps,
    };
  }

  /** 拉取卡片（走缓存，离线可用）。 */
  static loadCards(): Promise<Loaded<ReviewCard[]>> {
    return HttpClient.getJson<ReviewCard[]>(Endpoints.cardsUrl()).then(
      (data: ReviewCard[]): Loaded<ReviewCard[]> => {
        Cache.write(Endpoints.cardsUrl(), JSON.stringify(data));
        return { data: data, cached: false, savedAt: Date.now() };
      },
      (err: Error): Loaded<ReviewCard[]> => {
        const entry: CacheEntry | null = Cache.read(Endpoints.cardsUrl());
        if (entry !== null) {
          try {
            const cached: ReviewCard[] = JSON.parse(entry.text) as ReviewCard[];
            return { data: cached, cached: true, savedAt: entry.savedAt };
          } catch (parseErr) {
            // 缓存损坏 → 当作没有
          }
        }
        throw err;
      },
    );
  }

  static readState(): CardProgress[] {
    const path: string | null = Review.statePath();
    if (path === null) {
      return [];
    }
    try {
      if (!fs.accessSync(path)) {
        return [];
      }
      return JSON.parse(fs.readTextSync(path)) as CardProgress[];
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '读取复习进度失败（视为全新）：%{public}s', cause.message);
      return [];
    }
  }

  static writeState(progress: CardProgress[]): void {
    const path: string | null = Review.statePath();
    if (path === null) {
      return;
    }
    try {
      const file: fs.File = fs.openSync(path, fs.OpenMode.READ_WRITE | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      try {
        fs.writeSync(file.fd, JSON.stringify(progress));
      } finally {
        fs.closeSync(file);
      }
    } catch (err) {
      const cause: Error = err as Error;
      hilog.warn(DOMAIN, TAG, '写入复习进度失败（不影响本次复习）：%{public}s', cause.message);
    }
  }

  /** 进度数组 → 查询用 Map。 */
  static stateMap(progress: CardProgress[]): Map<string, CardState> {
    const map: Map<string, CardState> = new Map<string, CardState>();
    for (const item of progress) {
      map.set(item.id, item.state);
    }
    return map;
  }

  /** 记一次评分：读改写。 */
  static record(cardId: string, grade: number): CardState {
    const progress: CardProgress[] = Review.readState();
    let next: CardState | null = null;
    for (const item of progress) {
      if (item.id === cardId) {
        item.state = Review.schedule(item.state, grade);
        next = item.state;
        break;
      }
    }
    if (next === null) {
      next = Review.schedule(Review.freshState(), grade);
      progress.push({ id: cardId, state: next });
    }
    Review.writeState(progress);
    return next;
  }

  /** 挑出到期卡片。新卡排在旧的之后——先复习旧的，再看新的。 */
  static dueCards(cards: ReviewCard[], progress: CardProgress[], now: number = Date.now()): DueCard[] {
    const map: Map<string, CardState> = Review.stateMap(progress);
    const due: DueCard[] = [];
    const fresh: DueCard[] = [];
    for (const card of cards) {
      const state: CardState | undefined = map.get(card.id);
      if (state === undefined) {
        if (Review.freshState().due <= now) {
          fresh.push({ card: card, state: Review.freshState(), fresh: true });
        }
        continue;
      }
      if (state.due <= now) {
        due.push({ card: card, state: state, fresh: false });
      }
    }
    return due.concat(fresh);
  }

  private static statePath(): string | null {
    const context = Settings.context();
    if (context === null) {
      return null;
    }
    return `${context.filesDir}/${STATE_FILE}`;
  }
}
