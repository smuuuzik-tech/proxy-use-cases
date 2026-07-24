from __future__ import annotations

import ipaddress
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping


class AnalysisError(ValueError):
    pass


MAX_ROWS = 500_000
MAX_TEXT = 120
ALLOWED_STRATEGIES = {"sticky", "rotating"}


def load_jsonl(path: str | Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    source = Path(path)
    try:
        handle = source.open(encoding="utf-8")
    except OSError as exc:
        raise AnalysisError(f"cannot read input: {exc}") from exc

    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            if len(records) >= MAX_ROWS:
                raise AnalysisError(f"input exceeds {MAX_ROWS} records")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AnalysisError(f"line {line_number}: invalid JSON") from exc
            if not isinstance(record, dict):
                raise AnalysisError(f"line {line_number}: record must be an object")
            records.append(record)

    if not records:
        raise AnalysisError("input contains no records")
    return records


def analyze_records(records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    normalized = [
        _normalize_record(record, index)
        for index, record in enumerate(records, start=1)
    ]
    if not normalized:
        raise AnalysisError("at least one record is required")
    if len(normalized) > MAX_ROWS:
        raise AnalysisError(f"input exceeds {MAX_ROWS} records")

    by_strategy: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in normalized:
        by_strategy[str(record["strategy"])].append(record)

    strategies = {
        strategy: _strategy_summary(strategy, rows)
        for strategy, rows in sorted(by_strategy.items())
    }
    comparison = _comparison(strategies)
    return {
        "schema": "proxy-session-strategy/v1",
        "record_count": len(normalized),
        "strategies": strategies,
        "comparison": comparison,
        "decision_notes": _decision_notes(strategies),
        "method": {
            "success_rate": "successful requests / total requests",
            "p95_latency_ms": "nearest-rank p95 over successful requests",
            "cost_per_success": "sum(cost_units) / successful requests",
            "session_ip_continuity": (
                "same-IP transitions / consecutive transitions inside each session"
            ),
            "exit_ip_change_rate": (
                "changed-IP transitions / consecutive observations in input order"
            ),
        },
    }


def _normalize_record(
    record: Mapping[str, object],
    index: int,
) -> dict[str, object]:
    strategy = _text(record.get("strategy"), "strategy", index).lower()
    if strategy not in ALLOWED_STRATEGIES:
        raise AnalysisError(
            f"record {index}: strategy must be sticky or rotating"
        )
    request_id = _text(record.get("request_id"), "request_id", index)
    session_id = _text(record.get("session_id"), "session_id", index)
    exit_ip = _text(record.get("exit_ip"), "exit_ip", index)
    try:
        ipaddress.ip_address(exit_ip)
    except ValueError as exc:
        raise AnalysisError(f"record {index}: exit_ip is invalid") from exc

    status_code = _bounded_int(record.get("status_code"), "status_code", index, 0, 599)
    latency_ms = _bounded_float(
        record.get("latency_ms"),
        "latency_ms",
        index,
        0,
        600_000,
    )
    cost_units = _bounded_float(
        record.get("cost_units", 0),
        "cost_units",
        index,
        0,
        1_000_000_000,
    )
    success_raw = record.get("success")
    if not isinstance(success_raw, bool):
        raise AnalysisError(f"record {index}: success must be a boolean")

    return {
        "strategy": strategy,
        "request_id": request_id,
        "session_id": session_id,
        "exit_ip": exit_ip,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "cost_units": cost_units,
        "success": success_raw,
    }


def _strategy_summary(
    strategy: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    successful = [row for row in rows if row["success"] is True]
    latencies = [float(row["latency_ms"]) for row in successful]
    status_codes = Counter(str(row["status_code"]) for row in rows)
    error_classes = Counter(
        _status_class(int(row["status_code"]))
        for row in rows
        if row["success"] is False
    )

    sessions: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        sessions[str(row["session_id"])].append(str(row["exit_ip"]))
    same_ip_transitions = 0
    session_transitions = 0
    for exit_ips in sessions.values():
        for previous, current in zip(exit_ips, exit_ips[1:]):
            session_transitions += 1
            if previous == current:
                same_ip_transitions += 1

    input_changes = sum(
        1
        for previous, current in zip(rows, rows[1:])
        if previous["exit_ip"] != current["exit_ip"]
    )
    input_transitions = max(0, len(rows) - 1)
    successes = len(successful)
    total_cost = sum(float(row["cost_units"]) for row in rows)
    success_rate = successes / len(rows)
    continuity = (
        same_ip_transitions / session_transitions
        if session_transitions
        else None
    )

    return {
        "requests": len(rows),
        "successful": successes,
        "success_rate": _round(success_rate),
        "p95_latency_ms": _nearest_rank(latencies, 0.95),
        "total_cost_units": _round(total_cost),
        "cost_per_success": _round(total_cost / successes)
        if successes
        else None,
        "sessions": len(sessions),
        "unique_exit_ips": len({str(row["exit_ip"]) for row in rows}),
        "session_ip_continuity": _round(continuity)
        if continuity is not None
        else None,
        "exit_ip_change_rate": _round(input_changes / input_transitions)
        if input_transitions
        else None,
        "status_codes": dict(sorted(status_codes.items())),
        "failed_request_classes": dict(sorted(error_classes.items())),
        "strategy_expectation": (
            "preserve one exit IP inside a logical session"
            if strategy == "sticky"
            else "change exit IP across independent requests"
        ),
    }


def _comparison(
    strategies: Mapping[str, Mapping[str, object]],
) -> dict[str, object] | None:
    if "sticky" not in strategies or "rotating" not in strategies:
        return None
    sticky = strategies["sticky"]
    rotating = strategies["rotating"]
    return {
        "success_rate_delta_rotating_minus_sticky": _delta(
            rotating.get("success_rate"),
            sticky.get("success_rate"),
        ),
        "p95_latency_delta_ms_rotating_minus_sticky": _delta(
            rotating.get("p95_latency_ms"),
            sticky.get("p95_latency_ms"),
        ),
        "cost_per_success_delta_rotating_minus_sticky": _delta(
            rotating.get("cost_per_success"),
            sticky.get("cost_per_success"),
        ),
    }


def _decision_notes(
    strategies: Mapping[str, Mapping[str, object]],
) -> list[str]:
    notes = [
        (
            "Select a strategy per business transaction, not from aggregate "
            "latency alone."
        ),
        (
            "Compare success rate and cost per success on the same authorized "
            "target mix and concurrency."
        ),
    ]
    sticky = strategies.get("sticky")
    if sticky:
        continuity = sticky.get("session_ip_continuity")
        if isinstance(continuity, (int, float)) and continuity < 0.9:
            notes.append(
                "Sticky continuity is below 0.90; verify session identifiers and pool TTL."
            )
    rotating = strategies.get("rotating")
    if rotating:
        change_rate = rotating.get("exit_ip_change_rate")
        if isinstance(change_rate, (int, float)) and change_rate < 0.5:
            notes.append(
                "Rotating change rate is below 0.50; verify rotation policy and pool size."
            )
    return notes


def _status_class(status_code: int) -> str:
    if status_code == 0:
        return "transport"
    if status_code == 407:
        return "proxy_authentication"
    if status_code == 429:
        return "rate_limited"
    if 400 <= status_code < 500:
        return "http_4xx"
    if status_code >= 500:
        return "http_5xx"
    return "other"


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return _round(ordered[rank - 1])


def _delta(left: object, right: object) -> float | None:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    return _round(float(left) - float(right))


def _text(value: object, field: str, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisError(f"record {index}: {field} is required")
    return value.strip()[:MAX_TEXT]


def _bounded_int(
    value: object,
    field: str,
    index: int,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool):
        raise AnalysisError(f"record {index}: {field} must be an integer")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AnalysisError(f"record {index}: {field} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise AnalysisError(
            f"record {index}: {field} must be between {minimum} and {maximum}"
        )
    return parsed


def _bounded_float(
    value: object,
    field: str,
    index: int,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise AnalysisError(f"record {index}: {field} must be numeric")
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AnalysisError(f"record {index}: {field} must be numeric") from exc
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise AnalysisError(
            f"record {index}: {field} must be between {minimum} and {maximum}"
        )
    return parsed


def _round(value: float) -> float:
    return round(value, 4)
