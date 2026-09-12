# -*- coding: utf-8 -*-
"""管道编排单测：fetch_candidates / build_content / practice_content 端到端（mock 全部网络）。"""
import datetime as dt
import json
from pathlib import Path

import httpx
import jsonschema
import pytest

from kaogong.pipeline import build_content, clip_content, practice_content, quality_gate

_SCHEMA = (
    Path(__file__).resolve().parents[2] / "content" / "schema" / "digest.schema.json"
)


def _validate(data: dict):
    jsonschema.validate(data, json.loads(_SCHEMA.read_text(encoding="utf-8")))


def test_build_content_writes_valid_empty_digest(tmp_path):
    """所有源失败时仍产出结构合法（空 sections）的日报。"""

    def handler(request):
        return httpx.Response(500, text="")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = build_content(dt.date(2026, 8, 12), tmp_path, client=client)
    assert path.name == "digest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["date"] == "2026-08-12"
    assert data["sections"] == []
    _validate(data)
    assert quality_gate(dt.date(2026, 8, 12), tmp_path)["qualityStatus"] == "failed"


def test_build_content_end_to_end(tmp_path):
    """gov 源产出候选 → 归入 national 栏目 → 写合法 JSON。"""

    def handler(request):
        if "content_" in request.url.path:
            return httpx.Response(200, text='<div>发布日期：2026-08-12 08:00</div>')
        return httpx.Response(
            200, text='<a href="/zhengce/content/202608/content_1.html">政策标题</a>'
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = build_content(dt.date(2026, 8, 12), tmp_path, client=client)
    data = json.loads(path.read_text(encoding="utf-8"))
    national = next(s for s in data["sections"] if s["id"] == "national")
    assert national["items"][0]["title"] == "政策标题"
    _validate(data)


def _practice_payload(questions):
    return json.dumps({"questions": questions}, ensure_ascii=False)


def _q(i=1):
    return {"q": f"题干{i}", "options": ["A", "B", "C", "D"], "answer": 0, "analysis": "解析", "topic": "主题"}


def test_practice_content_writes_valid_set(tmp_path, monkeypatch):
    """build_content 产出 digest → practice_content 注入 mock chat → 写 practice.json。"""

    def handler(request):
        if "content_" in request.url.path:
            return httpx.Response(200, text='<div>发布日期：2026-08-12 08:00</div>')
        return httpx.Response(
            200, text='<a href="/zhengce/content/202608/content_1.html">政策标题</a>'
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        build_content(dt.date(2026, 8, 12), tmp_path, client=client)

    calls = {"n": 0}

    def fake_generate_practice(text, date, cfg, **kw):
        calls["n"] += 1
        return [
            {"id": "q1", "q": "题干1", "options": ["A", "B", "C", "D"], "answer": 0, "analysis": "解析", "topic": "主题"},
            {"id": "q2", "q": "题干2", "options": ["A", "B", "C", "D"], "answer": 1, "analysis": "解析", "topic": "主题"},
            {"id": "q3", "q": "题干3", "options": ["A", "B", "C", "D"], "answer": 2, "analysis": "解析", "topic": "主题"},
        ]

    # practice_content 内部通过 `from .practice import generate_practice` 引用，
    # 绑定在 pipeline 模块命名空间，故 patch pipeline.generate_practice。
    import kaogong.pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "generate_practice", fake_generate_practice)

    cfg = {"deepseek_api_key": "k"}
    path = practice_content(dt.date(2026, 8, 12), tmp_path, cfg=cfg)
    assert path is not None
    assert path.name == "practice.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["date"] == "2026-08-12"
    assert data["total"] == 3
    assert len(data["questions"]) == 3
    assert calls["n"] == 1


def test_practice_content_no_key_returns_none(tmp_path):
    """无 DEEPSEEK_API_KEY 时 practice_content 返回 None，不抛错。"""
    build_content(dt.date(2026, 8, 12), tmp_path, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500, text=""))))
    path = practice_content(dt.date(2026, 8, 12), tmp_path, cfg={})
    assert path is None


def test_clip_content_records_bounded_sanitized_ai_failures(tmp_path, monkeypatch):
    # Given: more failed articles than the diagnostic report is allowed to retain.
    # v2.1 两阶段（T04）：异构 host 避免配额截断、500+ 字单段过密度门禁、
    # MAX_AI_FAILURES 调小验证截断分支本身。
    target = dt.date(2026, 8, 12)
    day = tmp_path / target.isoformat()
    day.mkdir()
    body = "高质量发展是全面建设社会主义现代化国家的首要任务。" * 20  # 500 字，过 G1-G4
    items = [
        {"title": f"article-{index}", "date": "08-12",
         "sourceUrl": f"https://h{index}.example.com/{index}"}  # 每条独立 host → 配额不裁
        for index in range(8)  # pol CAPS=8：8 条全过配额/CAPS，进 pass-2
    ]
    (day / "digest.json").write_text(
        json.dumps({"date": target.isoformat(), "title": "digest", "sections": [
            {"id": "national", "title": "news", "items": items},
        ]}),
        encoding="utf-8",
    )

    def fake_clip(url, title, date, **kwargs):
        article_id = url.rsplit("/", 1)[-1]
        return {
            "id": article_id, "date": date, "title": title, "source": "source",
            "url": url, "pubDate": "", "fetchedAt": "2026-08-12T00:00:00+00:00",
            "status": "ok", "paragraphs": [body], "keySentences": [],
        }

    def fake_analyze(article, cfg):
        return article | {
            "aiStatus": "error", "aiAnnotations": [],
            "aiError": "ai_provider:request_failed SECRET-ARTICLE-BODY test-secret",
        }

    import kaogong.article_ai as article_ai_mod
    import kaogong.clip as clip_mod
    import kaogong.pipeline as pipeline_mod
    monkeypatch.setattr(clip_mod, "clip_article", fake_clip)
    monkeypatch.setattr(article_ai_mod, "analyze_article", fake_analyze)
    monkeypatch.setattr(pipeline_mod, "MAX_AI_FAILURES", 3)

    # When: clipping completes with per-article AI degradation.
    assert clip_content(target, tmp_path, cfg={}) == 8

    # Then: the report is bounded and contains only IDs plus reason codes.
    report = json.loads((tmp_path / "_reports" / f"{target.isoformat()}.json").read_text(encoding="utf-8"))
    assert report["aiError"] == 8
    assert len(report["aiFailures"]) == 3  # MAX_AI_FAILURES 截断分支
    assert report["aiFailures"][0] == {"articleId": "0", "reason": "ai_provider:request_failed"}
    assert "SECRET-ARTICLE-BODY" not in json.dumps(report, ensure_ascii=False)
    assert "test-secret" not in json.dumps(report, ensure_ascii=False)
    # v2.1 §3.6：candidates=最终 digest 条数；clip 漏斗计数齐备
    assert report["candidates"] == 8
    assert report["clip"]["clipped"] == 8
    assert report["clip"]["densityRejected"] == []
    assert report["clip"]["quotaRejected"] == []


def test_quality_gate_reports_distinct_source_location_ai_and_schema_diagnostics(tmp_path):
    # Given: each diagnostic class has occurred and one artifact violates schema.
    target = dt.date(2026, 8, 12)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "article-invalid.json").write_text(json.dumps({"id": "invalid"}), encoding="utf-8")
    reports = tmp_path / "_reports"
    reports.mkdir()
    (reports / f"{target.isoformat()}.json").write_text(json.dumps({
        "date": target.isoformat(), "sourcesOk": 1, "candidates": 1,
        "sourceErrors": [{"source": "source-a", "error": "source_fetch_failed"}],
        "aiError": 1, "aiFailures": [{"articleId": "a", "reason": "ai_schema:invalid"}],
        "locationErrors": 2,
    }), encoding="utf-8")

    # When: the quality gate evaluates the run.
    result = quality_gate(target, tmp_path)

    # Then: each class remains separately machine-readable and schema is fatal.
    assert result["qualityStatus"] == "failed"
    assert result["sourceErrors"][0]["source"] == "source-a"
    assert result["aiFailures"][0]["reason"] == "ai_schema:invalid"
    assert result["locationErrors"] == 2
    assert result["schemaErrors"][0]["file"] == "article-invalid.json"


def test_quality_gate_fails_when_report_or_candidates_are_missing(tmp_path):
    # Given: no source report and no output directory exist.
    target = dt.date(2026, 8, 12)

    # When: the quality gate runs.
    result = quality_gate(target, tmp_path)

    # Then: absence is a failed run, not a successful empty publication.
    assert result["qualityStatus"] == "failed"
    assert result["sourcesOk"] == 0
    assert result["candidates"] == 0


def test_quality_gate_is_degraded_for_recoverable_ai_failure(tmp_path):
    # Given: sources and candidates succeeded while one article retained original content after AI failure.
    target = dt.date(2026, 8, 12)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "digest.json").write_text(json.dumps({
        "date": target.isoformat(), "title": "digest", "sections": [],
    }), encoding="utf-8")
    reports = tmp_path / "_reports"
    reports.mkdir()
    (reports / f"{target.isoformat()}.json").write_text(json.dumps({
        "sourcesOk": 1, "candidates": 1, "aiError": 1,
        "aiFailures": [{"articleId": "a", "reason": "ai_provider:request_failed"}],
    }), encoding="utf-8")

    # When: the quality gate evaluates a publishable fallback.
    result = quality_gate(target, tmp_path)

    # Then: fallback is explicit but does not become a fatal source/schema failure.
    assert result["qualityStatus"] == "degraded"


def test_quality_gate_degrades_when_picks_slots_all_empty(tmp_path):
    """0022 P0 门禁：picked 非空但 essay/exam/extra 三槽位同时为空 → degraded。

    「合法但空转」的 picks（schema 只要求 minItems:1；bug 期间 4 天实测形态：
    essay 恒 []、exam/extra 恒 null，仅靠 supplement 凑够下限）必须被门禁暴露
    并写失败原因，不得静默发布（AGENTS.md 第 8 条）。
    修复前必失败：无该规则时本场景 qualityStatus == "ok"。
    """
    # Given: a schema-valid picks with picked non-empty but all three slots empty.
    target = dt.date(2026, 8, 14)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "picks.json").write_text(json.dumps({
        "date": target.isoformat(),
        "slots": {"headline": "a", "essay": [], "exam": None, "extra": None},
        "picked": ["a"], "assignments": {"a": None},
    }), encoding="utf-8")
    reports = tmp_path / "_reports"
    reports.mkdir()
    (reports / f"{target.isoformat()}.json").write_text(json.dumps({
        "date": target.isoformat(), "sourcesOk": 1, "candidates": 2, "articles": 2,
    }), encoding="utf-8")

    # When: the publication gate evaluates the hollow picks.
    result = quality_gate(target, tmp_path)

    # Then: it is degraded (not failed—原文仍可发布) with a machine-readable reason.
    assert result["qualityStatus"] == "degraded"
    assert "picks_slots_all_empty" in result["curationErrors"]


def _write_report(root, date, **values):
    reports = root / "_reports"
    reports.mkdir(exist_ok=True)
    payload = {"date": date.isoformat(), "sourcesOk": 1, "candidates": 10, "articles": 10} | values
    (reports / f"{date.isoformat()}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_digest(root, date):
    day = root / date.isoformat()
    day.mkdir(exist_ok=True)
    (day / "digest.json").write_text(json.dumps({
        "date": date.isoformat(), "title": "digest", "sections": [],
    }), encoding="utf-8")
    # 0022：picks 是每日选材产物；测试 fixture 提供非空 picks 以免误判 picks_missing。
    # 槽位必须非空：旧 fixture 的 {essay: [], exam: None, extra: None} 恰是 bug 期间的
    # 「空转」形态，会触发 picks_slots_all_empty 门禁（本组测试只验证数量/分类/语义门禁，
    # 该门禁由 test_quality_gate_degrades_when_picks_slots_all_empty 专门覆盖）。
    (day / "picks.json").write_text(json.dumps({
        "date": date.isoformat(),
        "slots": {"headline": "a", "essay": ["b"], "exam": "c", "extra": "d"},
        "picked": ["a", "b", "c", "d"],
        "assignments": {"a": None, "b": None, "c": None, "d": None},
    }), encoding="utf-8")


def test_quality_gate_revalidates_successful_ai_article_semantics(tmp_path):
    # Given: schema-valid AI output points at text different from its declared range.
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, target)
    article = {
        "id": "semantic", "date": target.isoformat(), "title": "title", "source": "source",
        "url": "https://example.com/article", "pubDate": "", "fetchedAt": "2026-08-14T00:00:00+00:00",
        "status": "ok", "paragraphs": ["高质量发展"], "keySentences": [], "aiStatus": "ok",
        "aiSummary": "高质量发展需要持续强化创新驱动和制度保障，推动产业结构优化升级，提升公共治理效能，为中国式现代化建设积蓄更加坚实可靠的长期发展动能。",
        "aiAnnotations": [{"id": "a", "paragraphIndex": 0, "start": 0, "end": 5, "text": "错误文本", "type": "viewpoint"}],
        "aiModel": "model", "aiPromptVersion": "v1", "aiGeneratedAt": "2026-08-14T00:00:00+00:00",
        "sourceTextHash": "1e7982906907aa91510de306e1d16c882091723b4045d15b9fe0a5db1228268d",
        "aiQuality": {"locationErrors": 0},
    }
    (tmp_path / target.isoformat() / "article-semantic.json").write_text(json.dumps(article), encoding="utf-8")

    # When: the publication gate runs.
    result = quality_gate(target, tmp_path)

    # Then: semantic corruption is fatal and diagnostics contain no article body.
    assert result["qualityStatus"] == "failed"
    assert result["semanticErrors"] == [{"file": "article-semantic.json", "error": "source_hash_mismatch"}, {"file": "article-semantic.json", "error": "annotation_text_mismatch"}]
    assert "高质量发展" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(("raw", "expected"), [(5, "ok"), (4, "failed")])
def test_quality_gate_enforces_fetch_raw_floor(tmp_path, raw, expected):
    """2026-09-12 校准（用户拍板）：数量体检 = fetch 层绝对下限（candidatesRaw < 5）。

    v2.1 精品转向后低量级是设计目标（≤15 篇/日），旧「相对近期基线中位数」会把
    天生日薄（合法 sparse）误报为源故障——09-12 实战：10 篇健康日被旧检查判 failed。
    真正的源故障信号在 fetch 层：13 源经白名单后正常日 candidatesRaw ~10-20。
    """
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, target, fetch={"candidatesRaw": raw})

    result = quality_gate(target, tmp_path)

    assert result["qualityStatus"] == expected
    assert len(result["volumeErrors"]) == (0 if expected == "ok" else 1)
    if expected == "failed":
        assert result["volumeErrors"][0]["metric"] == "candidatesRaw"
        assert result["volumeErrors"][0]["error"] == "below_fetch_floor"


def test_quality_gate_skips_volume_check_without_fetch_metric(tmp_path):
    """兼容：无 fetch.candidatesRaw 的报告形态（T04 前旧格式）不触发数量误报。"""
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, target)

    result = quality_gate(target, tmp_path)

    assert result["qualityStatus"] == "ok"
    assert result["volumeErrors"] == []


def test_quality_gate_ignores_post_gate_volume(tmp_path):
    """post-pivot 核心语义：candidates/articles 后置门禁量低是设计目标，不做数量体检。

    修复前必失败：旧检查拿 candidates=3 与历史基线中位数比较 → below_half_baseline。
    """
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, target, candidates=3, articles=3, fetch={"candidatesRaw": 14})

    result = quality_gate(target, tmp_path)

    assert result["qualityStatus"] == "ok"
    assert result["volumeErrors"] == []


def test_quality_gate_classifies_artifacts_by_filename(tmp_path):
    # Given: an article filename contains digest-like payload keys.
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, target)
    (tmp_path / target.isoformat() / "article-wrong.json").write_text(json.dumps({
        "date": target.isoformat(), "title": "wrong", "sections": [],
    }), encoding="utf-8")

    # When: the quality gate assigns its schema.
    result = quality_gate(target, tmp_path)

    # Then: article-* is validated as an article, not inferred as a digest.
    assert result["qualityStatus"] == "failed"
    assert result["schemaErrors"][0]["file"] == "article-wrong.json"


def test_quality_gate_rejects_practice_total_mismatch_and_digest_date_relation(tmp_path):
    # Given: aggregate practice count and digest item date contradict their enclosing artifacts.
    target = dt.date(2026, 8, 14)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "digest.json").write_text(json.dumps({
        "date": target.isoformat(), "title": "digest", "sections": [{
            "id": "national", "title": "news", "items": [{
                "title": "item", "date": "08-13", "sourceUrl": "https://example.com/item",
            }],
        }],
    }), encoding="utf-8")
    practice = json.loads((Path(__file__).resolve().parents[2] / "content" / "2026-08-12" / "practice.json").read_text(encoding="utf-8"))
    practice.update({"date": target.isoformat(), "total": 4})
    (day / "practice.json").write_text(json.dumps(practice), encoding="utf-8")
    _write_report(tmp_path, target)

    # When: cross-field semantic validation runs.
    result = quality_gate(target, tmp_path)

    # Then: both contradictions are fatal and separately machine-readable.
    assert result["qualityStatus"] == "failed"
    assert result["semanticErrors"] == [
        {"file": "digest.json", "error": "digest_item_date_mismatch"},
        {"file": "practice.json", "error": "practice_total_mismatch"},
    ]


def test_quality_gate_handles_summary_artifact_without_crashing(tmp_path):
    # Given: a schema-valid summary.json（今日速览）sits alongside other artifacts.
    target = dt.date(2026, 8, 14)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "summary.json").write_text(json.dumps({
        "date": target.isoformat(),
        "summary": "今天重点关注防灾减灾与地方全会。",
        "keywords": ["防灾减灾", "广东开渔"],
    }), encoding="utf-8")
    _write_digest(tmp_path, target)
    _write_report(tmp_path, target)

    # When: the quality gate runs semantic validation over every artifact.
    result = quality_gate(target, tmp_path)

    # Then: the summary artifact kind is handled without raising, and adds no semantic error.
    assert result["qualityStatus"] in {"ok", "degraded", "failed"}
    assert all(e["file"] != "summary.json" for e in result["semanticErrors"])


# —— v2.1 §3：配额/CAPS 后移 clip 层（T04 _apply_quota_and_caps）；
#    fetch 层只剩 MAX_PRECLIP 安全阀，同源候选不再被截断 ——


def test_caps_values_v2():
    """v2.1 §3.7：CAPS 取值不变（pol 8 / essay 10 / gdp 5，删 gd/sc/js）。

    常量保留在 pipeline.py 供 clip 层 _apply_quota_and_caps（T04）消费；
    本测试锁定取值防漂移。
    """
    from kaogong.pipeline import CAPS

    assert not {"gd", "sc", "js"} & set(CAPS)
    assert CAPS["pol"] == 8
    assert CAPS["essay"] == 10
    assert CAPS["gdp"] == 5
    assert CAPS["gov"] == 10 and CAPS["shi"] == 18  # 其余不变


def test_preclip_ceiling_keeps_list_order_below_limit():
    # Given: 候选总量低于安全阀（正常日 ~22 << MAX_PRECLIP=48）。
    from kaogong.models import Candidate
    from kaogong.pipeline import _preclip_ceiling

    cands = [
        Candidate(title=f"文{i}", url=f"u{i}", date=dt.date(2026, 9, 11), slot="pol")
        for i in range(22)
    ]

    # When / Then: 原样放行（同一对象），不做任何截断。
    assert _preclip_ceiling(cands) is cands


def test_preclip_ceiling_truncates_at_forty_eight():
    # Given: 单日刷屏 60 条候选（源故障/目录页改版场景）。
    from kaogong.models import Candidate
    from kaogong.pipeline import _preclip_ceiling

    cands = [
        Candidate(title=f"文{i}", url=f"u{i}", date=dt.date(2026, 9, 11), slot="pol")
        for i in range(60)
    ]

    # When: 过 MAX_PRECLIP=48 安全阀。
    out = _preclip_ceiling(cands)

    # Then: 按抓取顺序保留前 48 条。
    assert len(out) == 48
    assert [c.title for c in out] == [f"文{i}" for i in range(48)]


def test_fetch_candidates_same_source_passes_through():
    """v2.1 返工验收：fetch 层不再截断同源候选——单源 20 条全过。

    v2 的列表序配额在此场景会砍到 3 条（先到先得 = 发布时间倒序，与价值无关，
    黄金样本日误杀 news.cn 第 5/6 位的长文 IN）；v2.1 配额后移 clip 层。
    同时验证 source_name 回填保留——后移配额仍需它作分组键。
    """
    from kaogong.pipeline import fetch_candidates
    from kaogong.sources import Source, _yyyymmdd, source_to_dict

    src = Source("测试源", "pol", "https://x.com/", r"/(\d{8})/",
                 date_fn=_yyyymmdd, limit=30)
    html = "".join(f'<a href="/20260911/a{i}.html">标题{i}</a>' for i in range(20))

    def handler(request):
        return httpx.Response(200, text=html)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_candidates(
            dt.date(2026, 9, 11), client=client,
            config={"sources": [source_to_dict(src)]},
            cfg={"deepseek_api_key": ""},
        )
    assert [c.title for c in cands] == [f"标题{i}" for i in range(20)]
    assert all(c.source_name == "测试源" for c in cands)


def test_fetch_candidates_no_quota_no_caps_at_fetch_layer():
    """v2.1 §3.2-A1：槽位 CAPS 不在 fetch 层——3 个 pol 源 × 10 条 = 30 条全过。

    v2 行为：配额 3×3=9 → CAPS pol=8 截到 8 条；v2.1 全过（30 < MAX_PRECLIP=48），
    由 clip 层按 total_chars 降序统一执行配额与 CAPS。
    """
    from kaogong.pipeline import fetch_candidates
    from kaogong.sources import Source, _yyyymmdd, source_to_dict

    srcs = [
        Source(f"pol源{i}", "pol", f"https://p{i}.com/", r"/(\d{8})/",
               date_fn=_yyyymmdd, limit=10)
        for i in range(3)
    ]

    def handler(request):
        i = request.url.host[1]  # p0.com / p1.com / p2.com
        links = "".join(f'<a href="/20260911/{i}{j}.html">源{i}文{j}</a>' for j in range(10))
        return httpx.Response(200, text=links)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_candidates(
            dt.date(2026, 9, 11), client=client,
            config={"sources": [source_to_dict(s) for s in srcs]},
            cfg={"deepseek_api_key": ""},
        )
    assert len(cands) == 30  # 3 源 × 10 全过，无配额、无 CAPS
    assert {c.source_name for c in cands} == {"pol源0", "pol源1", "pol源2"}


def test_fetch_candidates_essay_inflow_not_squeezed_at_fetch_layer():
    """essay 槽（大洋网+川观理论栏目流入）不在 fetch 层收口——4 源 × 10 = 40 全过。

    v2 行为：配额 4×3=12 → CAPS essay=10 截到 10；v2.1 全过（40 < 48）。
    """
    from kaogong.pipeline import fetch_candidates
    from kaogong.sources import Source, _yyyymmdd, source_to_dict

    srcs = [
        Source(f"essay源{i}", "essay", f"https://e{i}.com/", r"/(\d{8})/",
               date_fn=_yyyymmdd, limit=10)
        for i in range(4)
    ]

    def handler(request):
        i = request.url.host[1]  # e0.com … e3.com
        links = "".join(f'<a href="/20260911/{i}{j}.html">源{i}文{j}</a>' for j in range(10))
        return httpx.Response(200, text=links)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_candidates(
            dt.date(2026, 9, 11), client=client,
            config={"sources": [source_to_dict(s) for s in srcs]},
            cfg={"deepseek_api_key": ""},
        )
    assert len(cands) == 40  # 4 源 × 10 全过


def test_fetch_candidates_max_preclip_applies():
    """MAX_PRECLIP=48 安全阀端到端：5 源 × 12 = 60 条 → 截到 48（防刷屏兜底）。"""
    from kaogong.pipeline import MAX_PRECLIP, fetch_candidates
    from kaogong.sources import Source, _yyyymmdd, source_to_dict

    assert MAX_PRECLIP == 48
    srcs = [
        Source(f"m源{i}", "pol", f"https://m{i}.com/", r"/(\d{8})/",
               date_fn=_yyyymmdd, limit=12)
        for i in range(5)
    ]

    def handler(request):
        i = request.url.host[1]  # m0.com … m4.com
        links = "".join(f'<a href="/20260911/{i}{j}.html">源{i}文{j}</a>' for j in range(12))
        return httpx.Response(200, text=links)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        cands = fetch_candidates(
            dt.date(2026, 9, 11), client=client,
            config={"sources": [source_to_dict(s) for s in srcs]},
            cfg={"deepseek_api_key": ""},
        )
    assert len(cands) == 48  # 60 → MAX_PRECLIP 48
    # 按抓取顺序截断：前 4 源（4×12=48）全过，第 5 源被兜底切掉
    assert not any(c.source_name == "m源4" for c in cands)


# —— v2.1 §3.2-A1/§5（T04）：clip 层密度门禁 + 配额/CAPS（total_chars 降序）——


def test_slot_of_section_mapping():
    """digest 契约无 slot → 分节 id + URL host 推导；gd.gov.cn 不得误匹配 gov.cn。"""
    from kaogong.pipeline import _slot_of

    assert _slot_of("https://news.dayoo.com/1", "essay") == "essay"
    assert _slot_of("https://www.gd.gov.cn/1", "policy") == "gdp"
    assert _slot_of("https://www.gov.cn/1", "national") == "gov"
    assert _slot_of("https://www.gd.gov.cn/1", "national") == "pol"  # gd.gov.cn ≠ gov.cn
    assert _slot_of("https://www.news.cn/1", "national") == "pol"


def test_apply_quota_and_caps_prefers_longest_per_host():
    """同 host 配额 3：按 total_chars 降序保留最长 3 条（v2 列表序截断的修正）。

    v2 行为：先到先得 = 发布时间倒序，黄金样本日误杀 news.cn 第 5/6 位的长文 IN。
    """
    from kaogong.pipeline import _apply_quota_and_caps

    section_by_url: dict[str, str] = {}
    clips = []
    for i, chars in enumerate([500, 400, 300, 200, 100]):
        url = f"https://news.cn/a{i}"
        section_by_url[url] = "national"
        clips.append({"id": f"a{i}", "url": url, "title": f"文{i}", "paragraphs": ["字" * chars]})
    final, cut = _apply_quota_and_caps(clips, section_by_url)
    assert [c["id"] for c in final] == ["a0", "a1", "a2"]  # 最长 3 条存活
    assert [c["id"] for c in cut] == ["a3", "a4"]
    # final 保持原相对顺序（digest 重写不乱序）
    assert [c["id"] for c in final] == [c["id"] for c in clips if c in final]


def test_apply_quota_and_caps_host_grouping_and_govcn_override():
    """分组键 = 文章 URL host（去 www）：大洋网源页/文章 host 分裂按文章算；
    gov.cn 覆盖配额 4；digest 无源名也能稳定计量。"""
    from kaogong.pipeline import _apply_quota_and_caps

    section_by_url: dict[str, str] = {}
    clips = []
    for i in range(4):  # news.dayoo.com：配额 3 → 留 3 砍 1
        url = f"https://news.dayoo.com/{i}"
        section_by_url[url] = "essay"
        clips.append({"id": f"d{i}", "url": url, "title": f"大{i}", "paragraphs": ["字" * 100]})
    for i in range(4):  # gov.cn：QUOTA_OVERRIDES 4 → 4 条全过
        url = f"https://www.gov.cn/zhengce/{i}"
        section_by_url[url] = "policy"
        clips.append({"id": f"g{i}", "url": url, "title": f"政{i}", "paragraphs": ["字" * 100]})
    final, cut = _apply_quota_and_caps(clips, section_by_url)
    assert {c["id"] for c in final} == {f"d{i}" for i in range(3)} | {f"g{i}" for i in range(4)}
    assert [c["id"] for c in cut] == ["d3"]


def test_clip_content_density_gate_rejects_and_rewrites_digest(tmp_path, monkeypatch):
    """两阶段：密度门禁拒绝的条目不落盘、不做 AI、digest 重写只留存活条目。"""
    target = dt.date(2026, 8, 12)
    day = tmp_path / target.isoformat()
    day.mkdir()
    shallow = "短讯内容。" * 20          # 100 字 → G1 shallow_notice
    pure_data = "2024年进出口12345678亿元增长12.3%。" * 25  # ~500 字、数字密集、零分析词 → G2
    good = "推动高质量发展必须坚持问题导向，因为发展是解决一切问题的基础和关键。" * 12  # ~408 字
    items = [
        {"title": "浅讯", "date": "08-12", "sourceUrl": "https://s0.example.com/0"},
        {"title": "数据稿", "date": "08-12", "sourceUrl": "https://s1.example.com/1"},
        {"title": "好文章", "date": "08-12", "sourceUrl": "https://s2.example.com/2"},
    ]
    (day / "digest.json").write_text(
        json.dumps({"date": target.isoformat(), "title": "digest", "sections": [
            {"id": "national", "title": "news", "items": items},
        ]}),
        encoding="utf-8",
    )
    bodies = {"0": [shallow], "1": [pure_data], "2": [good]}

    def fake_clip(url, title, date, **kwargs):
        key = url.rsplit("/", 1)[-1]
        return {
            "id": key, "date": date, "title": title, "source": "source",
            "url": url, "pubDate": "", "fetchedAt": "2026-08-12T00:00:00+00:00",
            "status": "ok", "paragraphs": bodies[key], "keySentences": [],
        }

    analyzed: list[str] = []

    def fake_analyze(article, cfg):
        analyzed.append(article["id"])
        return article | {"aiStatus": "error", "aiAnnotations": [], "aiError": "ai_config:missing_api_key"}

    import kaogong.article_ai as article_ai_mod
    import kaogong.clip as clip_mod
    monkeypatch.setattr(clip_mod, "clip_article", fake_clip)
    monkeypatch.setattr(article_ai_mod, "analyze_article", fake_analyze)

    assert clip_content(target, tmp_path, cfg={}) == 1

    # AI 只对存活者调用（§3.4：密度门禁在剪藏后、AI 前）
    assert analyzed == ["2"]
    report = json.loads((tmp_path / "_reports" / f"{target.isoformat()}.json").read_text(encoding="utf-8"))
    assert report["candidates"] == 1 and report["articles"] == 1
    assert [r["reason"] for r in report["clip"]["densityRejected"]] == ["shallow_notice", "pure_data"]
    assert report["clip"]["quotaRejected"] == []
    assert report["clip"]["clipped"] == 3
    # clipDetails 显性化：density_low:* 前缀
    reasons = {d["id"]: d["reason"] for d in report["clipDetails"]}
    assert reasons["0"] == "density_low:shallow_notice"
    assert reasons["1"] == "density_low:pure_data"
    # digest 重写：只留存活条目
    digest = json.loads((day / "digest.json").read_text(encoding="utf-8"))
    assert [it["sourceUrl"] for it in digest["sections"][0]["items"]] == ["https://s2.example.com/2"]
    # 被拒者不落文章文件
    assert not (day / "article-0.json").exists()
    assert not (day / "article-1.json").exists()
    assert (day / "article-2.json").exists()


def test_clip_content_quota_rejection_recorded_and_digest_shrinks(tmp_path, monkeypatch):
    """同 host 4 条 → 配额 3 留最长 3 条；quotaRejected 带 totalChars 供排查。"""
    target = dt.date(2026, 8, 12)
    day = tmp_path / target.isoformat()
    day.mkdir()
    body = "推动高质量发展必须坚持问题导向，因为发展是解决一切问题的基础和关键。" * 12  # ~470 字
    items = [
        {"title": f"文{i}", "date": "08-12", "sourceUrl": f"https://news.dayoo.com/{i}",
         } for i in range(4)
    ]
    (day / "digest.json").write_text(
        json.dumps({"date": target.isoformat(), "title": "digest", "sections": [
            {"id": "essay", "title": "申论精读", "items": items},
        ]}),
        encoding="utf-8",
    )

    def fake_clip(url, title, date, **kwargs):
        key = url.rsplit("/", 1)[-1]
        return {
            "id": key, "date": date, "title": title, "source": "source",
            "url": url, "pubDate": "", "fetchedAt": "2026-08-12T00:00:00+00:00",
            "status": "ok", "paragraphs": [body * (int(key) + 1)], "keySentences": [],
        }

    def fake_analyze(article, cfg):
        return article | {"aiStatus": "error", "aiAnnotations": [], "aiError": "ai_config:missing_api_key"}

    import kaogong.article_ai as article_ai_mod
    import kaogong.clip as clip_mod
    monkeypatch.setattr(clip_mod, "clip_article", fake_clip)
    monkeypatch.setattr(article_ai_mod, "analyze_article", fake_analyze)

    assert clip_content(target, tmp_path, cfg={}) == 3

    report = json.loads((tmp_path / "_reports" / f"{target.isoformat()}.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in report["clip"]["quotaRejected"]] == ["0"]  # 最短者被砍，1/2/3 存活
    assert report["clip"]["quotaRejected"][0]["totalChars"] == len(body)
    digest = json.loads((day / "digest.json").read_text(encoding="utf-8"))
    kept_urls = {it["sourceUrl"] for it in digest["sections"][0]["items"]}
    assert kept_urls == {f"https://news.dayoo.com/{i}" for i in (1, 2, 3)}


def test_quality_gate_sparse_day_with_single_pick(tmp_path):
    """v2.1 §7.1：1≤picked<2 且 slots.sparse=true → 合法 sparse 日（非 degraded）。

    修复前必失败：无 sparse 语义时该场景判 degraded（picks_slots_all_empty）。
    """
    target = dt.date(2026, 9, 11)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "picks.json").write_text(json.dumps({
        "date": target.isoformat(),
        "slots": {"headline": "a", "essay": [], "exam": None, "extra": None, "sparse": True},
        "picked": ["a"], "assignments": {"a": None},
    }), encoding="utf-8")
    reports = tmp_path / "_reports"
    reports.mkdir()
    (reports / f"{target.isoformat()}.json").write_text(json.dumps({
        "date": target.isoformat(), "sourcesOk": 1, "candidates": 1, "articles": 1,
    }), encoding="utf-8")

    result = quality_gate(target, tmp_path)

    assert result["qualityStatus"] == "sparse"
    assert result["curationErrors"] == []


def test_quality_gate_sparse_when_curate_found_nothing(tmp_path):
    """v2.1 §7.1：curate 已跑（report 有 curation 段）但 picked=0 → sparse。

    「跑了没选出」≠「curate 没跑」：后者（无 curation 段）仍判 picks_missing。
    """
    target = dt.date(2026, 9, 11)
    day = tmp_path / target.isoformat()
    day.mkdir()
    (day / "article-a.json").write_text(json.dumps({
        "id": "a", "date": target.isoformat(), "title": "t", "source": "s",
        "url": "https://example.com/a", "pubDate": "",
        "fetchedAt": "2026-09-11T00:00:00+00:00", "status": "ok",
        "paragraphs": ["正文"], "keySentences": [],
        "aiStatus": "error", "aiAnnotations": [], "aiModel": "m",
        "aiPromptVersion": "v", "aiGeneratedAt": "2026-09-11T00:00:00+00:00",
        "sourceTextHash": "0" * 64, "aiError": "ai_config:missing_api_key",
    }), encoding="utf-8")
    reports = tmp_path / "_reports"
    reports.mkdir()
    (reports / f"{target.isoformat()}.json").write_text(json.dumps({
        "date": target.isoformat(), "sourcesOk": 1, "candidates": 1, "articles": 1,
        "curation": {"candidates": 1, "picked": 0, "picksWritten": False, "needsHuman": ["a"]},
    }), encoding="utf-8")

    result = quality_gate(target, tmp_path)

    assert result["qualityStatus"] == "sparse"
    assert "picks_missing" not in result["curationErrors"]
