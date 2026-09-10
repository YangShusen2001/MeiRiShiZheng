import type { AiAnnotation } from "@kaogong/contracts";
import { buildSegments, type Span } from "./highlights";

interface ReaderSegment {
  text: string;
  userStyles: Span["styles"];
  aiAnnotations: AiAnnotation[];
  /** 该 segment 覆盖的关系标注 id（多簇合并，逗号拼接输出）。 */
  relIds: string[];
  /** 与 segment 区间精确一致的标注 id（关系箭头锚点渲染用）。 */
  annotationExact?: string;
  note?: string;
  explanation?: string;
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Ignore stale or malformed AI offsets instead of marking unrelated article text. */
export function validAiAnnotations(text: string, annotations: AiAnnotation[]): AiAnnotation[] {
  return annotations.filter((annotation) =>
    ["viewpoint", "exam_point", "term", "figure"].includes(annotation.type) &&
    Number.isInteger(annotation.start)
    && Number.isInteger(annotation.end)
    && annotation.start >= 0
    && annotation.start < annotation.end
    && annotation.end <= text.length
    && text.slice(annotation.start, annotation.end) === annotation.text,
  );
}

export function buildReaderSegments(
  text: string,
  userSpans: Span[],
  aiAnnotations: AiAnnotation[],
  relByAnnotation?: Map<string, string[]>,
): ReaderSegment[] {
  const validAi = validAiAnnotations(text, aiAnnotations);
  const boundaries = new Set<number>([0, text.length]);
  for (const span of userSpans) {
    boundaries.add(Math.min(Math.max(span.start, 0), text.length));
    boundaries.add(Math.min(Math.max(span.end, 0), text.length));
  }
  for (const annotation of validAi) {
    boundaries.add(annotation.start);
    boundaries.add(annotation.end);
  }

  const relIdsFor = (start: number, end: number): string[] => {
    const ids = new Set<string>();
    if (!relByAnnotation) return [];
    for (const annotation of validAi) {
      if (annotation.start <= start && end <= annotation.end) {
        for (const relId of relByAnnotation.get(annotation.id) ?? []) ids.add(relId);
      }
    }
    return [...ids];
  };

  const sorted = [...boundaries].sort((a, b) => a - b);
  const userSegments = buildSegments(text, userSpans);
  const segments: ReaderSegment[] = [];
  let userOffset = 0;
  for (let i = 0; i < sorted.length - 1; i++) {
    const start = sorted[i]!;
    const end = sorted[i + 1]!;
    if (start === end) continue;
    while (userOffset + (userSegments[0]?.text.length ?? 0) <= start && userSegments.length > 1) {
      userOffset += userSegments.shift()!.text.length;
    }
    const exact = validAi.find(
      (annotation) => annotation.start === start && annotation.end === end,
    );
    segments.push({
      text: text.slice(start, end),
      userStyles: userSegments[0]?.styles ?? [],
      aiAnnotations: validAi.filter((annotation) => annotation.start <= start && end <= annotation.end),
      relIds: relIdsFor(start, end),
      annotationExact: exact?.id,
      note: userSegments[0]?.note,
      explanation: userSegments[0]?.explanation,
    });
  }
  return segments;
}

export function readerSegmentsToHtml(segments: ReaderSegment[]): string {
  return segments.map((segment) => {
    const text = escapeHtml(segment.text);
    const classes = [
      ...segment.userStyles.map((style) => `hl-${style}`),
      ...new Set(segment.aiAnnotations.map((annotation) => `ai-${annotation.type.replace("_", "-")}`)),
    ];
    if (!classes.length && !segment.relIds.length) return text;

    const term = segment.aiAnnotations.find((annotation) => annotation.type === "term" && annotation.explanation);
    const attributes = [`class="${classes.join(" ")}"`];
    if (segment.relIds.length) {
      attributes.push(`data-rel-ids="${segment.relIds.join(",")}"`);
    }
    if (segment.annotationExact) {
      attributes.push(`data-annotation-id="${escapeHtml(segment.annotationExact)}"`);
    }
    if (segment.userStyles.length) {
      attributes.push('data-user-highlight="true"');
      if (segment.explanation) {
        attributes.push('tabindex="0"', `data-explanation="${escapeHtml(segment.explanation)}"`);
      }
    }
    // 用户 AI 解析优先于静态术语释义（避免覆盖）；术语仍保留 aria-label 描述。
    if (term?.explanation && !segment.explanation) {
      attributes.push('tabindex="0"', `data-explanation="${escapeHtml(term.explanation)}"`);
      attributes.push(`aria-label="${escapeHtml(`${term.text}：${term.explanation}`)}"`);
    }
    // 术语收藏（0018）：整个术语可点击收藏，携带术语文本/释义供阅读页交互
    if (segment.aiAnnotations.some((annotation) => annotation.type === "term")) {
      attributes.push(`data-term-text="${escapeHtml(term?.text ?? "")}"`);
      if (term?.explanation) attributes.push(`data-term-expl="${escapeHtml(term.explanation)}"`);
    }
    const tag = segment.userStyles.length ? "mark" : "span";
    return `<${tag} ${attributes.join(" ")}>${text}</${tag}>`;
  }).join("");
}
