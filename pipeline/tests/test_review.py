# -*- coding: utf-8 -*-
"""本地审核服务测试：北京时间日期、参数校验、补跑 AI 守卫、发布拦截。"""
import datetime as dt
import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import kaogong.review.server as server

UTC = dt.timezone.utc


@pytest.fixture()
def client() -> TestClient:
    return TestClient(server.app)


def test_beijing_today_crosses_utc_midnight():
    # UTC 16:00 08-16 = 北京 08-17 00:00（次日）
    assert server.beijing_today(dt.datetime(2026, 8, 16, 16, 0, tzinfo=UTC)) == dt.date(2026, 8, 17)
    # UTC 15:59 08-16 = 北京 08-16 23:59（当日）
    assert server.beijing_today(dt.datetime(2026, 8, 16, 15, 59, tzinfo=UTC)) == dt.date(2026, 8, 16)


def test_parse_target_rejects_invalid_date():
    with pytest.raises(HTTPException) as exc:
        server._parse_target("2026-13-99")
    assert exc.value.status_code == 400


def test_parse_target_defaults_to_beijing_today(monkeypatch):
    monkeypatch.setattr(server, "beijing_today", lambda: dt.date(2026, 8, 17))
    assert server._parse_target("") == dt.date(2026, 8, 17)


def test_default_api_base_is_real_worker_url(monkeypatch):
    """发布修复（2026-08-20）：环境变量缺失时兜底必须是真实 Worker 地址，杜绝 api.example.com。"""
    monkeypatch.delenv("PUBLIC_API_BASE", raising=False)
    base = server._default_api_base()
    assert base.startswith("https://")
    assert "example.com" not in base


def test_reanalyze_default_cleans_without_ai_key(client, tmp_path, monkeypatch):
    # 默认补跑只清洗正文/重定位标注，不调用 AI，无 key 也允许
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    day = tmp_path / "2026-08-15"
    day.mkdir()
    (day / "article-x.json").write_text(json.dumps({"id": "x", "status": "ok",
        "paragraphs": ["&emsp;干净正文。"]}), encoding="utf-8")
    reports = tmp_path / "_reports"
    reports.mkdir()
    (reports / "2026-08-15.json").write_text(json.dumps({
        "date": "2026-08-15", "articles": 1, "aiOk": 0, "aiError": 1,
    }), encoding="utf-8")
    response = client.post("/api/reanalyze", json={"date": "2026-08-15"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["rewritten"] >= 0


def test_reanalyze_force_requires_ai_key(client, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    response = client.post("/api/reanalyze", json={"date": "2026-08-15", "force": True})
    assert response.status_code == 400
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_publish_blocked_by_latest_failed_report(client, tmp_path, monkeypatch):
    reports = tmp_path / "_reports"
    reports.mkdir(parents=True)
    (reports / "2026-08-16.json").write_text(json.dumps({
        "date": "2026-08-16", "qualityStatus": "failed",
        "candidates": 0, "articles": 0, "aiError": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    response = client.post("/api/publish")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["step"] == "质量门禁"
    assert "2026-08-16" in body["log"]


def test_publish_allowed_without_failed_report(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setattr(server, "_run", lambda cmd, cwd: (True, "fake build+deploy ok"))
    response = client.post("/api/publish")
    assert response.status_code == 200
    assert response.json()["started"] is True
    # 后台线程很快完成，轮询状态直到 done
    import time
    status = client.get("/api/publish/status").json()
    for _ in range(100):
        if status["done"]:
            break
        time.sleep(0.02)
        status = client.get("/api/publish/status").json()
    assert status["done"] is True
    assert status["ok"] is True
    assert "fake build+deploy ok" in status["log"]


def test_publish_blocked_without_cloudflare_credentials(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    response = client.post("/api/publish")
    body = response.json()
    assert body["ok"] is False
    assert body["step"] == "凭证检查"
    assert "CLOUDFLARE_API_TOKEN" in body["log"]


def test_fetch_reports_quality_status(client, tmp_path, monkeypatch):
    """fetch 端点走完整编排后返回质量摘要（不真抓网）。"""
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    digest = tmp_path / "2026-08-15" / "digest.json"
    digest.parent.mkdir(parents=True)
    digest.write_text(json.dumps({"date": "2026-08-15", "title": "t", "sections": []}), encoding="utf-8")
    report_dir = tmp_path / "_reports"
    report_dir.mkdir(parents=True)
    (report_dir / "2026-08-15.json").write_text(json.dumps({
        "date": "2026-08-15", "qualityStatus": "degraded",
        "sourcesOk": 15, "sourceErrors": [], "candidates": 3, "articles": 2,
        "aiOk": 1, "aiError": 1, "aiFailures": [{"articleId": "a", "reason": "ai_config:missing_api_key"}],
        "locationErrors": 0,
    }), encoding="utf-8")
    monkeypatch.setattr(server, "build_content", lambda target, content_dir: digest)
    monkeypatch.setattr(server, "clip_content", lambda target, content_dir: 2)
    monkeypatch.setattr(server, "practice_content", lambda target, content_dir: None)
    monkeypatch.setattr(server, "quality_gate", lambda target, content_dir: {"qualityStatus": "degraded"})
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    response = client.post("/api/fetch", json={"date": "2026-08-15"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["clips"] == 2
    assert body["aiKeyConfigured"] is False
    assert body["quality"]["qualityStatus"] == "degraded"
    assert body["quality"]["aiError"] == 1


# ===== 0018 审核台：条目视图 / 重试 / 排除 / 报告解释 / 审计 =====

def _write_day(tmp_path, date_str, items):
    day = tmp_path / date_str
    day.mkdir(parents=True, exist_ok=True)
    (day / "digest.json").write_text(
        json.dumps({"date": date_str, "sections": [{"title": "s", "items": items}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return day


def _write_report_file(tmp_path, date_str, payload):
    reports = tmp_path / "_reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{date_str}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_items_view_aggregates_clip_and_ai_status(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    date = "2026-08-15"
    url = "https://example.com/a1"
    aid = server._article_id(url)
    day = _write_day(tmp_path, date, [{"title": "甲", "sourceUrl": url}])
    (day / f"article-{aid}.json").write_text(json.dumps({
        "id": aid, "status": "ok", "aiStatus": "error", "aiError": "ai_api:timeout",
    }, ensure_ascii=False), encoding="utf-8")
    _write_report_file(tmp_path, date, {"date": date, "clipDetails": [
        {"id": aid, "title": "甲", "status": "clip_error", "reason": "fetch_failed:ConnectError:boom"},
    ]})
    r = client.get(f"/api/items/{date}")
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["clipStatus"] == "clip_error"
    assert item["clipError"] == "fetch_failed:ConnectError:boom"
    assert item["aiStatus"] == "error"
    assert item["actions"] == ["retry"]


def test_exclude_and_restore_item(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    monkeypatch.setattr(server, "AUDIT_LOG", tmp_path / "_reports" / "audit.jsonl")
    date = "2026-08-15"
    url = "https://example.com/a2"
    aid = server._article_id(url)
    _write_day(tmp_path, date, [{"title": "乙", "sourceUrl": url}])
    _write_report_file(tmp_path, date, {"date": date})
    r = client.post(f"/api/items/{date}/{aid}/exclude", json={"reason": "视频稿"})
    assert r.status_code == 200
    digest = json.loads((tmp_path / date / "digest.json").read_text(encoding="utf-8"))
    assert len(digest["sections"][0]["items"]) == 0  # 发布即生效
    report = json.loads((tmp_path / "_reports" / f"{date}.json").read_text(encoding="utf-8"))
    assert report["excluded"][0]["reason"] == "视频稿"
    # 恢复：原样插回
    r = client.post(f"/api/items/{date}/{aid}/restore")
    assert r.status_code == 200
    digest = json.loads((tmp_path / date / "digest.json").read_text(encoding="utf-8"))
    assert len(digest["sections"][0]["items"]) == 1
    report = json.loads((tmp_path / "_reports" / f"{date}.json").read_text(encoding="utf-8"))
    assert report["excluded"] == []


def test_retry_failed_reclips_and_analyzes(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    date = "2026-08-15"
    url = "https://example.com/a3"
    aid = server._article_id(url)
    _write_day(tmp_path, date, [{"title": "丙", "sourceUrl": url}])
    _write_report_file(tmp_path, date, {"date": date, "clipDetails": [
        {"id": aid, "status": "clip_error", "reason": "fetch_failed:ConnectError:x"},
    ]})
    monkeypatch.setattr(server, "clip_article", lambda url, title, date, client=None, allow_single=False: {
        "id": aid, "status": "ok", "title": title, "paragraphs": ["第一段", "第二段"], "keySentences": [],
    })
    monkeypatch.setattr(server, "analyze_article", lambda clip, cfg: {**clip, "aiStatus": "ok"})
    r = client.post(f"/api/items/{date}/retry-failed")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["results"][0]["clipStatus"] == "ok"
    assert (tmp_path / date / f"article-{aid}.json").exists()


def test_report_explain_and_note_acknowledges_volume(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    date = "2026-08-15"
    _write_day(tmp_path, date, [{"title": "丁", "sourceUrl": "https://example.com/a4"}])
    _write_report_file(tmp_path, "2026-08-10", {"date": "2026-08-10", "candidates": 20, "articles": 20, "qualityStatus": "ok"})
    _write_report_file(tmp_path, "2026-08-12", {"date": "2026-08-12", "candidates": 20, "articles": 20, "qualityStatus": "ok"})
    _write_report_file(tmp_path, date, {
        "date": date, "candidates": 5, "articles": 5, "sourcesOk": 1,
        "qualityStatus": "failed",
        # 2026-09-12 校准后：门禁重算 volume_errors 读 fetch.candidatesRaw（< 5 触发），
        # 旧 below_half_baseline 相对基线已废除；acknowledge 流以新码验证。
        "fetch": {"candidatesRaw": 3},
        "volumeErrors": [{"metric": "candidatesRaw", "error": "below_fetch_floor", "floor": 5}],
    })
    r = client.get(f"/api/reports/{date}")
    assert r.status_code == 200
    errors = r.json()["errors"]
    assert errors and errors[0]["explain"]  # 人类可读解释
    r = client.post(f"/api/reports/{date}/note", json={"text": "当天源产出少"})
    assert r.status_code == 200
    body = r.json()
    assert body["notes"] == ["当天源产出少"]
    report = json.loads((tmp_path / "_reports" / f"{date}.json").read_text(encoding="utf-8"))
    assert report["volumeErrors"] == []  # 标注后不再拦截
    assert len(report["volumeErrorsAcknowledged"]) > 0  # 保留记录


def test_audit_written_and_history_served(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    monkeypatch.setattr(server, "AUDIT_LOG", tmp_path / "_reports" / "audit.jsonl")
    date = "2026-08-15"
    url = "https://example.com/a5"
    aid = server._article_id(url)
    _write_day(tmp_path, date, [{"title": "戊", "sourceUrl": url}])
    _write_report_file(tmp_path, date, {"date": date})
    client.post(f"/api/items/{date}/{aid}/exclude", json={"reason": "r"})
    lines = (tmp_path / "_reports" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert any("exclude" in line for line in lines)
    h = client.get(f"/api/items/{date}/{aid}/history")
    assert h.status_code == 200
    assert len(h.json()["history"]) >= 1
