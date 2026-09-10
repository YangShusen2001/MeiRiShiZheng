import { AiAnnotation } from '../model/Content';

/** 一段正文切片：`type` 为空串表示无标注的普通文本。 */
export interface ReaderSegment {
  text: string;
  type: string;
  explanation: string;
}

/** 标注类型 → 中文标签（释义浮层与标注总览用）。 */
export function annotationLabel(type: string): string {
  if (type === 'exam_point') {
    return '考点';
  }
  if (type === 'viewpoint') {
    return '观点';
  }
  if (type === 'term') {
    return '术语';
  }
  if (type === 'figure') {
    return '数字指标';
  }
  return '';
}

/**
 * 把一段原文按标注切成有序切片。
 *
 * 纯函数，不依赖 UI，便于单测。规则：
 * - 只取落在本段且区间合法（`0 <= start < end <= 段长`）的标注；
 * - 按 `start` 升序；重叠时后一个从游标处截断，避免负长度切片；
 * - 未被任何标注覆盖的区间输出为普通切片。
 */
export function buildReaderSegments(
  paragraph: string,
  annotations: AiAnnotation[],
  paragraphIndex: number,
): ReaderSegment[] {
  const inParagraph: AiAnnotation[] = annotations
    .filter((item: AiAnnotation) => item.paragraphIndex === paragraphIndex)
    .filter((item: AiAnnotation) => item.start >= 0 && item.end > item.start && item.end <= paragraph.length)
    .sort((left: AiAnnotation, right: AiAnnotation) => left.start - right.start);

  const segments: ReaderSegment[] = [];
  let cursor: number = 0;

  for (const item of inParagraph) {
    const start: number = item.start < cursor ? cursor : item.start;
    if (start > cursor) {
      segments.push({ text: paragraph.substring(cursor, start), type: '', explanation: '' });
    }
    if (item.end > start) {
      const explanation: string | undefined = item.explanation;
      segments.push({
        text: paragraph.substring(start, item.end),
        type: item.type,
        explanation: explanation === undefined ? '' : explanation,
      });
      cursor = item.end;
    }
  }

  if (cursor < paragraph.length) {
    segments.push({ text: paragraph.substring(cursor), type: '', explanation: '' });
  }
  return segments;
}
