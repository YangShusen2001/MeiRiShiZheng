# -*- coding: utf-8 -*-
"""DeepSeek 客户端（移植自原 site_builder/deepseek.py）。

标准化改动：urllib → httpx（可注入 mock 测试）；其余签名与返回保持兼容。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def load_config(config_path: Path | None = None) -> dict[str, str]:
    """DEEPSEEK_API_KEY 环境变量优先，其次读 config.json / 仓库根 .env.local；无 key 返回空 dict。"""
    env_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if env_key:
        return {"deepseek_api_key": env_key}
    if config_path is None or not config_path.exists():
        # CLI 兜底：python -m kaogong 直接跑时自动读仓库根 .env.local（审核台 bat 注入的同一份）
        config_path = Path(__file__).resolve().parents[3] / ".env.local"
        if not config_path.exists():
            return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        # .env.local 是 key=value 文本而非 JSON（Windows CRLF 常见），按行解析
        values = {}
        for line in config_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip().rstrip("\r")
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
        key = values.get("DEEPSEEK_API_KEY", "").strip()
        return {"deepseek_api_key": key} if key else {}


def chat(
    messages: list[dict[str, str]],
    cfg: dict[str, str],
    max_tokens: int = 1200,
    temperature: float = 0.7,
    timeout: float = 120,
    extra: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
) -> str:
    """调用 DeepSeek chat/completions，返回首条回复文本。client 可注入（测试用 mock）。"""
    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key:
        raise RuntimeError("未配置 DeepSeek API Key")
    model = cfg.get("deepseek_model") or DEFAULT_MODEL
    base = (cfg.get("deepseek_base_url") or DEFAULT_BASE_URL).rstrip("/")
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra:
        payload.update(extra)
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}

    def _post(c: httpx.Client) -> str:
        r = c.post(base + "/chat/completions", json=payload, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

    if client is not None:
        return _post(client)
    with httpx.Client() as c:
        return _post(c)
