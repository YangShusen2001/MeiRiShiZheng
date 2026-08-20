import type { AiAnnotation } from "@kaogong/contracts";
import { buildSegments, type Span } from "./highlights";

interface ReaderSegment {
  text: string;
  userStyles: Span["styles"];
  aiAnnotations: AiAnnotation[];
  note?: string;
  explanation?: string;
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Ignore stale or malformed AI offsets instead of marking unrelated article text. */
export function validAiAnnotations(text: string, annotations: AiAnnotation[]): AiAnnotation[] {
  return annotations.filter((annotation) =>
    ["viewpoint", "exam_point", "term"].includes(annotation.type) &&
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
    segments.push({
      text: text.slice(start, end),
      userStyles: userSegments[0]?.styles ?? [],
      aiAnnotations: validAi.filter((annotation) => annotation.start <= start && end <= annotation.end),
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
    if (!classes.length) return text;

    const term = segment.aiAnnotations.find((annotation) => annotation.type === "term" && annotation.explanation);
    const attributes = [`class="${classes.join(" ")}"`];
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
    const tag = segment.userStyles.length ? "mark" : "span";
    return `<${tag} ${attributes.join(" ")}>${text}</${tag}>`;
  }).join("");
}
