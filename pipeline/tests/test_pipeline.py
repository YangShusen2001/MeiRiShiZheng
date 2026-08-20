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
    target = dt.date(2026, 8, 12)
    day = tmp_path / target.isoformat()
    day.mkdir()
    items = [
        {"title": f"article-{index}", "sourceUrl": f"https://example.com/{index}"}
        for index in range(60)
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
            "status": "ok", "paragraphs": ["SECRET-ARTICLE-BODY"], "keySentences": [],
        }

    def fake_analyze(article, cfg):
        return article | {
            "aiStatus": "error", "aiAnnotations": [],
            "aiError": "ai_provider:request_failed SECRET-ARTICLE-BODY test-secret",
        }

    import kaogong.article_ai as article_ai_mod
    import kaogong.clip as clip_mod
    monkeypatch.setattr(clip_mod, "clip_article", fake_clip)
    monkeypatch.setattr(article_ai_mod, "analyze_article", fake_analyze)

    # When: clipping completes with per-article AI degradation.
    assert clip_content(target, tmp_path, cfg={}) == 60

    # Then: the report is bounded and contains only IDs plus reason codes.
    report = json.loads((tmp_path / "_reports" / f"{target.isoformat()}.json").read_text(encoding="utf-8"))
    assert report["aiError"] == 60
    assert len(report["aiFailures"]) == 50
    assert report["aiFailures"][0] == {"articleId": "0", "reason": "ai_provider:request_failed"}
    assert "SECRET-ARTICLE-BODY" not in json.dumps(report, ensure_ascii=False)
    assert "test-secret" not in json.dumps(report, ensure_ascii=False)


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


@pytest.mark.parametrize(("current", "expected"), [(5, "ok"), (4, "failed")])
def test_quality_gate_enforces_half_of_volume_median_baseline(tmp_path, current, expected):
    # Given: 5-window median baseline of ten (values 10/20/10); outliers and failed reports excluded.
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, dt.date(2026, 8, 9), candidates=10, articles=10, qualityStatus="ok")
    _write_report(tmp_path, dt.date(2026, 8, 10), candidates=20, articles=20, qualityStatus="ok")
    _write_report(tmp_path, dt.date(2026, 8, 11), candidates=0, articles=0, qualityStatus="ok")
    _write_report(tmp_path, dt.date(2026, 8, 12), candidates=100, articles=100, qualityStatus="failed")
    _write_report(tmp_path, dt.date(2026, 8, 13), candidates=10, articles=10, qualityStatus="degraded")
    _write_report(tmp_path, dt.date(2026, 8, 15), candidates=999, articles=999, qualityStatus="ok")
    _write_report(tmp_path, target, candidates=current, articles=current)

    # When: candidate and article volume are compared independently.
    result = quality_gate(target, tmp_path)

    # Then: exactly fifty percent passes, while anything below is fatal.
    assert result["qualityStatus"] == expected
    assert len(result["volumeErrors"]) == (0 if expected == "ok" else 2)


def test_quality_gate_skips_volume_check_without_valid_baseline(tmp_path):
    # Given: all earlier reports are failed or have zero metrics.
    target = dt.date(2026, 8, 14)
    _write_digest(tmp_path, target)
    _write_report(tmp_path, dt.date(2026, 8, 12), candidates=10, articles=10, qualityStatus="failed")
    _write_report(tmp_path, dt.date(2026, 8, 13), candidates=0, articles=0, qualityStatus="degraded")
    _write_report(tmp_path, target, candidates=1, articles=1)

    # When: the publication gate runs.
    result = quality_gate(target, tmp_path)

    # Then: absent nonzero nonfailed baselines do not invent a failure threshold.
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


def test_pick_top_scores_and_selects_top_cap(monkeypatch):
    # Given: 一个槽位当天候选超过上限，用 AI 评分挑重点。
    from kaogong.models import Candidate
    from kaogong.pipeline import _pick_top

    def fake_judge(item, article, cfg, **kw):
        score = 90 if "重点" in item["title"] else 50
        return {"score": score, "verdict": "keep", "reason": "x", "newTitle": "", "newSummary": ""}

    monkeypatch.setattr("kaogong.pipeline.judge_item", fake_judge)
    cands = [
        Candidate(title="普通A", url="u1", date=dt.date(2026, 8, 12), slot="nf"),
        Candidate(title="重点B", url="u2", date=dt.date(2026, 8, 12), slot="nf"),
        Candidate(title="普通C", url="u3", date=dt.date(2026, 8, 12), slot="nf"),
    ]

    # When: 按分数选 top 2。
    picked = _pick_top(cands, 2, {"deepseek_api_key": "k"})

    # Then: 重点B 靠前入选，普通A 其次。
    assert [c.title for c in picked] == ["重点B", "普通A"]


def test_pick_top_without_key_keeps_list_order():
    # Given: 无 DeepSeek key（评分全部退化为 0）。
    from kaogong.models import Candidate
    from kaogong.pipeline import _pick_top

    cands = [
        Candidate(title="普通A", url="u1", date=dt.date(2026, 8, 12), slot="nf"),
        Candidate(title="重点B", url="u2", date=dt.date(2026, 8, 12), slot="nf"),
    ]

    # When: 按槽位上限 1 选取。
    picked = _pick_top(cands, 1, {"deepseek_api_key": ""})

    # Then: 稳定排序保持列表顺序（退化行为）。
    assert [c.title for c in picked] == ["普通A"]
