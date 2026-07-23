from __future__ import annotations

import ipaddress
import json
import math
import random
import socket
import ssl
import time
import urllib.error
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from .config import (
    MAX_RETRY_BACKOFF_SECONDS,
    EndpointConfig,
    HealthcheckConfig,
    _validate,
)
from .models import CheckResult, ErrorCategory, ExitCode, HealthStatus, Report
from .redaction import proxy_secrets, redact_text
from .transport import Transport, UrllibTransport


Clock = Callable[[], float]
Sleeper = Callable[[float], None]
Jitter = Callable[[float, float], float]


def run_healthcheck(
    config: HealthcheckConfig,
    transport: Transport | None = None,
    *,
    clock: Clock = time.perf_counter,
    sleeper: Sleeper = time.sleep,
    jitter: Jitter = random.uniform,
) -> Report:
    """Run all configured checks and return a serializable, credential-safe report."""
    _validate(config)
    active_transport = transport or UrllibTransport()
    futures = {}
    results: list[CheckResult] = []
    with ThreadPoolExecutor(max_workers=config.concurrency, thread_name_prefix="proxy-check") as pool:
        for endpoint in config.endpoints:
            for request_index in range(config.requests_per_endpoint):
                future = pool.submit(
                    _run_one,
                    endpoint,
                    request_index,
                    config,
                    active_transport,
                    clock,
                    sleeper,
                    jitter,
                )
                futures[future] = (endpoint.name, request_index)
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda result: (result.endpoint, result.request_index))
    return _build_report(config, results)


def _run_one(
    endpoint: EndpointConfig,
    request_index: int,
    config: HealthcheckConfig,
    transport: Transport,
    clock: Clock,
    sleeper: Sleeper,
    jitter: Jitter,
) -> CheckResult:
    started = clock()
    attempts = 0
    last_status: int | None = None
    last_error: str | None = None
    last_error_category: ErrorCategory | None = None
    observed_ip: str | None = None
    runtime_proxy_url = config.authenticated_proxy_url
    secrets = proxy_secrets(runtime_proxy_url)

    for attempt in range(config.retry_budget + 1):
        attempts = attempt + 1
        last_status = None
        try:
            response = transport.request(
                endpoint.url,
                runtime_proxy_url,
                config.timeout_seconds,
            )
            last_status = response.status_code
            if response.status_code not in endpoint.expected_status:
                last_error = f"unexpected HTTP status {response.status_code}"
                last_error_category = _http_error_category(response.status_code)
            else:
                observed_ip = _extract_ip(response.body, endpoint.ip_json_path)
                if observed_ip is not None:
                    return CheckResult(
                        endpoint=endpoint.name,
                        request_index=request_index,
                        success=True,
                        status_code=last_status,
                        latency_ms=round((clock() - started) * 1000, 3),
                        attempts=attempts,
                        observed_ip=observed_ip,
                        error_category=None,
                        error=None,
                    )
                last_error = f"valid IP not found at JSON path {endpoint.ip_json_path!r}"
                last_error_category = ErrorCategory.APPLICATION_RESPONSE
        except Exception as exc:  # transport implementations have provider-specific errors
            last_error = redact_text(exc, secrets)
            last_error_category = _exception_category(exc)
        if attempt < config.retry_budget and _is_retryable(last_status, last_error_category):
            if config.retry_backoff_seconds:
                maximum_delay = min(
                    MAX_RETRY_BACKOFF_SECONDS,
                    config.retry_backoff_seconds * (2**attempt),
                )
                sleeper(jitter(0, maximum_delay))
            continue
        break

    return CheckResult(
        endpoint=endpoint.name,
        request_index=request_index,
        success=False,
        status_code=last_status,
        latency_ms=round((clock() - started) * 1000, 3),
        attempts=attempts,
        observed_ip=None,
        error_category=(last_error_category or ErrorCategory.TRANSPORT).value,
        error=redact_text(last_error or "unknown transport error", secrets),
    )


def _http_error_category(status_code: int) -> ErrorCategory:
    if status_code == 407:
        return ErrorCategory.PROXY_AUTH
    if status_code in {401, 403}:
        return ErrorCategory.TARGET_AUTH
    if 300 <= status_code < 400:
        return ErrorCategory.POLICY_REDIRECT
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if status_code in {408, 504}:
        return ErrorCategory.TIMEOUT
    return ErrorCategory.TARGET_HTTP


def _exception_category(exc: Exception) -> ErrorCategory:
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return ErrorCategory.TIMEOUT
    if isinstance(reason, ssl.SSLError):
        return ErrorCategory.TLS
    if isinstance(reason, socket.gaierror):
        return ErrorCategory.DNS
    if isinstance(reason, (ConnectionError, ConnectionRefusedError)):
        return ErrorCategory.CONNECT
    return ErrorCategory.TRANSPORT


def _is_retryable(status_code: int | None, category: ErrorCategory | None) -> bool:
    if status_code is not None:
        return status_code in {408, 425, 429} or 500 <= status_code <= 599
    return category in {
        ErrorCategory.DNS,
        ErrorCategory.CONNECT,
        ErrorCategory.TLS,
        ErrorCategory.TIMEOUT,
        ErrorCategory.TRANSPORT,
    }


def _extract_ip(body: bytes, path: str) -> str | None:
    try:
        payload: Any = json.loads(body.decode("utf-8"))
        for component in path.split("."):
            if not isinstance(payload, dict):
                return None
            payload = payload[component]
        value = str(payload).strip()
        return str(ipaddress.ip_address(value))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _endpoint_metrics(
    endpoint: EndpointConfig,
    checks: list[CheckResult],
    config: HealthcheckConfig,
) -> tuple[dict[str, Any], list[str]]:
    successful = [check for check in checks if check.success]
    latencies = [check.latency_ms for check in successful]
    ips = [check.observed_ip for check in successful if check.observed_ip]
    counts = Counter(ips)
    success_rate = len(successful) / len(checks) if checks else 0.0
    minimum_unique = (
        endpoint.minimum_unique_ips
        if endpoint.minimum_unique_ips is not None
        else config.minimum_unique_ips
    )
    reasons: list[str] = []
    if success_rate < config.minimum_success_rate:
        reasons.append("success_rate_below_healthy_threshold")
    p95 = _percentile(latencies, 0.95)
    if p95 is not None and p95 > config.maximum_p95_ms:
        reasons.append("p95_latency_above_threshold")
    if len(counts) < minimum_unique:
        reasons.append("unique_ip_count_below_threshold")
    if not successful or success_rate < config.fail_below_success_rate:
        endpoint_status = HealthStatus.FAILED
    elif reasons:
        endpoint_status = HealthStatus.DEGRADED
    else:
        endpoint_status = HealthStatus.HEALTHY
    metrics = {
        "name": endpoint.name,
        "status": endpoint_status.value,
        "requests": len(checks),
        "successful": len(successful),
        "failed": len(checks) - len(successful),
        "success_rate": round(success_rate, 4),
        "latency_ms": {
            "min": round(min(latencies), 3) if latencies else None,
            "average": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "p95": p95,
            "max": round(max(latencies), 3) if latencies else None,
        },
        "observed_ip_count": len(ips),
        "unique_ip_count": len(counts),
        "minimum_unique_ips": minimum_unique,
        "issues": reasons,
    }
    return metrics, reasons


def _rotation_metrics(checks: list[CheckResult]) -> dict[str, Any]:
    by_endpoint: dict[str, list[CheckResult]] = {}
    for check in checks:
        by_endpoint.setdefault(check.endpoint, []).append(check)
    endpoint_summaries: list[dict[str, Any]] = []
    all_ips: list[str] = []
    for endpoint_name, endpoint_checks in sorted(by_endpoint.items()):
        sequence = [
            check.observed_ip
            for check in sorted(endpoint_checks, key=lambda item: item.request_index)
            if check.success and check.observed_ip
        ]
        all_ips.extend(sequence)
        counts = Counter(sequence)
        transitions = sum(
            1 for previous, current in zip(sequence, sequence[1:]) if previous != current
        )
        endpoint_summaries.append(
            {
                "name": endpoint_name,
                "observed": len(sequence),
                "unique_ips": len(counts),
                "ip_frequencies": dict(sorted(counts.items())),
                "sequence_changes": transitions,
                "change_rate": round(transitions / (len(sequence) - 1), 4)
                if len(sequence) > 1
                else 0.0,
            }
        )
    all_counts = Counter(all_ips)
    return {
        "observed": len(all_ips),
        "unique_ips": len(all_counts),
        "reuse_rate": round(1 - (len(all_counts) / len(all_ips)), 4) if all_ips else None,
        "ip_frequencies": dict(sorted(all_counts.items())),
        "by_endpoint": endpoint_summaries,
    }


def _build_report(config: HealthcheckConfig, results: list[CheckResult]) -> Report:
    endpoint_reports: list[dict[str, Any]] = []
    issue_count = 0
    failed_endpoints = 0
    for endpoint in config.endpoints:
        endpoint_results = [result for result in results if result.endpoint == endpoint.name]
        metrics, issues = _endpoint_metrics(endpoint, endpoint_results, config)
        issue_count += len(issues)
        if metrics["status"] == HealthStatus.FAILED.value:
            failed_endpoints += 1
        endpoint_reports.append(metrics)

    successful = [result for result in results if result.success]
    total = len(results)
    success_rate = len(successful) / total if total else 0.0
    all_latencies = [result.latency_ms for result in successful]
    if failed_endpoints or success_rate < config.fail_below_success_rate or not successful:
        status = HealthStatus.FAILED
        exit_code = ExitCode.FAILED
    elif issue_count:
        status = HealthStatus.DEGRADED
        exit_code = ExitCode.DEGRADED
    else:
        status = HealthStatus.HEALTHY
        exit_code = ExitCode.HEALTHY

    return Report(
        schema_version="1.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        status=status,
        exit_code=int(exit_code),
        summary={
            "requests": total,
            "successful": len(successful),
            "failed": total - len(successful),
            "success_rate": round(success_rate, 4),
            "latency_ms": {
                "average": round(sum(all_latencies) / len(all_latencies), 3)
                if all_latencies
                else None,
                "p95": _percentile(all_latencies, 0.95),
            },
            "endpoints": len(config.endpoints),
        },
        endpoints=endpoint_reports,
        rotation=_rotation_metrics(results),
        config=config.safe_dict(),
        results=results,
    )
