// 今日复习：4 选 1 选择题 + 间隔重复（SRS）调度。
//
// ── 形态变更（用户 2026-09-16）──────────────────────────────
// 原先是「翻转卡 + 4 档自评」的问答卡。现在改成选择题。改的是**交互形态**，
// 不是数据源：题目直接复用每日一练的题集（content/<date>/practice.json）——
// 它天生就是 4 选 1，带 analysis（解析）、hint（提示）、traps（错因），
// 题量 103 题也远大于考点卡 30 张。
//
// ⚠️ 考点卡**不参与复习**，这是刻意的：它的答案是 30-80 字的整句
// （如「基本实现社会主义现代化「夯实基础、全面发力」的关键时期…」），
// 且同一卡组内答案高度重叠（15w-loc-001 与 15w-loc-002 都在讲「关键时期/承前启后」）。
// 拿同组答案当干扰项会出现「多个选项都看着对」的多解，那不是选择题，是猜谜。
//
// ── 提示方式变更 ─────────────────────────────────────────
// 原先页面一打开就自动弹遮罩（每日软闸门）。现在**不自动弹**，
// 改成页面顶部一条可关闭的提示条；点提示条或顶栏「复习」才进来。
//
// 卡片内容由构建时注入（Base.astro 读 content/<date>/practice.json），复习状态走 api（D1）。
import type { Api } from "./api";

const SKIP_KEY = "kaogong.review.skip";
const DONE_KEY = "kaogong.review.done";
const NOTICE_KEY = "kaogong.review.notice";
const NEW_PER_DAY = 5;

/** 一道可复习的题：练习题 + 它所属的日期。 */
export interface ReviewQuestion {
  /** 全局唯一键 `${date}:${question.id}`。
   *  ⚠️ 练习题 id 只在**当天内**唯一（每天都是 q1…q20），跨天直接碰撞，
   *  所以存进 D1 的 review_cards.cardId 前必须拼上日期。 */
  key: string;
  date: string;
  q: string;
  options: string[];
  answer: number;
  analysis: string;
  topic: string;
  hint?: string;
  traps?: string[];
}

/** 练习题集的题目形状（与 contracts 的 Question 对齐，这里只取复习要用的字段）。 */
export interface ReviewQuestionSource {
  id: string;
  q: string;
  options: string[];
  answer: number;
  analysis: string;
  topic: string;
  hint?: string;
  traps?: string[];
}

/**
 * 由某天的题集构造复习题列表（保持题集原顺序）。
 * 关键是拼出全局唯一 key —— 练习题 id 每天都是 q1…q20，不拼日期会跨天碰撞。
 */
export function toReviewQuestions(date: string, questions: ReviewQuestionSource[]): ReviewQuestion[] {
  return questions.map((q) => ({
    key: `${date}:${q.id}`,
    date,
    q: q.q,
    options: q.options,
    answer: q.answer,
    analysis: q.analysis,
    topic: q.topic,
    hint: q.hint,
    traps: q.traps,
  }));
}

const OPTION_KEYS = ["A", "B", "C", "D"] as const;

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function initReview(questions: ReviewQuestion[], api: Api) {
  if (questions.length === 0) return;
  const byKey = new Map(questions.map((q) => [q.key, q]));

  // —— 遮罩 DOM（挂到 body 末尾）——
  const overlay = document.createElement("div");
  overlay.className = "review-overlay";
  overlay.hidden = true;
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "今日复习");
  overlay.innerHTML = `
    <div class="review-card">
      <div class="review-head">
        <span class="review-title">今日复习</span>
        <span class="review-count" id="review-count"></span>
      </div>
      <div class="review-body">
        <p class="review-topic" id="review-topic"></p>
        <div class="review-question" id="review-question"></div>
        <p class="review-hint-text" id="review-hint-text" hidden></p>
        <div class="review-options" id="review-options"></div>
        <div class="review-feedback" id="review-feedback" hidden>
          <p class="review-verdict" id="review-verdict"></p>
          <p class="review-trap" id="review-trap" hidden></p>
          <p class="review-analysis" id="review-analysis"></p>
        </div>
      </div>
      <div class="review-actions">
        <button type="button" class="review-hint" id="review-hint" hidden>查看提示</button>
        <button type="button" class="review-next" id="review-next" hidden>下一题</button>
      </div>
      <button type="button" class="review-skip" id="review-skip">今日跳过</button>
    </div>
  `;
  document.body.appendChild(overlay);

  const countEl = overlay.querySelector<HTMLElement>("#review-count")!;
  const topicEl = overlay.querySelector<HTMLElement>("#review-topic")!;
  const questionEl = overlay.querySelector<HTMLElement>("#review-question")!;
  const hintTextEl = overlay.querySelector<HTMLElement>("#review-hint-text")!;
  const optionsEl = overlay.querySelector<HTMLElement>("#review-options")!;
  const feedbackEl = overlay.querySelector<HTMLElement>("#review-feedback")!;
  const verdictEl = overlay.querySelector<HTMLElement>("#review-verdict")!;
  const trapEl = overlay.querySelector<HTMLElement>("#review-trap")!;
  const analysisEl = overlay.querySelector<HTMLElement>("#review-analysis")!;
  const hintBtn = overlay.querySelector<HTMLButtonElement>("#review-hint")!;
  const nextBtn = overlay.querySelector<HTMLButtonElement>("#review-next")!;
  const skipBtn = overlay.querySelector<HTMLButtonElement>("#review-skip")!;

  let queue: ReviewQuestion[] = [];
  let index = 0;
  let answered = false;
  let busy = false;

  function hide() {
    overlay.hidden = true;
    document.body.style.overflow = "";
  }
  function show() {
    overlay.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function render() {
    if (index >= queue.length) {
      localStorage.setItem(DONE_KEY, today());
      hide();
      return;
    }
    const item = queue[index]!;
    answered = false;
    countEl.textContent = `${index + 1} / ${queue.length}`;
    topicEl.textContent = item.topic ? `考点：${item.topic}` : "";
    topicEl.hidden = !item.topic;
    questionEl.textContent = item.q;
    feedbackEl.hidden = true;
    nextBtn.hidden = true;
    nextBtn.disabled = false;
    nextBtn.textContent = index + 1 >= queue.length ? "完成" : "下一题";
    // 提示按钮：有 hint 才出；点开后按钮消失，提示文字原地展开在题干下方。
    // 提示内容与按钮状态都在 render() 里重置，切题不会把上一题的提示留在页面上。
    hintBtn.hidden = !item.hint;
    hintBtn.disabled = false;
    hintBtn.textContent = "查看提示";
    hintTextEl.hidden = true;
    hintTextEl.textContent = "";

    optionsEl.innerHTML = item.options
      .map((text, i) => `
        <button type="button" class="review-opt" data-i="${i}">
          <span class="review-opt__k">${OPTION_KEYS[i] ?? i + 1}</span>
          <span class="review-opt__t"></span>
        </button>`)
      .join("");
    // 选项文本用 textContent 写，避免题干里的 < > & 被当成标签
    optionsEl.querySelectorAll<HTMLElement>(".review-opt__t").forEach((el, i) => {
      el.textContent = item.options[i] ?? "";
    });
    show();
  }

  hintBtn.addEventListener("click", () => {
    const item = queue[index];
    if (!item?.hint) return;
    hintBtn.hidden = true;
    hintTextEl.textContent = `提示：${item.hint}`;
    hintTextEl.hidden = false;
  });

  optionsEl.addEventListener("click", async (e) => {
    const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("button[data-i]");
    const item = queue[index];
    if (!btn || !item || answered || busy) return;
    const chosen = Number(btn.dataset.i);
    const correct = chosen === item.answer;
    answered = true;

    // 判定：选中项标对/错，正确项始终标出来（答错时要知道正确答案是哪个）
    optionsEl.querySelectorAll<HTMLButtonElement>("button[data-i]").forEach((b) => {
      b.disabled = true;
      const i = Number(b.dataset.i);
      if (i === item.answer) b.classList.add("is-correct");
      else if (i === chosen) b.classList.add("is-wrong");
    });

    verdictEl.textContent = correct ? "答对了" : `答错了 · 正确答案是 ${OPTION_KEYS[item.answer] ?? ""}`;
    verdictEl.classList.toggle("is-wrong", !correct);
    // 错因只在答错时给，且取题目侧预生成的 traps[chosen]（运行期不做 AI 推断）
    const trap = !correct ? item.traps?.[chosen] : "";
    trapEl.hidden = !trap;
    trapEl.textContent = trap ? `错因：${trap}` : "";
    analysisEl.textContent = item.analysis ? `解析：${item.analysis}` : "";
    analysisEl.hidden = !item.analysis;
    feedbackEl.hidden = false;
    nextBtn.hidden = false;

    // SRS 评分：选择题没有自评档位，按对错折算 —— 对 = good，错 = again
    busy = true;
    await api.gradeReview({ cardId: item.key, rating: correct ? "good" : "again" });
    busy = false;
  });

  nextBtn.addEventListener("click", () => {
    index += 1;
    render();
  });

  skipBtn.addEventListener("click", () => {
    localStorage.setItem(SKIP_KEY, today());
    hide();
  });

  /** 组装本次要复习的队列：到期题（按 dueAt 升序）+ 每日新题（≤5）。 */
  async function buildQueue(): Promise<ReviewQuestion[]> {
    const state = await api.getReviewState();
    const rows = state.data?.cards ?? [];
    const known = new Set(rows.map((s) => s.cardId));
    const now = Date.now();
    const due = rows
      .filter((s) => s.dueAt <= now)
      .sort((a, b) => a.dueAt - b.dueAt)
      .map((s) => byKey.get(s.cardId))
      .filter((q): q is ReviewQuestion => !!q);
    const fresh = questions.filter((q) => !known.has(q.key)).slice(0, NEW_PER_DAY);
    return [...due, ...fresh];
  }

  async function start(force = false) {
    const t = today();
    if (!force && localStorage.getItem(SKIP_KEY) === t) return;
    queue = await buildQueue();
    index = 0;
    if (queue.length > 0) render();
  }

  // 「复习」入口：清除跳过标记后强制重算
  const entry = document.getElementById("review-entry");
  entry?.addEventListener("click", () => {
    localStorage.removeItem(SKIP_KEY);
    void start(true);
  });

  // —— 提示条（替代原先的自动弹窗）——
  // 不自动弹遮罩，只在页面顶部出一条可关闭的提示；当天关掉就不再出现。
  const notice = document.getElementById("review-notice");
  if (notice) {
    const text = notice.querySelector<HTMLElement>("#review-notice-text");
    const startBtn = notice.querySelector<HTMLButtonElement>("#review-notice-start");
    const closeBtn = notice.querySelector<HTMLButtonElement>("#review-notice-close");
    const openReview = () => {
      localStorage.removeItem(SKIP_KEY);
      void start(true);
    };
    startBtn?.addEventListener("click", openReview);
    closeBtn?.addEventListener("click", () => {
      localStorage.setItem(NOTICE_KEY, today());
      notice.hidden = true;
    });

    void (async () => {
      if (localStorage.getItem(NOTICE_KEY) === today()) return;
      if (localStorage.getItem(DONE_KEY) === today()) return;
      const q = await buildQueue();
      if (q.length === 0) return;
      if (text) text.textContent = `今日有 ${q.length} 道题目需要复习`;
      notice.hidden = false;
    })();
  }
}
