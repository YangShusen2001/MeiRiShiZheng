# -*- coding: utf-8 -*-
import json

import kaogong.__main__ as cli


def test_main_emits_json_completion_event_and_fails_quality_gate(tmp_path, monkeypatch, capsys):
    # Given: pipeline stages complete but the quality gate fails.
    digest = tmp_path / "2026-08-12" / "digest.json"
    monkeypatch.setattr(cli, "build_content", lambda target, content_dir: digest)
    monkeypatch.setattr(cli, "clip_content", lambda target, content_dir: 0)
    monkeypatch.setattr(cli, "practice_content", lambda target, content_dir: None)
    monkeypatch.setattr(cli, "summary_content", lambda target, content_dir: None)
    monkeypatch.setattr(cli, "curate_content", lambda target, content_dir, **kw: {
        "curation": {"candidates": 0, "picked": 0},
    })
    monkeypatch.setattr(cli, "quality_gate", lambda target, content_dir: {"qualityStatus": "failed"})

    # When: the CLI executes through its real main boundary.
    exit_code = cli.main(["2026-08-12", "--content-dir", str(tmp_path)])

    # Then: automation receives structured completion and a nonzero exit code.
    event = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert event == {
        "event": "pipeline.complete",
        "date": "2026-08-12",
        "digest": str(digest),
        "articles": 0,
        "practice": None,
        "summary": None,
        "curation": {"candidates": 0, "picked": 0},
        "qualityStatus": "failed",
    }


def test_main_curate_only_skips_fetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "curate_content", lambda target, content_dir, **kw: {
        "curation": {"candidates": 3, "picked": 2},
    })
    exit_code = cli.main(["2026-08-12", "--content-dir", str(tmp_path), "--curate-only"])
    event = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert event == {"event": "pipeline.curate", "date": "2026-08-12",
                     "curation": {"candidates": 3, "picked": 2}}


def test_main_reanalyze_skips_fetch_and_reports_rewritten(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "reanalyze_content", lambda target, content_dir, **kwargs: 3)
    monkeypatch.setattr(cli, "quality_gate", lambda target, content_dir: {"qualityStatus": "ok"})

    exit_code = cli.main(["2026-08-13", "--content-dir", str(tmp_path), "--reanalyze"])

    event = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert event == {
        "event": "pipeline.reanalyze",
        "date": "2026-08-13",
        "rewritten": 3,
        "qualityStatus": "ok",
    }


def test_main_reanalyze_fails_quality_gate(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "reanalyze_content", lambda target, content_dir, **kwargs: 0)
    monkeypatch.setattr(cli, "quality_gate", lambda target, content_dir: {"qualityStatus": "failed"})

    exit_code = cli.main(["2026-08-13", "--content-dir", str(tmp_path), "--reanalyze"])

    event = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert event["qualityStatus"] == "failed"
