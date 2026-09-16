# -*- coding: utf-8 -*-
"""DeepSeek 客户端单测（httpx.MockTransport，不真实联网）。"""
import json

import httpx
import pytest

from kaogong.deepseek import DEFAULT_BASE_URL, DEFAULT_MODEL, chat, load_config


@pytest.fixture(autouse=True)
def _clean_extra_env(monkeypatch):
    """DEEPSEEK_EXTRA_JSON 残留会污染所有「精确相等」断言，逐测试清干净。"""
    monkeypatch.delenv("DEEPSEEK_EXTRA_JSON", raising=False)


def test_load_config_env_priority(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "envkey")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    assert load_config(tmp_path / "missing.json") == {"deepseek_api_key": "envkey"}


def test_load_config_reads_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    p = tmp_path / "config.json"
    p.write_text('{"deepseek_api_key": "filekey"}', encoding="utf-8")
    assert load_config(p) == {"deepseek_api_key": "filekey"}


# ── base_url / model 可配置（2026-09-16：过去是死代码，只有 api_key 能配） ──────
# `chat()` 一直读 cfg 的 deepseek_base_url / deepseek_model，但 load_config 从不产出它们
# → 指向本地 OpenAI 兼容网关（127.0.0.1:7864）时才发现「换端点」根本没法配。


def test_load_config_env_carries_base_url_and_model(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "envkey")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "http://127.0.0.1:7864/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "global:deepseek-v4.1-flash")
    assert load_config(tmp_path / "missing.json") == {
        "deepseek_api_key": "envkey",
        "deepseek_base_url": "http://127.0.0.1:7864/v1",
        "deepseek_model": "global:deepseek-v4.1-flash",
    }


def test_load_config_dotenv_carries_base_url_and_model(monkeypatch, tmp_path):
    """仓库根 .env.local 是 key=value 文本（不是 JSON），base_url/model 同样要能读出来。"""
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.delenv(name, raising=False)
    p = tmp_path / ".env.local"
    p.write_text(
        "DEEPSEEK_API_KEY=filekey\n"
        "DEEPSEEK_BASE_URL=http://127.0.0.1:7864/v1\n"
        "DEEPSEEK_MODEL=global:deepseek-v4.1-flash\n",
        encoding="utf-8",
    )
    assert load_config(p) == {
        "deepseek_api_key": "filekey",
        "deepseek_base_url": "http://127.0.0.1:7864/v1",
        "deepseek_model": "global:deepseek-v4.1-flash",
    }


def test_load_config_omits_unset_endpoint_keys(monkeypatch, tmp_path):
    """没设置就不写默认值 —— 交给 chat() 自己的 DEFAULT_* 兜底，避免默认值被固化进 cfg。"""
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.delenv(name, raising=False)
    p = tmp_path / ".env.local"
    p.write_text("DEEPSEEK_API_KEY=filekey\n", encoding="utf-8")
    assert load_config(p) == {"deepseek_api_key": "filekey"}


def test_load_config_ignores_empty_env_values(monkeypatch, tmp_path):
    """空字符串要当成「没设置」—— fetch-only-today.py 就是靠 setenv('') 来强制走文件。"""
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.setenv(name, "")
    p = tmp_path / ".env.local"
    p.write_text("DEEPSEEK_API_KEY=filekey\nDEEPSEEK_MODEL=filemodel\n", encoding="utf-8")
    assert load_config(p) == {"deepseek_api_key": "filekey", "deepseek_model": "filemodel"}


def test_chat_honors_cfg_base_url_and_model():
    """cfg 里的端点/模型必须真的进请求 —— 这是「能换网关」的硬证据。"""
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    cfg = {
        "deepseek_api_key": "k",
        "deepseek_base_url": "http://127.0.0.1:7864/v1/",  # 末尾斜杠要被 rstrip
        "deepseek_model": "global:deepseek-v4.1-flash",
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        chat([{"role": "user", "content": "hi"}], cfg, client=client)
    assert seen["url"] == "http://127.0.0.1:7864/v1/chat/completions"
    assert seen["model"] == "global:deepseek-v4.1-flash"


def test_chat_falls_back_to_defaults_when_cfg_has_no_endpoint():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["model"] = json.loads(request.content)["model"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        chat([{"role": "user", "content": "hi"}], {"deepseek_api_key": "k"}, client=client)
    assert seen["url"] == DEFAULT_BASE_URL + "/chat/completions"
    assert seen["model"] == DEFAULT_MODEL


def test_chat_requires_key():
    with pytest.raises(RuntimeError):
        chat([{"role": "user", "content": "hi"}], {})


def test_chat_returns_content():
    def handler(request):
        assert request.url.path == "/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == DEFAULT_MODEL
        assert body["messages"][0]["content"] == "hi"
        return httpx.Response(200, json={"choices": [{"message": {"content": "  回答  "}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        out = chat([{"role": "user", "content": "hi"}], {"deepseek_api_key": "k"}, client=client)
    assert out == "回答"


def test_chat_passes_extra_fields():
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        chat(
            [{"role": "user", "content": "hi"}],
            {"deepseek_api_key": "k"},
            extra={"response_format": {"type": "json_object"}},
            client=client,
        )


# ── DEEPSEEK_EXTRA_JSON：附加请求体参数（2026-09-16） ─────────────────────────
# `global:deepseek-v4.1-flash` 是推理模型，max_tokens=1800 时把预算全花在
# reasoning_content 上、content 恒为空 → ai_parse:json_object_missing。
# 加 {"thinking":{"type":"disabled"}} 后 391 tokens 即产出完整 JSON。
# 做成配置项是为了「换网关/换模型不改源码」，也不去动 analyze_article 里写死的 max_tokens。


def test_load_config_env_carries_extra_json(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "envkey")
    monkeypatch.setenv("DEEPSEEK_EXTRA_JSON", '{"thinking":{"type":"disabled"}}')
    assert load_config(tmp_path / "missing.json") == {
        "deepseek_api_key": "envkey",
        "deepseek_extra": {"thinking": {"type": "disabled"}},
    }


def test_load_config_dotenv_carries_extra_json(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    p = tmp_path / ".env.local"
    p.write_text(
        "DEEPSEEK_API_KEY=filekey\n"
        'DEEPSEEK_EXTRA_JSON={"thinking":{"type":"disabled"}}\n',
        encoding="utf-8",
    )
    assert load_config(p) == {
        "deepseek_api_key": "filekey",
        "deepseek_extra": {"thinking": {"type": "disabled"}},
    }


def test_load_config_json_file_accepts_extra_as_object(monkeypatch, tmp_path):
    """JSON 配置里直接写嵌套对象（比塞转义字符串自然），也要认。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    p = tmp_path / "config.json"
    p.write_text(
        json.dumps({"deepseek_api_key": "filekey", "DEEPSEEK_EXTRA_JSON": {"thinking": {"type": "disabled"}}}),
        encoding="utf-8",
    )
    assert load_config(p) == {
        "deepseek_api_key": "filekey",
        "deepseek_extra": {"thinking": {"type": "disabled"}},
    }


def test_load_config_ignores_empty_extra_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "envkey")
    monkeypatch.setenv("DEEPSEEK_EXTRA_JSON", "")
    assert load_config(tmp_path / "missing.json") == {"deepseek_api_key": "envkey"}


def test_load_config_rejects_invalid_extra_json(monkeypatch, tmp_path):
    """非法 JSON 必须抛错而不是静默忽略 —— 静默会让「参数没生效」变成难查的玄学。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    p = tmp_path / ".env.local"
    p.write_text("DEEPSEEK_API_KEY=filekey\nDEEPSEEK_EXTRA_JSON={坏\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)


def test_load_config_rejects_non_object_extra_json(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    p = tmp_path / ".env.local"
    p.write_text("DEEPSEEK_API_KEY=filekey\nDEEPSEEK_EXTRA_JSON=[1,2]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)


def test_chat_merges_cfg_extra_into_payload():
    """配置级附加参数必须真的进请求体 —— 这是「关思考」生效的硬证据。"""
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    cfg = {
        "deepseek_api_key": "k",
        "deepseek_extra": {"thinking": {"type": "disabled"}},
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        chat([{"role": "user", "content": "hi"}], cfg, client=client)
    assert seen["thinking"] == {"type": "disabled"}
    assert seen["max_tokens"] == 1200  # 其余字段不受影响


def test_chat_explicit_extra_overrides_cfg_extra():
    """调用级 extra 优先级更高（便于单点覆盖，不必改配置）。"""
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    cfg = {
        "deepseek_api_key": "k",
        "deepseek_extra": {"thinking": {"type": "disabled"}, "temperature": 0.9},
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        chat([{"role": "user", "content": "hi"}], cfg, extra={"temperature": 0.1}, client=client)
    assert seen["temperature"] == 0.1
    assert seen["thinking"] == {"type": "disabled"}
