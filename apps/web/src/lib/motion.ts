// 动效统一入口（P2）：CSS 优先，anime.js 只做需要 JS 编排的场景（stagger / spring / 数字滚动）。
// 数值标准：提案 0017 §3（emilkowalski/skills STANDARDS）——禁止自造曲线/时长。
// 渐进增强：motionEnabled() 为 false 时所有函数为 no-op（无 JS 依赖时页面照常显示）。
import { animate, stagger, Spring } from "animejs";

/** 与 global.css --ease-out 同一曲线（anime 的 cubicBezier 语法） */
export const EASE_OUT = "cubicBezier(0.23, 1, 0.32, 1)";

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** 动效仅在桌面端启用：reduced-motion 关闭；移动端零动画（性能优先 + 触控优先，P2 验收） */
export function motionEnabled(): boolean {
  return typeof window !== "undefined" && !prefersReducedMotion() && window.matchMedia("(min-width: 769px)").matches;
}

/**
 * 组入场 stagger：元素初始 opacity 0 + 上移 8px，进入视口后按间隔依次淡入（IO once，不重播）。
 * 装饰性动画，不阻塞交互；仅桌面端生效。
 */
export function staggerReveal(
  scope: ParentNode,
  selector: string,
  opts: { gap?: number; duration?: number } = {},
): void {
  if (!motionEnabled()) return;
  const items = Array.from(scope.querySelectorAll<HTMLElement>(selector));
  if (items.length === 0) return;
  const { gap = 40, duration = 300 } = opts;
  for (const el of items) {
    el.style.opacity = "0";
    el.style.transform = "translateY(8px)";
  }
  const io = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return;
      io.disconnect();
      animate(items, {
        opacity: [0, 1],
        translateY: [8, 0],
        delay: stagger(gap),
        duration,
        ease: EASE_OUT,
      });
    },
    { threshold: 0.05, rootMargin: "0px 0px -40px 0px" },
  );
  items.forEach((el) => io.observe(el));
}

/**
 * 数字滚动：从当前文本数值滚到目标值（600ms ease-out）。
 * reduced-motion / 移动端下直接落最终值。
 */
export function countUp(el: HTMLElement, to: number, opts: { duration?: number } = {}): void {
  if (!motionEnabled()) {
    el.textContent = String(to);
    return;
  }
  const { duration = 600 } = opts;
  const from = Number(el.textContent) || 0;
  if (from === to) return;
  const target = { v: from };
  animate(target, {
    v: to,
    duration,
    ease: EASE_OUT,
    update: () => {
      el.textContent = String(Math.round(target.v));
    },
  });
}

/**
 * delight：spring 弹出（Emil Apple 风格 {duration:0.5, bounce:0.2}，bounce 0.1–0.3）。
 * 仅用于稀有/首次场景（练习完成等），bounce 保持克制。
 */
export function springPop(
  el: HTMLElement,
  opts: { from?: number; duration?: number; bounce?: number } = {},
): void {
  if (!motionEnabled()) return;
  const { from = 0.9, duration = 0.5, bounce = 0.2 } = opts;
  animate(el, {
    scale: [from, 1],
    opacity: [0, 1],
    duration: Math.max(300, duration * 1000),
    ease: new Spring({ duration, bounce }),
  });
}
