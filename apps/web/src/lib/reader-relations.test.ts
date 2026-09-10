import { describe, expect, it } from "vitest";
import { buildReaderSegments, readerSegmentsToHtml, validAiAnnotations } from "./reader-annotations";
import { relationSpanMap, validRelations } from "./reader-relations";
import type { AiAnnotation, AiRelation } from "@kaogong/contracts";

function ann(id: string, para: number, text: string, type: AiAnnotation["type"]): AiAnnotation {
  const start = PARA.indexOf(text);
  return { id, paragraphIndex: para, start, end: start + text.length, text, type };
}

const PARA = "商家是第一责任主体，骑手与消费者均享有双向拒收权。";
const VIEW = ann("v1", 0, "商家是第一责任主体", "viewpoint");
const POINT = ann("p1", 0, "双向拒收权", "exam_point");

const REL: AiRelation = {
  id: "rel-1", paragraphIndex: 0, anchor: "v1",
  points: [{ annotationId: "p1", kind: "support" }], kind: "support", aiGenerated: true,
};

describe("validRelations", () => {
  it("接受引用有效的关系，过滤坏引用与跨段锚点", () => {
    const good = [REL];
    const badAnchor = { ...REL, id: "r2", anchor: "missing" };
    const wrongPara = { ...REL, id: "r3", paragraphIndex: 1 };
    const badPoint = { ...REL, id: "r4", points: [{ annotationId: "missing", kind: "support" }] };
    expect(validRelations([...good, badAnchor as AiRelation, wrongPara as AiRelation, badPoint as AiRelation], [VIEW, POINT]).map((r) => r.id)).toEqual(["rel-1"]);
  });
});

describe("relationSpanMap", () => {
  it("把 center/point 标注映射到关系 id 集合", () => {
    const map = relationSpanMap([REL], [VIEW, POINT]);
    expect(map.get("v1")).toEqual(["rel-1"]);
    expect(map.get("p1")).toEqual(["rel-1"]);
  });
});

describe("buildReaderSegments 关系装饰", () => {
  it("在对应标注 segment 输出 data-rel-ids 与精确 annotation id", () => {
    const relMap = relationSpanMap([REL], [VIEW, POINT]);
    const segments = buildReaderSegments(PARA, [], [VIEW, POINT], relMap);
    const html = readerSegmentsToHtml(segments);
    expect(html).toContain('data-rel-ids="rel-1"');
    expect(html).toContain('data-annotation-id="v1"');
    expect(html).toContain('data-annotation-id="p1"');
    // 无装饰段落（原文模式 relMap 不传）不出关系标记
    const plain = readerSegmentsToHtml(buildReaderSegments(PARA, [], [], undefined));
    expect(plain).not.toContain("data-rel-ids");
  });

  it("validAiAnnotations 依然只认白名单类型（figure 已被加入）", () => {
    const figure = validAiAnnotations(PARA, [{ ...VIEW, id: "f1", type: "figure" as const }]);
    expect(figure).toHaveLength(1);
  });
});
