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
        case _:
            raise AssertionError(f"unexpected artifact kind: {artifact.kind}")
    return [
        {"file": artifact.path.name, "error": error}
        for error in errors[:MAX_QUALITY_ERRORS]
    ]


# 0018：数量门禁基线取「最近 N 次 ok/degraded 报告的中位数」，避免单日波动误报
VOLUME_BASELINE_WINDOW = 5


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def volume_errors(target: dt.date, report_dir: Path, current: Mapping[str, object]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    prior_reports: list[tuple[dt.date, Mapping[str, object]]] = []
    for path in report_dir.glob("*.json") if report_dir.exists() else []:
        try:
            report_date = dt.date.fromisoformat(path.stem)
            report = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            continue
        if report_date < target and report.get("qualityStatus") in {"ok", "degraded"}:
            prior_reports.append((report_date, report))
    prior_reports.sort(reverse=True, key=lambda entry: entry[0])
    recent = prior_reports[:VOLUME_BASELINE_WINDOW]
    for metric in ("candidates", "articles"):
        values = [
            int(report[metric])
            for _, report in recent
            if isinstance(report.get(metric), int) and int(report[metric]) > 0
        ]
        if not values:
            continue
        baseline = _median(values)
        current_value = current.get(metric)
        if isinstance(current_value, int) and current_value * 2 < baseline:
            errors.append({
                "metric": metric,
                "error": "below_half_baseline",
                "baseline": baseline,
                "window": len(values),
            })
    return errors[:MAX_QUALITY_ERRORS]
