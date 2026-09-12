// 关系标注渲染层（正式版）：rough-notation 书写动画（中心句双括号 + 支撑句荧光笔）
// + Handy Arrows 素材箭头（矢量方向摆放，可换素材/旋转）。
// 交互规格见 docs/archive/2026-08/tasks/0024：编辑器先画荧光笔区域 → [ ] 吸附左右 → 箭头素材库自选 +
// 方向（up=锚定句最上行 / down=锚定句最下行）。渲染按当前 DOM 实时计算（响应式自适应）。
import rough from "roughjs";
import type { AiAnnotation, AiRelation } from "@kaogong/contracts";

// 全局样式（工作台「样式面板」写入 apps/web/public/relation-style.json，刷新生效）
interface RelationStyle {
  color: string; highlightColor: string; strokeWidth: number;
  highlightOpacity: number; defaultArrow: string; arrowSize: number; defaultDirection: "up" | "down";
}
const DEFAULT_STYLE: RelationStyle = {
  color: "#b2493a", highlightColor: "#e8b93c", strokeWidth: 2.8,
  highlightOpacity: 0.32, defaultArrow: "41.svg", arrowSize: 84, defaultDirection: "down",
};
let style: RelationStyle = { ...DEFAULT_STYLE };
async function loadStyle(): Promise<void> {
  try {
    const res = await fetch("/relation-style.json");
    if (res.ok) {
      const remote = (await res.json()) as Partial<RelationStyle>;
      style = { ...DEFAULT_STYLE, ...remote };
    }
  } catch { /* 保持默认 */ }
}
const ARROW_OFFSET = 12;           // 素材头与锚定行边缘的间隙

interface StyleSpec {
  arrow: string;
  rotate: number; // 素材整体旋转补偿（编辑器可调；0 = 按矢量自动计算）
}

/** 每个标注（中心句或支撑点）所属的关系簇 id 集合。 */
export function relationSpanMap(
  relations: AiRelation[],
  annotations: AiAnnotation[],
): Map<string, string[]> {
  const byId = new Map(annotations.map((a) => [a.id, a]));
  const map = new Map<string, string[]>();
  for (const rel of relations) {
    const anchor = byId.get(rel.anchor);
    if (!anchor || anchor.paragraphIndex !== rel.paragraphIndex) continue;
    if (!map.has(rel.anchor)) map.set(rel.anchor, []);
    map.get(rel.anchor)!.push(rel.id);
    for (const p of rel.points) {
      const point = byId.get(p.annotationId);
      if (!point) continue;
      if (!map.has(p.annotationId)) map.set(p.annotationId, []);
      map.get(p.annotationId)!.push(rel.id);
    }
  }
  return map;
}

/** 过滤掉引用失效的关系（锚点必须是观点/政策句标注且引用存在）。 */
export function validRelations(
  relations: AiRelation[] | undefined,
  annotations: AiAnnotation[],
): AiRelation[] {
  if (!relations) return [];
  const byId = new Map(annotations.map((a) => [a.id, a]));
  return relations.filter((rel) => {
    const anchor = byId.get(rel.anchor);
    if (!anchor) return false;
    if (anchor.paragraphIndex !== rel.paragraphIndex) return false;
    return rel.points.every((p) => byId.has(p.annotationId) && p.annotationId !== rel.anchor);
  });
}

export interface RelationDrawHandle {
  destroy(): void;
  redraw(): void;
}

/** 在文章容器内绘制关系标注（rough-notation + 素材箭头）。 */
export function drawRelationOverlay(
  container: HTMLElement,
  relations: AiRelation[],
  annotations: AiAnnotation[],
): RelationDrawHandle {
  const valid = validRelations(relations, annotations);
  const overlay = container.querySelector<SVGSVGElement>(".relation-overlay svg");
  if (!overlay || valid.length === 0) {
    return { destroy: () => {}, redraw: () => {} };
  }
  const svg: SVGSVGElement = overlay;
  const rc = rough.svg(svg);
  let raf = 0;
  // 素材缓存（渲染层保证一次性加载；编辑器换素材时重新 fetch）
  const arrowCache = new Map<string, string>();
  let annotationsOn = true;

  async function loadArrow(name: string): Promise<string> {
    const cached = arrowCache.get(name);
    if (cached) return cached;
    try {
      const res = await fetch(`/vendor/handy/${name}`);
      const text = await res.text();
      const colored = text
        .replace(/fill="black"/g, `fill="${style.color}"`)
        .replace(/fill="#000(?:000)?"/gi, `fill="${style.color}"`);
      arrowCache.set(name, colored);
      return colored;
    } catch {
      return "";
    }
  }

  function applyHlOpacity() {
    document.documentElement.style.setProperty("--rel-hl-opacity", String(style.highlightOpacity));
  }

  function clearNotation() {
    if (!annotationsOn) return;
    container.querySelectorAll(".rough-annotation").forEach((el) => el.remove());
    annotationsOn = false;
  }

  function applyNotation() {
    clearNotation();
    applyHlOpacity();
    // rough-notation 是可选增强：缓存一份 ESM 到 public/vendor（构建不打包 public）
    const moduleUrl: string = "/vendor/rough-notation.esm.js";
    const loadRoughNotation = () =>
      import(/* @vite-ignore */ moduleUrl) as Promise<
        { annotate: (el: HTMLElement, opts: unknown) => { show(): void; hide(): void } }
      >;
    loadRoughNotation().then(({ annotate }) => {
      for (const rel of valid) {
        const anchorEl = container.querySelector<HTMLElement>(
          `[data-annotation-id="${cssEscape(rel.anchor)}"]`,
        ) ?? container.querySelector<HTMLElement>(`[data-rel-ids*="${cssEscape(rel.id)}"]`);
        if (anchorEl) {
          annotate(anchorEl, {
            type: "bracket", brackets: ["left", "right"],
            color: style.color, strokeWidth: style.strokeWidth, padding: 6, animate: true,
          }).show();
        }
        for (const p of rel.points) {
          const pointEl = container.querySelector<HTMLElement>(
            `[data-annotation-id="${cssEscape(p.annotationId)}"]`,
          ) ?? container.querySelector<HTMLElement>(`[data-rel-ids*="${cssEscape(rel.id)}"]`);
          if (pointEl) {
            annotate(pointEl, {
              type: "highlight", color: style.highlightColor, strokeWidth: 8, padding: 2, animate: true,
            }).show();
          }
        }
      }
      annotationsOn = true;
    }).catch(() => {});
  }

  /** 素材箭头：尾对齐中心句右缘，头指向锚定行边缘（up=最上行 / down=最下行）。 */
  async function drawArrows(els: HTMLElement[]) {
    svg.replaceChildren();
    for (const rel of valid) {
      const anchorEl = els.find((el) => el.dataset.annotationId === rel.anchor)
        ?? els.find((el) => (el.dataset.relIds ?? "").split(",").includes(rel.id));
      if (!anchorEl) continue;
      const anchor = spanBox(anchorEl, container.getBoundingClientRect());
      if (!anchor) continue;
      for (const p of rel.points) {
        const pointEl = els.find((el) => el.dataset.annotationId === p.annotationId)
          ?? els.find((el) => (el.dataset.relIds ?? "").split(",").includes(rel.id));
        if (!pointEl) continue;
        const target = spanBox(pointEl, container.getBoundingClientRect());
        if (!target) continue;
        const pointStyle = (rel as { style?: Partial<StyleSpec> }).style ?? {};
        const arrowName = pointStyle.arrow ?? style.defaultArrow;
        const arrowSvg = await loadArrow(arrowName);
        if (!arrowSvg) continue;
        const from = { x: anchor.right + 12, y: anchor.cy };
        // 方向：up → 锚定句最上边缘；down → 最下边缘（用户拍板）
        const direction = (rel as { direction?: "up" | "down" }).direction ?? (style as RelationStyle).defaultDirection;
        const to = {
          x: target.cx,
          y: direction === "up" ? target.top - ARROW_OFFSET : target.bottom + ARROW_OFFSET,
        };
        placeArrow(arrowSvg, from, to, pointStyle.rotate ?? 0);
      }
    }
  }

  async function placeArrow(svgText: string, from: { x: number; y: number }, to: { x: number; y: number }, rotate: number) {
    const angle = (Math.atan2(to.y - from.y, to.x - from.x) * 180) / Math.PI + 90 + rotate;
    const wrapper = document.createElementNS("http://www.w3.org/2000/svg", "g");
    wrapper.setAttribute("transform", `translate(${from.x} ${from.y}) rotate(${angle})`);
    const holder = document.createElementNS("http://www.w3.org/2000/svg", "g");
    holder.innerHTML = svgText;
    const inner = holder.querySelector("svg") as SVGSVGElement | null;
    if (!inner) return;
    // 素材默认朝上：底部中心对齐 from，整体放大到 ARROW_SIZE
    const w = Number(inner.getAttribute("width") || 73);
    const h = Number(inner.getAttribute("height") || 72);
    const scale = style.arrowSize / Math.max(w, h);
    wrapper.setAttribute("transform", `translate(${from.x} ${from.y}) rotate(${angle}) translate(${-w / 2} ${-h}) scale(${scale})`);
    wrapper.setAttribute("opacity", "0.85");
    wrapper.appendChild(inner);
    svg.appendChild(wrapper);
  }

  function redraw() {
    if (!container.isConnected || !svg.isConnected) return;
    const containerRect = container.getBoundingClientRect();
    const els = Array.from(container.querySelectorAll<HTMLElement>("[data-rel-ids]")).filter(
      (el): el is HTMLElement => el instanceof HTMLElement,
    );
    svg.setAttribute("viewBox", `0 0 ${containerRect.width} ${containerRect.height}`);
    svg.setAttribute("width", String(containerRect.width));
    svg.setAttribute("height", String(containerRect.height));
    applyNotation();
    void drawArrows(els);
  }

  function schedule() {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(redraw);
  }

  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(schedule) : null;
  if (ro) ro.observe(container);
  window.addEventListener("resize", schedule);
  document.fonts.ready.then(schedule).catch(() => {});
  loadStyle().then(schedule);
  schedule();

  return {
    redraw: schedule,
    destroy: () => {
      ro?.disconnect();
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", schedule);
      clearNotation();
      svg.replaceChildren();
    },
  };
}

function spanBox(el: HTMLElement, containerRect?: DOMRect): { left: number; right: number; top: number; bottom: number; cx: number; cy: number } | null {
  const rect = el.getBoundingClientRect();
  if (!rect || rect.width === 0) return null;
  const ox = containerRect?.left ?? 0;
  const oy = containerRect?.top ?? 0;
  return {
    left: rect.left - ox, right: rect.right - ox,
    top: rect.top - oy, bottom: rect.bottom - oy,
    cx: rect.left + rect.width / 2 - ox, cy: rect.top + rect.height / 2 - oy,
  };
}

function cssEscape(value: string): string {
  return typeof CSS !== "undefined" && typeof CSS.escape === "function" ? CSS.escape(value) : value;
}
