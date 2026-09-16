# -*- coding: utf-8 -*-
"""本地审核服务测试：北京时间日期、参数校验、补跑 AI 守卫、发布拦截、界面纪律。"""
import datetime as dt
import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import kaogong.review.server as server

UTC = dt.timezone.utc

# 仓库根 content/（测试进程真实写入目标）——用于断言测试不污染真实审计日志
REAL_AUDIT_LOG = Path(__file__).resolve().parents[2] / "content" / "_reports" / "audit.jsonl"


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


def test_audit_never_writes_real_content_log(tmp_path, monkeypatch):
    """防回归：审计日志路径必须随 CONTENT 动态解析，测试不得污染真实 content/。

    修复前必失败：AUDIT_LOG 是模块级常量（导入时固化），monkeypatch CONTENT 到
    tmp_path 后 _audit 仍写真实 content/_reports/audit.jsonl——实测真实日志 597 行中
    486 行是测试噪音（假 publish / retry / note）。
    """
    before = REAL_AUDIT_LOG.stat().st_size if REAL_AUDIT_LOG.exists() else 0
    monkeypatch.setattr(server, "CONTENT", tmp_path)

    server._audit(dt.date(2026, 8, 15), "test-only", "x1", {"probe": True})

    after = REAL_AUDIT_LOG.stat().st_size if REAL_AUDIT_LOG.exists() else 0
    assert after == before, "测试写入了真实审计日志（路径未跟随 CONTENT）"
    scoped = tmp_path / "_reports" / "audit.jsonl"
    assert scoped.exists(), "审计应写入被 patch 的 CONTENT"
    assert "test-only" in scoped.read_text(encoding="utf-8")


# ─────────── 设计令牌接线（规范 v3 §4.1 / §8 第 1 步的验收信号）───────────


def test_tokens_css_route_serves_generated_tokens(client: TestClient):
    """验收信号②：/review/tokens.css 返回 200 且是 CSS。"""
    resp = client.get("/review/tokens.css")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/css")

    css = resp.text
    assert "请勿手改" in css and "SOURCE_SHA256:" in css
    # 验收信号①：无品牌裸 hex——品牌色必须以变量的形式提供，而不是散落在页面里
    assert "--kg-brand: #3A4785;" in css


def test_tokens_css_route_404s_when_generator_not_run(client: TestClient, monkeypatch, tmp_path):
    """生成器没跑过时应给出可执行的提示，而不是 500 或空白样式。"""
    monkeypatch.setattr(server, "UI_TOKENS_CSS", tmp_path / "missing.css")
    resp = client.get("/review/tokens.css")
    assert resp.status_code == 404
    assert "generate" in resp.json()["detail"]


def test_admin_index_links_tokens_after_pinned_tabler(client: TestClient):
    """验收信号③的一部分：link 必须存在、必须位于 Tabler 之后，且 Tabler 已锁版本。"""
    html = client.get("/").text
    tabler_at = html.find("@tabler/core@")
    tokens_at = html.find("/review/tokens.css")
    assert tabler_at != -1, "Tabler CDN 链接不见了"
    assert tokens_at != -1, "未引入 tokens.css"
    assert "@tabler/core@latest" not in html, "Tabler 未锁版本（规范 §7 债务 2）"
    assert tabler_at < tokens_at, "tokens.css 必须置于 Tabler 之后，否则覆盖不生效"


# ─────────── AI 审核结果的日期归属（2026-09-15 修复）───────────
#
# `_review_state` 是模块级全局单例，只保存「最近一次」审核结果；
# `apply_decisions` 又是**按位置下标**逐条套用的，不做任何 id 匹配。
# 二者叠加 → 对 A 日跑完审核、把日期切到 B 日再点「应用」，
# A 日的 drop/rewrite 判定会被套到 B 日的条目上（误删误改，且只能整批回退）。


def _stub_review_state(reviewed_date: str, decisions: list[dict]) -> dict:
    return {
        "running": False, "step": "", "log": "", "done": True, "ok": True,
        "report": {
            "date": reviewed_date,
            "agent": "review-agent-v1",
            "decisions": decisions,
            "summary": {},
        },
    }


def test_review_apply_rejects_mismatched_date(client, tmp_path, monkeypatch):
    """跨日期应用必须被拒绝，且目标日报必须原封不动。"""
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    _write_day(tmp_path, "2026-09-14", [{"title": "甲", "sourceUrl": "https://x/14"}])
    _write_day(tmp_path, "2026-09-15", [{"title": "乙", "sourceUrl": "https://x/15"}])
    monkeypatch.setattr(server, "_review_state", _stub_review_state(
        "2026-09-14",
        [{"verdict": "drop", "articleId": "a1", "title": "甲", "reason": "不相关"}],
    ))

    body = client.post("/api/review-agent/apply", json={"date": "2026-09-15"}).json()

    assert body["ok"] is False
    assert body["step"] == "日期不一致"
    assert "2026-09-14" in body["log"] and "2026-09-15" in body["log"]

    # 09-15 的日报必须未被触碰，也不该留下可被 rollback 误用的 .bak
    digest = json.loads((tmp_path / "2026-09-15" / "digest.json").read_text(encoding="utf-8"))
    assert len(digest["sections"][0]["items"]) == 1
    assert digest["sections"][0]["items"][0]["title"] == "乙"
    assert not (tmp_path / "2026-09-15" / "digest.json.bak").exists()


def test_review_apply_accepts_matching_date(client, tmp_path, monkeypatch):
    """同日期应用照常工作（守卫不能把正常路径一起拦掉）。"""
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    _write_day(tmp_path, "2026-09-15", [
        {"title": "甲", "sourceUrl": "https://x/15a"},
        {"title": "乙", "sourceUrl": "https://x/15b"},
    ])
    _write_report_file(tmp_path, "2026-09-15", {"date": "2026-09-15"})
    monkeypatch.setattr(server, "_review_state", _stub_review_state(
        "2026-09-15",
        [
            {"verdict": "drop", "articleId": "a1", "title": "甲", "reason": "不相关"},
            {"verdict": "keep", "articleId": "a2", "title": "乙", "score": 90},
        ],
    ))

    body = client.post("/api/review-agent/apply", json={"date": "2026-09-15"}).json()

    assert body["ok"] is True
    assert body["appliedCount"] == 1
    digest = json.loads((tmp_path / "2026-09-15" / "digest.json").read_text(encoding="utf-8"))
    items = digest["sections"][0]["items"]
    assert [it["title"] for it in items] == ["乙"]
    assert (tmp_path / "2026-09-15" / "digest.json.bak").exists(), "应用前必须留备份供回退"


def test_review_apply_without_result_is_rejected(client, tmp_path, monkeypatch):
    """没跑过审核时给可执行提示，而不是套用一份空判定。"""
    monkeypatch.setattr(server, "CONTENT", tmp_path)
    _write_day(tmp_path, "2026-09-15", [{"title": "甲", "sourceUrl": "https://x/15"}])
    monkeypatch.setattr(server, "_review_state", {
        "running": False, "step": "", "log": "", "done": False, "ok": False, "report": None,
    })

    body = client.post("/api/review-agent/apply", json={"date": "2026-09-15"}).json()

    assert body["ok"] is False
    assert "开始 AI 审核" in body["log"]


# ─────────── 审核端界面纪律（三端统一，2026-09-15）───────────
#
# 三条纪律：
#   1. **界面控件层零 emoji** —— Web 构建产物与鸿蒙 UI 实测都是 0；审核端此前有 20+ 处
#      （🤖🔁📌🗑↩✅❌⚠️）。例外只有 `#log`：它是等价的命令行输出，✅/❌ 用于长日志定位成败行。
#   2. **编辑器必须有入口** —— /editor/{article_id} 是一整页，曾零引用（只能手敲 URL）。
#   3. **死代码不得回流** —— 见 test_review_ui_has_no_dead_helpers 的清单。

# 界面层 emoji 黑名单（只查标记段，不查 <script>）
_UI_EMOJI = "🤖🔁📌🗑↩✅❌⚠️"


def _strip_comments(text: str) -> str:
    """剥掉 HTML 注释与 /* */ 块注释——注释里出现 ⚠️ 不算界面 emoji。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def test_review_ui_markup_has_no_emoji():
    """标记段（<script> 之前）零 emoji：状态一律纯文字 + 颜色强化，不靠颜色单独表意。"""
    html = _strip_comments(server.UI.read_text(encoding="utf-8"))
    markup = html.split("<script>", 1)[0]
    offenders = [e for e in _UI_EMOJI if e in markup]
    assert not offenders, f"审核端标记段出现 emoji：{offenders}"


def test_review_ui_dropped_emoji_strings_stay_dropped():
    """已被清掉的界面文案不得回流（这些字符串直接进 DOM，不是日志）。"""
    html = _strip_comments(server.UI.read_text(encoding="utf-8"))
    for bad in ("🤖 AI 速览与标注", "🔁 重试", "📌 强制收录", "🗑 排除", "↩ 恢复",
                "❌ 剪藏失败", "✅ 已剪藏", "⚠️ AI 失败", "✅ AI 成功",
                "✅ 已上传", "❌ 上传失败", "✅ 新邀请码", "❌ 生成失败"):
        assert bad not in html, f"界面文案又带上了 emoji：{bad!r}"


def test_review_ui_exposes_relation_editor_entry():
    """关系标注编辑器必须有入口。

    `/editor/{article_id}`（editor.html：荧光笔 → 吸附 → 箭头素材库 → 样式面板）是一整页，
    但 index.html 里一度零引用 —— 只能手敲 URL 才到得了，等于功能不存在。
    """
    html = _strip_comments(server.UI.read_text(encoding="utf-8"))
    assert 'data-act="editor"' in html, "状态面板里没有关系标注入口按钮"
    assert "/editor/" in html, "入口没有指向 /editor/{id}"


def test_review_ui_has_no_dead_helpers():
    """防回归：已删除的死代码不得被重新引入。

    断言前剥注释 —— 否则「解释为什么删掉它」的注释本身会把测试打红。
    """
    html = _strip_comments(server.UI.read_text(encoding="utf-8"))
    # articleIdOf 永远 return null（前端算不出后端那份 MD5）；clipMap 建完从不被读；
    # lazyOnHover 的四个包裹层在画布 14 收拢视图时就不存在了 → 纯 no-op。
    for token in ("function articleIdOf", "function buildClipMap", "function lazyOnHover"):
        assert token not in html, f"死代码 {token} 又回来了"


def test_review_ui_empty_state_selector_is_scoped():
    """`.empty` 必须按 id 取。

    队列区（#aside）在 DOM 上排在预览区之前，且会在「当前筛选下无条目」时动态插一个 .empty；
    `document.querySelector(".empty")` 会命中队列那个 —— 选中文章时会隐藏错元素。
    """
    html = _strip_comments(server.UI.read_text(encoding="utf-8"))
    assert 'id="preview-empty"' in html, "预览区空态缺少 id"
    assert 'querySelector(".empty")' not in html, "又出现了不收敛的 .empty 全局选择器"



