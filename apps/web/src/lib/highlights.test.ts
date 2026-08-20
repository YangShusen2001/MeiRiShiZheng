import { describe, expect, it } from "vitest";
import { applyStyle, buildSegments, removeRange, removeStyle, resolveSpanNotes, segmentsToHtml, type Span } from "./highlights";
import { buildReaderSegments, readerSegmentsToHtml, validAiAnnotations } from "./reader-annotations";

describe("applyStyle", () => {
  it("在空集上应用样式生成单区间", () => {
    expect(applyStyle([], { start: 0, end: 4 }, "green")).toEqual([
      { start: 0, end: 4, styles: ["green"] },
    ]);
  });

  it("同区间叠加第二种样式（荧光笔 + 下划线）", () => {
    let spans = applyStyle([], { start: 2, end: 5 }, "green");
    spans = applyStyle(spans, { start: 2, end: 5 }, "underline");
    expect(spans).toEqual([{ start: 2, end: 5, styles: ["green", "underline"] }]);
  });

  it("重叠区间按覆盖求并集并切分", () => {
    let spans = applyStyle([], { start: 0, end: 6 }, "green");
    spans = applyStyle(spans, { start: 4, end: 8 }, "underline");
    expect(spans).toEqual([
      { start: 0, end: 4, styles: ["green"] },
      { start: 4, end: 6, styles: ["green", "underline"] },
      { start: 6, end: 8, styles: ["underline"] },
    ]);
  });

  it("重复应用相同样式去重", () => {
    let spans = applyStyle([], { start: 0, end: 3 }, "green");
    spans = applyStyle(spans, { start: 0, end: 3 }, "green");
    expect(spans).toEqual([{ start: 0, end: 3, styles: ["green"] }]);
  });
});

describe("note/explanation 保留（防 AI 解析/释义断层）", () => {
  it("applyStyle 叠加样式时不丢已有 explanation", () => {
    let spans = applyStyle([], { start: 0, end: 6 }, "underline");
    spans = [{ ...spans[0]!, explanation: "E" }];
    const next = applyStyle(spans, { start: 2, end: 4 }, "green");
    expect(next.map((s) => s.explanation ?? "")).toEqual(["E", "E", "E"]);
  });

  it("removeRange 保留两侧剩余区间的 explanation", () => {
    const spans: Span[] = [{ start: 0, end: 6, styles: ["underline"], explanation: "E" }];
    const next = removeRange(spans, { start: 2, end: 4 });
    expect(next.map((s) => s.explanation ?? "")).toEqual(["E", "E"]);
  });

  it("removeStyle 保留同区间的 explanation", () => {
    const spans: Span[] = [{ start: 0, end: 6, styles: ["green", "underline"], explanation: "E" }];
    const next = removeStyle(spans, { start: 0, end: 6 }, "underline");
    expect(next).toEqual([{ start: 0, end: 6, styles: ["green"], explanation: "E" }]);
  });

  it("相邻同样式区间合并时保留 explanation", () => {
    const spans: Span[] = [
      { start: 0, end: 2, styles: ["green"], explanation: "E1" },
      { start: 2, end: 4, styles: ["green"] },
    ];
    const next = applyStyle(spans, { start: 4, end: 5 }, "green");
    expect(next).toEqual([{ start: 0, end: 5, styles: ["green"], explanation: "E1" }]);
  });
});

describe("AI 与用户标注合并渲染", () => {
  const termExplanation = "这一政策术语强调跨部门协同配置资源，以制度衔接提升公共治理的整体效能。";
  const annotations = [
    { id: "v1", paragraphIndex: 0, start: 0, end: 4, text: "治理能力", type: "viewpoint" as const },
    { id: "e1", paragraphIndex: 0, start: 2, end: 6, text: "能力现代", type: "exam_point" as const },
    { id: "t1", paragraphIndex: 0, start: 4, end: 8, text: "现代化建", type: "term" as const, explanation: termExplanation },
  ];

  it("按所有边界切分并同时保留 AI 与用户样式", () => {
    const html = readerSegmentsToHtml(buildReaderSegments(
      "治理能力现代化建设",
      [{ start: 3, end: 7, styles: ["green"] }],
      annotations,
    ));
    expect(html).toContain('class="hl-green ai-viewpoint ai-exam-point"');
    expect(html).toContain('class="hl-green ai-exam-point ai-term"');
    expect(html).toContain('data-user-highlight="true"');
    expect(html).toContain(`data-explanation="${termExplanation}"`);
    expect(html).toContain('tabindex="0"');
  });

  it("原文模式不传 AI 区间时仍保留用户标注", () => {
    const html = readerSegmentsToHtml(buildReaderSegments(
      "治理能力现代化建设",
      [{ start: 0, end: 4, styles: ["underline"] }],
      [],
    ));
    expect(html).toContain("hl-underline");
    expect(html).not.toContain("ai-");
  });

  it("加粗样式渲染 hl-bold", () => {
    const html = readerSegmentsToHtml(buildReaderSegments(
      "治理能力现代化建设",
      [{ start: 0, end: 4, styles: ["bold"] }],
      [],
    ));
    expect(html).toContain("hl-bold");
  });

  it("带 AI 解释的用户划线渲染 data-explanation（悬停 tooltip）", () => {
    const html = readerSegmentsToHtml(buildReaderSegments(
      "治理能力现代化建设",
      [{ start: 0, end: 4, styles: ["underline"], explanation: "治理能力指统筹各方…" }],
      [],
    ));
    expect(html).toContain("hl-underline");
    expect(html).toContain('data-user-highlight="true"');
    expect(html).toContain('data-explanation="治理能力指统筹各方…"');
    expect(html).toContain('tabindex="0"');
  });

  it("用户 AI 解析优先于术语释义，不被静态释义覆盖", () => {
    const html = readerSegmentsToHtml(buildReaderSegments(
      "治理能力现代化建设",
      [{ start: 4, end: 8, styles: ["underline"], explanation: "用户解析内容" }],
      [{ id: "t1", paragraphIndex: 0, start: 4, end: 8, text: "现代化建", type: "term" as const, explanation: termExplanation }],
    ));
    expect(html).toContain('data-explanation="用户解析内容"');
    expect(html).not.toContain(`data-explanation="${termExplanation}"`);
  });

  it("丢弃越界或与原文不一致的 AI 标注", () => {
    expect(validAiAnnotations("治理能力", [
      { id: "bad", paragraphIndex: 0, start: 0, end: 2, text: "错误", type: "term" },
      { id: "outside", paragraphIndex: 0, start: 0, end: 20, text: "治理能力", type: "viewpoint" },
    ])).toEqual([]);
  });
});

describe("removeRange", () => {
  it("移除区间内所有样式并保留两侧", () => {
    const spans: Span[] = [{ start: 0, end: 10, styles: ["green"] }];
    expect(removeRange(spans, { start: 3, end: 7 })).toEqual([
      { start: 0, end: 3, styles: ["green"] },
      { start: 7, end: 10, styles: ["green"] },
    ]);
  });

  it("完全覆盖时清空", () => {
    const spans: Span[] = [{ start: 0, end: 10, styles: ["green"] }];
    expect(removeRange(spans, { start: 0, end: 10 })).toEqual([]);
  });
});

describe("removeStyle", () => {
  it("只移除指定样式并保留其他样式", () => {
    const spans: Span[] = [{ start: 0, end: 10, styles: ["green", "underline"] }];
    expect(removeStyle(spans, { start: 3, end: 7 }, "underline")).toEqual([
      { start: 0, end: 3, styles: ["green", "underline"] },
      { start: 3, end: 7, styles: ["green"] },
      { start: 7, end: 10, styles: ["green", "underline"] },
    ]);
  });
});

describe("buildSegments / segmentsToHtml", () => {
  it("无样式时返回整段文本", () => {
    const segs = buildSegments("abcdef", []);
    expect(segs).toEqual([{ text: "abcdef", styles: [] }]);
    expect(segmentsToHtml(segs)).toBe("abcdef");
  });

  it("按区间切分并包裹 <mark>（叠加样式）", () => {
    const spans: Span[] = [{ start: 2, end: 5, styles: ["green", "underline"] }];
    expect(segmentsToHtml(buildSegments("abcdef", spans))).toBe(
      'ab<mark class="hl-green hl-underline">cde</mark>f',
    );
  });

  it("转义 HTML 特殊字符", () => {
    const spans: Span[] = [{ start: 0, end: 3, styles: ["green"] }];
    expect(segmentsToHtml(buildSegments("<a&b", spans))).toBe(
      '<mark class="hl-green">&lt;a&amp;</mark>b',
    );
  });

  it("注释数据保留但前端不再渲染 data-note", () => {
    const spans: Span[] = [{ start: 2, end: 5, styles: ["green"], note: "重要考点" }];
    expect(segmentsToHtml(buildSegments("abcdef", spans))).toBe(
      'ab<mark class="hl-green">cde</mark>f',
    );
  });
});

describe("resolveSpanNotes", () => {
  it("对重叠划线加注释时，新注释落到选区覆盖的 span，不丢失", () => {
    // 已有 {2,5} 注释 "A"；选区 {4,8} 加注释 "新注"，applyStyle 切分为 {2,4}/{4,5}/{5,8}
    const spans: Span[] = [
      { start: 2, end: 4, styles: ["green"] },
      { start: 4, end: 5, styles: ["green", "yellow"] },
      { start: 5, end: 8, styles: ["yellow"] },
    ];
    const old = [{ start: 2, end: 5, note: "A" }];
    expect(resolveSpanNotes(spans, old, { "4:8": "新注" })).toEqual({
      "2:4": "A",
      "4:5": "新注",
      "5:8": "新注",
    });
  });

  it("无覆盖时，子段继承原注释，非子段不继承", () => {
    const spans: Span[] = [
      { start: 2, end: 3, styles: ["green"] },
      { start: 3, end: 5, styles: ["green", "underline"] },
      { start: 5, end: 6, styles: ["underline"] },
    ];
    const old = [{ start: 2, end: 5, note: "A" }];
    expect(resolveSpanNotes(spans, old, {})).toEqual({
      "2:3": "A",
      "3:5": "A",
      "5:6": "",
    });
  });

  it("精确 key 匹配保留注释（未切分）", () => {
    const spans: Span[] = [{ start: 2, end: 5, styles: ["green", "underline"] }];
    const old = [{ start: 2, end: 5, note: "A" }];
    expect(resolveSpanNotes(spans, old, {})).toEqual({ "2:5": "A" });
  });

  it("空字符串 override 清空注释", () => {
    const spans: Span[] = [{ start: 4, end: 5, styles: ["green", "yellow"] }];
    const old = [{ start: 4, end: 5, note: "A" }];
    expect(resolveSpanNotes(spans, old, { "4:5": "" })).toEqual({ "4:5": "" });
  });
});
