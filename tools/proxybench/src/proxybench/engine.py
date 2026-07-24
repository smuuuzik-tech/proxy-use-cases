from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_MANIFEST_BYTES = 256 * 1024
MAX_REPORT_BYTES = 5 * 1024 * 1024
MAX_CANDIDATES = 20
RANK_METRICS = (
    "success_rate",
    "cost_per_success",
    "p95_latency_ms",
    "retry_amplification",
)


class BenchmarkError(ValueError):
    """Stable, credential-safe input or report validation error."""

    def __init__(self, message: str, code: str = "INVALID_BENCHMARK") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Candidate:
    name: str
    report: Path
    total_cost: float | None


@dataclass(frozen=True)
class Policy:
    minimum_success_rate: float
    maximum_p95_ms: float
    maximum_retry_amplification: float
    maximum_cost_per_success: float | None
    rank_by: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "minimum_success_rate": self.minimum_success_rate,
            "maximum_p95_ms": self.maximum_p95_ms,
            "maximum_retry_amplification": self.maximum_retry_amplification,
            "maximum_cost_per_success": self.maximum_cost_per_success,
            "rank_by": list(self.rank_by),
        }


@dataclass(frozen=True)
class Benchmark:
    name: str
    currency: str | None
    allow_partial: bool
    policy: Policy
    candidates: tuple[Candidate, ...]


def load_benchmark(path: str | Path) -> Benchmark:
    manifest_path = Path(path)
    payload = _load_json(manifest_path, MAX_MANIFEST_BYTES, "manifest")
    _keys(
        payload,
        {
            "$schema",
            "schema_version",
            "name",
            "currency",
            "allow_partial",
            "policy",
            "candidates",
        },
        {"schema_version", "name", "policy", "candidates"},
        "manifest",
    )
    if payload.get("$schema") not in {
        None,
        "./src/proxybench/benchmark.schema.json",
    }:
        raise BenchmarkError(
            "manifest $schema points to an unsupported contract",
            "UNSUPPORTED_MANIFEST_SCHEMA",
        )
    if payload["schema_version"] != "1.0":
        raise BenchmarkError(
            "manifest schema_version must be 1.0",
            "UNSUPPORTED_MANIFEST_VERSION",
        )
    name = _name(payload["name"], "manifest.name")
    currency_raw = payload.get("currency")
    currency = None
    if currency_raw is not None:
        if not isinstance(currency_raw, str) or not re.fullmatch(
            r"[A-Z]{3}",
            currency_raw,
        ):
            raise BenchmarkError(
                "currency must be a three-letter ISO-style code",
                "INVALID_CURRENCY",
            )
        currency = currency_raw
    allow_partial = payload.get("allow_partial", False)
    if not isinstance(allow_partial, bool):
        raise BenchmarkError("allow_partial must be boolean")

    policy_raw = payload["policy"]
    if not isinstance(policy_raw, dict):
        raise BenchmarkError("policy must be an object")
    _keys(
        policy_raw,
        {
            "minimum_success_rate",
            "maximum_p95_ms",
            "maximum_retry_amplification",
            "maximum_cost_per_success",
            "rank_by",
        },
        {
            "minimum_success_rate",
            "maximum_p95_ms",
            "maximum_retry_amplification",
            "rank_by",
        },
        "policy",
    )
    minimum_success_rate = _number(
        policy_raw["minimum_success_rate"],
        "policy.minimum_success_rate",
        minimum=0,
        maximum=1,
    )
    maximum_p95_ms = _number(
        policy_raw["maximum_p95_ms"],
        "policy.maximum_p95_ms",
        minimum=0.001,
        maximum=600_000,
    )
    maximum_retry_amplification = _number(
        policy_raw["maximum_retry_amplification"],
        "policy.maximum_retry_amplification",
        minimum=1,
        maximum=6,
    )
    maximum_cost_per_success = None
    if policy_raw.get("maximum_cost_per_success") is not None:
        maximum_cost_per_success = _number(
            policy_raw["maximum_cost_per_success"],
            "policy.maximum_cost_per_success",
            minimum=0,
            maximum=1_000_000_000,
        )
    rank_raw = policy_raw["rank_by"]
    if (
        not isinstance(rank_raw, list)
        or len(rank_raw) != len(RANK_METRICS)
        or set(rank_raw) != set(RANK_METRICS)
    ):
        raise BenchmarkError(
            "policy.rank_by must contain each supported metric exactly once",
            "INVALID_RANK_POLICY",
        )
    policy = Policy(
        minimum_success_rate=minimum_success_rate,
        maximum_p95_ms=maximum_p95_ms,
        maximum_retry_amplification=maximum_retry_amplification,
        maximum_cost_per_success=maximum_cost_per_success,
        rank_by=tuple(rank_raw),
    )

    candidates_raw = payload["candidates"]
    if (
        not isinstance(candidates_raw, list)
        or not 2 <= len(candidates_raw) <= MAX_CANDIDATES
    ):
        raise BenchmarkError(
            f"candidates must contain between 2 and {MAX_CANDIDATES} entries"
        )
    candidates: list[Candidate] = []
    names: set[str] = set()
    for index, raw in enumerate(candidates_raw):
        prefix = f"candidates[{index}]"
        if not isinstance(raw, dict):
            raise BenchmarkError(f"{prefix} must be an object")
        _keys(raw, {"name", "report", "total_cost"}, {"name", "report"}, prefix)
        candidate_name = _name(raw["name"], f"{prefix}.name")
        if candidate_name in names:
            raise BenchmarkError("candidate names must be unique")
        names.add(candidate_name)
        report_raw = raw["report"]
        if not isinstance(report_raw, str) or not report_raw.strip():
            raise BenchmarkError(f"{prefix}.report must be a relative path")
        report_path = Path(report_raw)
        if report_path.is_absolute() or ".." in report_path.parts:
            raise BenchmarkError(
                f"{prefix}.report must stay inside the manifest directory",
                "UNSAFE_REPORT_PATH",
            )
        total_cost = None
        if raw.get("total_cost") is not None:
            total_cost = _number(
                raw["total_cost"],
                f"{prefix}.total_cost",
                minimum=0,
                maximum=1_000_000_000,
            )
        manifest_directory = manifest_path.parent.resolve()
        resolved_report = (manifest_directory / report_path).resolve()
        if not resolved_report.is_relative_to(manifest_directory):
            raise BenchmarkError(
                f"{prefix}.report resolves outside the manifest directory",
                "UNSAFE_REPORT_PATH",
            )
        candidates.append(
            Candidate(
                name=candidate_name,
                report=resolved_report,
                total_cost=total_cost,
            )
        )

    has_cost = any(candidate.total_cost is not None for candidate in candidates)
    if has_cost and currency is None:
        raise BenchmarkError("currency is required when total_cost is provided")
    if has_cost and any(candidate.total_cost is None for candidate in candidates):
        raise BenchmarkError(
            "total_cost must be provided for every candidate or none",
            "INCOMPARABLE_COST",
        )
    if maximum_cost_per_success is not None:
        if currency is None or any(candidate.total_cost is None for candidate in candidates):
            raise BenchmarkError(
                "a cost gate requires currency and total_cost for every candidate",
                "INCOMPARABLE_COST",
            )

    return Benchmark(
        name=name,
        currency=currency,
        allow_partial=allow_partial,
        policy=policy,
        candidates=tuple(candidates),
    )


def run_benchmark(config: Benchmark) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    for candidate in config.candidates:
        try:
            report = _load_health_report(candidate.report)
            evaluated.append(_evaluate(candidate, report, config.policy))
        except BenchmarkError as exc:
            if not config.allow_partial:
                raise BenchmarkError(
                    f"candidate {candidate.name!r} cannot be evaluated",
                    exc.code,
                ) from exc
            unavailable.append({"name": candidate.name, "code": exc.code})
    if len(evaluated) < 2:
        raise BenchmarkError(
            "at least two valid candidates are required",
            "INSUFFICIENT_VALID_CANDIDATES",
        )

    eligible = [candidate for candidate in evaluated if candidate["eligible"]]
    ordered = sorted(
        eligible,
        key=lambda item: _rank_key(item, config.policy.rank_by),
    )
    ranks = {candidate["name"]: index for index, candidate in enumerate(ordered, 1)}
    for candidate in evaluated:
        candidate["rank"] = ranks.get(candidate["name"])
    evaluated.sort(
        key=lambda item: (
            item["rank"] is None,
            item["rank"] or 0,
            item["name"],
        )
    )
    return {
        "schema_version": "1.0",
        "benchmark": config.name,
        "status": "partial" if unavailable else "completed",
        "currency": config.currency,
        "recommended_candidate": ordered[0]["name"] if ordered else None,
        "policy": config.policy.to_dict(),
        "ranking_rule": [
            "all policy gates must pass",
            *[
                f"{metric} {'descending' if metric == 'success_rate' else 'ascending'}"
                for metric in config.policy.rank_by
            ],
        ],
        "candidates": evaluated,
        "unavailable": unavailable,
        "privacy": {
            "copies_observed_ips": False,
            "copies_individual_results": False,
            "copies_source_paths": False,
        },
    }


def _evaluate(
    candidate: Candidate,
    report: dict[str, Any],
    policy: Policy,
) -> dict[str, Any]:
    summary = report["summary"]
    requests = summary["requests"]
    successful = summary["successful"]
    success_rate = summary["success_rate"]
    p95 = summary["latency_ms"]["p95"]
    attempts = _attempts(report, requests)
    retry_amplification = round(attempts / requests, 4)
    cost_per_success = (
        round(candidate.total_cost / successful, 8)
        if candidate.total_cost is not None and successful
        else None
    )
    gates = [
        _gate(
            "healthcheck_status",
            report["status"],
            "==",
            "healthy",
            report["status"] == "healthy",
        ),
        _gate(
            "success_rate",
            success_rate,
            ">=",
            policy.minimum_success_rate,
            success_rate >= policy.minimum_success_rate,
        ),
        _gate(
            "p95_latency_ms",
            p95,
            "<=",
            policy.maximum_p95_ms,
            p95 is not None and p95 <= policy.maximum_p95_ms,
        ),
        _gate(
            "retry_amplification",
            retry_amplification,
            "<=",
            policy.maximum_retry_amplification,
            retry_amplification <= policy.maximum_retry_amplification,
        ),
    ]
    if policy.maximum_cost_per_success is not None:
        gates.append(
            _gate(
                "cost_per_success",
                cost_per_success,
                "<=",
                policy.maximum_cost_per_success,
                cost_per_success is not None
                and cost_per_success <= policy.maximum_cost_per_success,
            )
        )
    return {
        "name": candidate.name,
        "rank": None,
        "eligible": all(gate["passed"] for gate in gates),
        "failed_gates": [
            gate["metric"] for gate in gates if not gate["passed"]
        ],
        "gates": gates,
        "metrics": {
            "requests": requests,
            "successful": successful,
            "success_rate": success_rate,
            "p95_latency_ms": p95,
            "attempts": attempts,
            "retry_amplification": retry_amplification,
            "total_cost": candidate.total_cost,
            "cost_per_success": cost_per_success,
        },
    }


def _load_health_report(path: Path) -> dict[str, Any]:
    report = _load_json(path, MAX_REPORT_BYTES, "health report")
    if report.get("schema_version") not in {"1.0", "1.1"}:
        raise BenchmarkError(
            "unsupported health report schema",
            "UNSUPPORTED_REPORT_VERSION",
        )
    if report.get("status") not in {"healthy", "degraded", "failed"}:
        raise BenchmarkError("invalid health report status", "INVALID_REPORT")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise BenchmarkError("health report summary is missing", "INVALID_REPORT")
    latency = summary.get("latency_ms")
    if not isinstance(latency, dict):
        raise BenchmarkError("health report latency is missing", "INVALID_REPORT")
    requests = _integer(summary.get("requests"), "summary.requests", minimum=1)
    successful = _integer(
        summary.get("successful"),
        "summary.successful",
        minimum=0,
        maximum=requests,
    )
    success_rate = _number(
        summary.get("success_rate"),
        "summary.success_rate",
        minimum=0,
        maximum=1,
        code="INVALID_REPORT",
    )
    expected_rate = round(successful / requests, 4)
    if abs(success_rate - expected_rate) > 0.0001:
        raise BenchmarkError(
            "health report success_rate is inconsistent",
            "INCONSISTENT_REPORT",
        )
    p95 = latency.get("p95")
    if p95 is not None:
        _number(
            p95,
            "summary.latency_ms.p95",
            minimum=0,
            maximum=600_000,
            code="INVALID_REPORT",
        )
    elif successful:
        raise BenchmarkError(
            "successful health report requires p95 latency",
            "INCONSISTENT_REPORT",
        )
    return report


def _attempts(report: dict[str, Any], requests: int) -> int:
    summary_attempts = report["summary"].get("attempts")
    if summary_attempts is not None:
        summary_attempts = _integer(
            summary_attempts,
            "summary.attempts",
            minimum=requests,
            maximum=requests * 6,
        )
    results = report.get("results")
    if not isinstance(results, list) or len(results) != requests:
        if summary_attempts is not None and results is None:
            return summary_attempts
        raise BenchmarkError(
            "health report requires one result per request",
            "INCONSISTENT_REPORT",
        )
    attempts = 0
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise BenchmarkError("invalid legacy result", "INVALID_REPORT")
        attempts += _integer(
            result.get("attempts"),
            f"results[{index}].attempts",
            minimum=1,
            maximum=6,
        )
    if summary_attempts is not None and attempts != summary_attempts:
        raise BenchmarkError(
            "health report attempts are inconsistent",
            "INCONSISTENT_REPORT",
        )
    return attempts


def _rank_key(candidate: dict[str, Any], rank_by: tuple[str, ...]) -> tuple[Any, ...]:
    metrics = candidate["metrics"]
    values: list[Any] = []
    for metric in rank_by:
        value = metrics[metric]
        if metric == "success_rate":
            values.append(-value)
        else:
            values.append(float("inf") if value is None else value)
    values.append(candidate["name"])
    return tuple(values)


def _gate(
    metric: str,
    observed: Any,
    operator: str,
    threshold: Any,
    passed: bool,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "observed": observed,
        "operator": operator,
        "threshold": threshold,
        "passed": passed,
    }


def _load_json(path: Path, limit: int, label: str) -> dict[str, Any]:
    try:
        if path.stat().st_size > limit:
            raise BenchmarkError(f"{label} exceeds size limit", "INPUT_TOO_LARGE")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except BenchmarkError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read {label}", "UNREADABLE_INPUT") from exc
    if not isinstance(payload, dict):
        raise BenchmarkError(f"{label} root must be an object", "INVALID_REPORT")
    return payload


def _keys(
    payload: dict[str, Any],
    allowed: set[str],
    required: set[str],
    label: str,
) -> None:
    unknown = sorted(set(payload) - allowed)
    missing = sorted(required - set(payload))
    if unknown:
        raise BenchmarkError(f"{label} has unknown fields: {', '.join(unknown)}")
    if missing:
        raise BenchmarkError(f"{label} is missing fields: {', '.join(missing)}")


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",
        value,
    ):
        raise BenchmarkError(f"{label} must be a safe identifier")
    return value


def _integer(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BenchmarkError(f"{label} must be an integer", "INVALID_REPORT")
    if value < minimum or (maximum is not None and value > maximum):
        raise BenchmarkError(f"{label} is outside allowed range", "INVALID_REPORT")
    return value


def _number(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float,
    code: str = "INVALID_BENCHMARK",
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BenchmarkError(f"{label} must be numeric", code)
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise BenchmarkError(f"{label} is outside allowed range", code)
    return number
