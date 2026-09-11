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

/** 卡片↔原文锚点。有它才能"回到原文"——这也是卡片可溯源的底线。 */
export interface CardAnchor {
  articleId: string;
  paragraphIndex: number;
}

/** 一张考点卡片（分发产物 `content/cards.json`）。 */
export interface ReviewCard {
  id: string;
  question: string;
  answer: string;
  /** 思路/逐项解析（可选）：管道生成后才有。 */
  explain?: string;
  tags: string[];
  /** 出处。人工卡组没有，管道从文章提炼的卡有。 */
  anchor?: CardAnchor;
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
/** 选项字母。 */
export const OPTION_LETTERS: string[] = ['A', 'B', 'C', 'D'];

/** 一个选项。 */
export interface Choice {
  text: string;
  correct: boolean;
}

/** 一道选择题（由卡片 + 同池其他卡片的答案构成）。 */
export interface QuizCard {
  id: string;
  question: string;
  tags: string[];
  options: Choice[];
  state: CardState;
  /**
   * true = 造不出 3 个合格干扰项，页面应退回「自评」模式。
   * 宁可降级，也不要出一道有两个正确选项的题。
   */
  fallback: boolean;
  /** 正确答案原文（判定后展示）。 */
  answer: string;
  /** 逐项解析；空串表示管道尚未生成，页面用「考点归属」给基础解析。 */
  explain: string;
  /** 出处文章 id；空串表示这张卡没有出处（人工卡组）。 */
  articleId: string;
}

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

  // ———————————————— 选择题构造 ————————————————

  /**
   * 把到期卡片变成 ABCD 选择题。
   *
   * ## 干扰项从哪来（不需要 AI、不需要新数据）
   * 用**同一题库里其他卡片的答案**当干扰项。这在时政选择里恰好是对的形态：
   * 错误选项也是这本政策里的正经表述，所以必须真的分清，而不是靠"读着不像"排除。
   *
   * ## 两条过滤（都用真实题库实测过，不是拍脑袋定的）
   * 1. **与正确答案的相似度 > 0.3 的不要**——实测 Q「十五五定位」与
   *    Q「十五五在现代化进程中的地位」两条答案的相似度高达 **0.806**，
   *    直接拿来当干扰项就会出现两个正确选项。这条是防坏题的关键。
   * 2. **长度要接近（相差不超过一半）**——否则"最长的那条就是答案"，
   *    不懂也能选对。
   *
   * ⚠️ **不要加"同 tag 不可用"**：我一开始加了，实测把可出题数从 30/30 压到 22/30——
   * 被挡掉的 8 张全是数字卡，而它们最合适的干扰项恰恰是**其他数字卡**
   * （「粮食产量」对「新能源汽车产量」），这正是真实时政选择题的形态。
   * 去掉后干扰项相似度最高仅 0.25，仍然安全。
   *
   * 找不到 3 个合格干扰项时**降级为自评模式**，而不是硬凑。
   */
  static buildQuiz(due: DueCard[], pool: ReviewCard[]): QuizCard[] {
    const out: QuizCard[] = [];
    for (const item of due) {
      const options: Choice[] = Review.optionsFor(item.card, pool);
      const explain: string | undefined = item.card.explain;
      const anchor: CardAnchor | undefined = item.card.anchor;
      out.push({
        id: item.card.id,
        question: item.card.question,
        tags: item.card.tags,
        answer: item.card.answer,
        options: options,
        state: item.state,
        fallback: options.length === 0,
        explain: explain === undefined ? '' : explain,
        articleId: anchor === undefined ? '' : anchor.articleId,
      });
    }
    return out;
  }

  /** 正确选项的字母（A/B/C/D）；找不到返回空串。 */
  static correctOptionLetter(question: QuizCard): string {
    for (let index = 0; index < question.options.length; index++) {
      if (question.options[index].correct && index < OPTION_LETTERS.length) {
        return OPTION_LETTERS[index];
      }
    }
    return '';
  }

  /** 造选项：正确项 + 最多 3 个干扰项。返回空数组表示无法造出合格题目。 */
  private static optionsFor(card: ReviewCard, pool: ReviewCard[]): Choice[] {
    const answer: string = card.answer.trim();
    if (answer.length === 0) {
      return [];
    }
    const distractors: string[] = [];
    for (const other of pool) {
      if (distractors.length >= 3) {
        break;
      }
      if (other.id === card.id) {
        continue;
      }
      const candidate: string = other.answer.trim();
      if (candidate.length === 0 || candidate === answer) {
        continue;
      }
      if (Review.similarity(answer, candidate) > 0.3) {
        continue;
      }
      if (!Review.lengthClose(answer, candidate)) {
        continue;
      }
      if (distractors.includes(candidate)) {
        continue;
      }
      distractors.push(candidate);
    }
    if (distractors.length < 3) {
      return [];
    }
    const all: Choice[] = [{ text: answer, correct: true }];
    for (const text of distractors) {
      all.push({ text: text, correct: false });
    }
    return Review.arrange(card.id, all);
  }

  /**
   * 选项定序：用**卡片 id 播种**的确定性洗牌（Fisher–Yates）。
   *
   * ## ⚠️ 这里修的是一个真实反馈："选项全是 C"
   * 原实现按 `hash(cardId + 选项文本)` 排序。问题在于：
   * **同一卡组的卡片，干扰项取自同一批答案，选项文本几乎完全一样**，
   * 而落位只由文本决定 → 组内正确答案的位置高度相关。
   * 实测前 8 题为 `B C C C A B C A`——用户连着看到几个 C，直接反馈"全是 C"。
   * （全局分布其实是均匀的 A:8 B:7 C:9 D:6，但**组内聚集**才是体感问题。）
   *
   * 改成由卡片 id 决定的置换：位置不再受文本支配，跨卡片独立且均匀。
   * 用确定性伪随机（同卡 id 结果稳定），避免每次进入题面跳位。
   */
  private static arrange(cardId: string, all: Choice[]): Choice[] {
    const out: Choice[] = all.slice();
    let state: number = Review.seedOf(cardId);
    for (let i = out.length - 1; i > 0; i--) {
      state = Review.nextRandom(state);
      const j: number = state % (i + 1);
      const swap: Choice = out[i];
      out[i] = out[j];
      out[j] = swap;
    }
    return out;
  }

  /** xorshift32：确定性、无依赖、跨平台一致。 */
  private static nextRandom(state: number): number {
    let x: number = state === 0 ? 0x9E3779B9 : state;
    x = x ^ (x << 13);
    x = x ^ (x >>> 17);
    x = x ^ (x << 5);
    const unsigned: number = x >>> 0;
    return unsigned === 0 ? 1 : unsigned;
  }

  /** FNV-1a：把卡片 id 折成 32 位种子（用 Math.imul 保证不丢精度）。 */
  private static seedOf(text: string): number {
    let value: number = 2166136261;
    for (let i = 0; i < text.length; i++) {
      value = Math.imul(value ^ text.charCodeAt(i), 16777619);
    }
    const unsigned: number = value >>> 0;
    return unsigned === 0 ? 1 : unsigned;
  }

  /** 字符二元组重合度（0~1）。用来判定"两个答案其实是同一句话"。 */
  private static similarity(left: string, right: string): number {
    const a: Set<string> = Review.bigrams(left);
    const b: Set<string> = Review.bigrams(right);
    if (a.size === 0 || b.size === 0) {
      return 0;
    }
    let hit: number = 0;
    a.forEach((gram: string) => {
      if (b.has(gram)) {
        hit = hit + 1;
      }
    });
    return hit / Math.min(a.size, b.size);
  }

  private static bigrams(text: string): Set<string> {
    const set: Set<string> = new Set<string>();
    for (let i = 0; i + 1 < text.length; i++) {
      set.add(text.substring(i, i + 2));
    }
    return set;
  }

  /** 长度接近（相差不超过一半）——避免"最长即答案"。 */
  private static lengthClose(answer: string, candidate: string): boolean {
    const longer: number = Math.max(answer.length, candidate.length);
    const shorter: number = Math.min(answer.length, candidate.length);
    return shorter * 2 >= longer;
  }

  private static statePath(): string | null {
    const context = Settings.context();
    if (context === null) {
      return null;
    }
    return `${context.filesDir}/${STATE_FILE}`;
  }
}
