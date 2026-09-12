"""Publication quality helpers for content artifacts and run volume."""
from __future__ import annotations

import datetime as dt
import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

MAX_QUALITY_ERRORS = 50

FORMAT_CHECKER = FormatChecker()
STANDARD_FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("public-http-url", raises=ValueError)
def _is_public_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return "." in hostname
    return address.is_global


@FORMAT_CHECKER.checks("month-day", raises=ValueError)
def _is_month_day(value: str) -> bool:
    return dt.datetime.strptime(value, "%m-%d").strftime("%m-%d") == value


@FORMAT_CHECKER.checks("strict-date-time", raises=ValueError)
def _is_strict_date_time(value: str) -> bool:
    return "T" in value and STANDARD_FORMAT_CHECKER.conforms(value, "date-time")


@dataclass(frozen=True, slots=True)
class Artifact:
    path: Path
    kind: str
    data: Mapping[str, object]


def classify_artifact(path: Path) -> str | None:
    # 考点卡片：content/cards/ 下的卡组 JSON（策展静态内容，非管道产出）
    if path.parent.name == "cards" and path.suffix == ".json":
        return "card"
    match path.name:
        case "digest.json":
            return "digest"
        case "practice.json":
            return "practice"
        case "summary.json":
            return "summary"
        case "policy-lines.json":
            return "policy-lines"
        case "picks.json":
            return "picks"
        case name if name.startswith("article-") and name.endswith(".json"):
            return "article"
        case _:
            return None


def load_artifact(path: Path) -> Artifact:
    kind = classify_artifact(path)
    if kind is None:
        raise ValueError("unsupported artifact filename")
    return Artifact(path=path, kind=kind, data=json.loads(path.read_text(encoding="utf-8")))


def schema_errors(artifact: Artifact, schema: Mapping[str, object]) -> list[dict[str, str]]:
    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    errors = sorted(
        validator.iter_errors(artifact.data),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        {"file": artifact.path.name, "error": f"schema:{error.validator}"}
        for error in errors[:MAX_QUALITY_ERRORS]
    ]


def artifact_semantic_errors(artifact: Artifact) -> list[dict[str, str]]:
    errors: list[str] = []
    match artifact.kind:
        case "article":
            if artifact.data.get("aiStatus") == "ok":
                from .article_ai import validate_article_ai

                errors.extend(validate_article_ai(dict(artifact.data)))
        case "digest":
            expected = str(artifact.data.get("date", ""))[5:]
            for section in artifact.data.get("sections", []):
                for item in section.get("items", []):
                    if item.get("date") != expected:
                        errors.append("digest_item_date_mismatch")
        case "practice":
            if artifact.data.get("total") != len(artifact.data.get("questions", [])):
                errors.append("practice_total_mismatch")
        case "summary":
            # summary.json（今日速览）的语义已由 summary.schema.json 校验覆盖，无额外语义规则
            pass
        case "card":
            # 考点卡片：语义（一问一答、原子、非空）已由 card.schema.json 校验覆盖，无额外语义规则
            pass
        case "picks":
            # 选材定稿：结构已由 picks.schema.json 校验覆盖；picked 与槽位一致性由 gate 兜底
            pass
        case _:
            raise AssertionError(f"unexpected artifact kind: {artifact.kind}")
    return [
        {"file": artifact.path.name, "error": error}
        for error in errors[:MAX_QUALITY_ERRORS]
    ]


# v2.1 转向后校准（2026-09-12 用户拍板，pivot 方案 §9 后续）：数量体检不再用
# 「相对近期基线」——精品转向后低量级是设计目标（≤15 篇/日），相对基线会把
# 「天生日薄（合法 sparse）」误报为「源故障」。真正的源故障信号在 fetch 层：
# 13 源经栏目白名单后正常日 candidatesRaw ~10-20，跌破绝对下限意味着多源故障
# 或白名单配置错误。candidates/articles 的后置门禁量不再做数量体检（candidates==0
# 仍由 quality_gate 直接判 failed 兜底）。
VOLUME_FETCH_RAW_FLOOR = 5


def volume_errors(current: Mapping[str, object]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    fetch = current.get("fetch")
    if isinstance(fetch, Mapping):
        raw = fetch.get("candidatesRaw")
        if isinstance(raw, int) and 0 <= raw < VOLUME_FETCH_RAW_FLOOR:
            errors.append({
                "metric": "candidatesRaw",
                "error": "below_fetch_floor",
                "floor": VOLUME_FETCH_RAW_FLOOR,
            })
    return errors[:MAX_QUALITY_ERRORS]
