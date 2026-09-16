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

# 环境变量名 ↔ 内部键名。`chat()` 读 cfg 里的三个键，所以三者必须都能从外部配置。
_ENV_TO_CFG = (
    ("DEEPSEEK_API_KEY", "deepseek_api_key"),
    ("DEEPSEEK_BASE_URL", "deepseek_base_url"),
    ("DEEPSEEK_MODEL", "deepseek_model"),
)

# 附加请求体参数（JSON 对象）。用途：网关/模型需要额外开关时不必改源码。
# 典型：推理模型关思考 → {"thinking":{"type":"disabled"}}。
# 见 2026-09-16：`global:deepseek-v4.1-flash` 在 max_tokens=1800 下把预算全烧在
# reasoning 上、content 恒为空；关思考后 391 tokens 出完整 JSON（省 87%）。
_EXTRA_ENV = "DEEPSEEK_EXTRA_JSON"

# `load_config()` 的返回形状：三个字符串键 + 可选的 `deepseek_extra`（值是 dict）。
# ⚠️ 所以它**不是** `dict[str, str]` —— 凡是接收 cfg 的函数一律用这个别名，
# 别退回写 `dict[str, str]`：那会让人误以为可以安全地 `",".join(cfg.values())`。
Cfg = dict[str, Any]


def _parse_extra(raw: Any) -> dict[str, Any]:
    """解析附加请求体参数。空值 = 不附加。

    非法 JSON **直接抛错**而不是静默忽略 —— 静默会让「参数没生效」变成难查的玄学。
    """
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{_EXTRA_ENV} 不是合法 JSON：{exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{_EXTRA_ENV} 必须是 JSON 对象，收到 {type(doc).__name__}")
    return doc


def _from_env() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for env_name, cfg_key in _ENV_TO_CFG:
        value = (os.environ.get(env_name) or "").strip()
        if value:
            out[cfg_key] = value
    extra = _parse_extra(os.environ.get(_EXTRA_ENV, ""))
    if extra:
        out["deepseek_extra"] = extra
    return out


def load_config(config_path: Path | None = None) -> Cfg:
    """DEEPSEEK_API_KEY 环境变量优先，其次读 config.json / 仓库根 .env.local；无 key 返回空 dict。

    ⚠️ **base_url / model 也必须产出**：`chat()` 一直在读 `cfg.get("deepseek_base_url")`
    与 `cfg.get("deepseek_model")`，但本函数过去只产出 `deepseek_api_key` ——
    于是「换端点 / 换模型」是**死代码**，只能改源码。
    2026-09-16 要把管道指向本地 OpenAI 兼容网关（`http://127.0.0.1:7864/v1`）才发现。
    现在三者统一从环境变量或配置文件读取；**未设置时不写默认值**，
    让 `chat()` 自己的 `DEFAULT_BASE_URL` / `DEFAULT_MODEL` 兜底。
    """
    env = _from_env()
    if env.get("deepseek_api_key"):
        return env
    if config_path is None or not config_path.exists():
        # CLI 兜底：python -m kaogong 直接跑时自动读仓库根 .env.local（审核台 bat 注入的同一份）
        config_path = Path(__file__).resolve().parents[3] / ".env.local"
        if not config_path.exists():
            return {}
    try:
        doc = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        doc = None  # 不是 JSON → 走下面的 key=value 文本分支
    if doc is not None:
        if not isinstance(doc, dict):
            return {}
        result: dict[str, Any] = {
            cfg_key: str(doc[cfg_key]).strip() for _, cfg_key in _ENV_TO_CFG if doc.get(cfg_key)
        }
        # 放在 try 之外：非法 DEEPSEEK_EXTRA_JSON 要抛错，不能被文本分支兜住
        extra = _parse_extra(doc.get(_EXTRA_ENV))
        if extra:
            result["deepseek_extra"] = extra
        return result
    # .env.local 是 key=value 文本而非 JSON（Windows CRLF 常见），按行解析
    values = {}
    for line in config_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().rstrip("\r")
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    result = {cfg_key: values[env_name] for env_name, cfg_key in _ENV_TO_CFG if values.get(env_name)}
    extra = _parse_extra(values.get(_EXTRA_ENV))
    if extra:
        result["deepseek_extra"] = extra
    return result


def chat(
    messages: list[dict[str, str]],
    cfg: Cfg,
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
    cfg_extra = cfg.get("deepseek_extra")
    if isinstance(cfg_extra, dict) and cfg_extra:
        # 配置级附加参数（如推理模型关思考）；显式 extra 参数优先级更高，故放前面
        payload.update(cfg_extra)
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
