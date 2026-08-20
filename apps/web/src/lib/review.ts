// 考点卡片复习：毛玻璃遮罩 + 翻转卡片 + 4 档自评 + 软闸门（今日跳过）。
// 卡片内容由构建时注入（Base.astro 读 content/cards），复习状态走 api（D1）。
import type { ReviewCard } from "@kaogong/contracts";
import type { Api } from "./api";

const SKIP_KEY = "kaogong.review.skip";
const DONE_KEY = "kaogong.review.done";
const NEW_CARDS_PER_DAY = 5;

const RATINGS = [
  { key: "again", label: "忘了" },
  { key: "hard", label: "模糊" },
  { key: "good", label: "会了" },
  { key: "easy", label: "轻松" },
] as const;

type RatingKey = (typeof RATINGS)[number]["key"];

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function initReview(cards: ReviewCard[], api: Api) {
  if (cards.length === 0) return;
  const cardById = new Map(cards.map((c) => [c.id, c]));

  // —— 遮罩 DOM（挂到 body 末尾）——
  const overlay = document.createElement("div");
  overlay.className = "review-overlay";
  overlay.hidden = true;
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML = `
    <div class="review-card">
      <div class="review-head">
        <span class="review-title">今日复习</span>
        <span class="review-count" id="review-count"></span>
      </div>
      <div class="review-body">
        <div class="review-question" id="review-question"></div>
        <div class="review-answer" id="review-answer" hidden></div>
      </div>
      <div class="review-actions">
        <button type="button" class="review-flip" id="review-flip">翻面看答案</button>
        <div class="review-grade" id="review-grade" hidden>
          ${RATINGS.map((r) => `<button type="button" data-rating="${r.key}">${r.label}</button>`).join("")}
        </div>
      </div>
      <button type="button" class="review-skip" id="review-skip">今日跳过</button>
    </div>
  `;
  document.body.appendChild(overlay);

  const countEl = overlay.querySelector<HTMLElement>("#review-count")!;
  const questionEl = overlay.querySelector<HTMLElement>("#review-question")!;
  const answerEl = overlay.querySelector<HTMLElement>("#review-answer")!;
  const flipBtn = overlay.querySelector<HTMLButtonElement>("#review-flip")!;
  const gradeEl = overlay.querySelector<HTMLElement>("#review-grade")!;
  const skipBtn = overlay.querySelector<HTMLButtonElement>("#review-skip")!;

  let queue: ReviewCard[] = [];
  let index = 0;
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
    const card = queue[index]!;
    countEl.textContent = `${index + 1} / ${queue.length}`;
    questionEl.textContent = card.question;
    answerEl.textContent = card.answer;
    answerEl.hidden = true;
    flipBtn.hidden = false;
    gradeEl.hidden = true;
    show();
  }

  flipBtn.addEventListener("click", () => {
    answerEl.hidden = false;
    flipBtn.hidden = true;
    gradeEl.hidden = false;
  });

  gradeEl.addEventListener("click", async (e) => {
    const btn = (e.target as HTMLElement).closest("button[data-rating]") as HTMLButtonElement | null;
    if (!btn || btn.disabled || busy) return;
    const rating = btn.dataset.rating as RatingKey;
    const card = queue[index];
    if (!card) return;
    busy = true;
    btn.disabled = true;
    const res = await api.gradeReview({ cardId: card.id, rating });
    busy = false;
    if (res.ok) {
      index += 1;
      render();
    } else {
      btn.disabled = false;
    }
  });

  skipBtn.addEventListener("click", () => {
    localStorage.setItem(SKIP_KEY, today());
    hide();
  });

  async function start(force = false) {
    const t = today();
    if (!force && (localStorage.getItem(SKIP_KEY) === t || localStorage.getItem(DONE_KEY) === t)) return;

    const state = await api.getReviewState();
    const rows = state.data?.cards ?? [];
    const known = new Set(rows.map((s) => s.cardId));
    const now = Date.now();

    // 到期卡（按 dueAt 升序）+ 每日新卡（未学过的按文件顺序，≤5 张）
    const due = rows
      .filter((s) => s.dueAt <= now)
      .sort((a, b) => a.dueAt - b.dueAt)
      .map((s) => cardById.get(s.cardId))
      .filter((c): c is ReviewCard => !!c);
    const fresh = cards.filter((c) => !known.has(c.id)).slice(0, NEW_CARDS_PER_DAY);

    queue = [...due, ...fresh];
    index = 0;
    if (queue.length > 0) render();
  }

  // 「复习」入口：清除跳过标记后强制重算
  const entry = document.getElementById("review-entry");
  entry?.addEventListener("click", () => {
    localStorage.removeItem(SKIP_KEY);
    localStorage.removeItem(DONE_KEY);
    void start(true);
  });

  void start();
}
