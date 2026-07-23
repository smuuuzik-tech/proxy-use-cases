from __future__ import annotations

import json
import sys
import threading
import unittest
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxy_healthcheck import (  # noqa: E402
    ConfigError,
    EndpointConfig,
    ExitCode,
    HealthStatus,
    HealthcheckConfig,
    TransportResponse,
    run_healthcheck,
)
from proxy_healthcheck.redaction import redact_text, redact_url  # noqa: E402


def response(ip: str, status: int = 200) -> TransportResponse:
    return TransportResponse(status, json.dumps({"ip": ip}).encode())


class ScriptedTransport:
    def __init__(self, scripts: dict[str, list[object]]) -> None:
        self._scripts = {key: deque(values) for key, values in scripts.items()}
        self._lock = threading.Lock()

    def request(self, url: str, proxy_url: str, timeout_seconds: float) -> TransportResponse:
        with self._lock:
            outcome = self._scripts[url].popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class StepClock:
    def __init__(self, step: float = 0.01) -> None:
        self._current = 0.0
        self._step = step
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            value = self._current
            self._current += self._step
            return value


def config(
    *,
    requests: int = 4,
    retry_budget: int = 0,
    minimum_success_rate: float = 0.75,
    fail_below_success_rate: float = 0.5,
    minimum_unique_ips: int = 1,
    retry_backoff_seconds: float = 0,
) -> HealthcheckConfig:
    return HealthcheckConfig(
        proxy_url="http://proxy.internal:8080",
        proxy_username="business-user",
        proxy_password="super-secret",
        endpoints=(EndpointConfig("primary", "https://allowed.example/ip"),),
        requests_per_endpoint=requests,
        concurrency=1,
        timeout_seconds=1,
        retry_budget=retry_budget,
        retry_backoff_seconds=retry_backoff_seconds,
        minimum_success_rate=minimum_success_rate,
        fail_below_success_rate=fail_below_success_rate,
        maximum_p95_ms=1000,
        minimum_unique_ips=minimum_unique_ips,
    )


class HealthcheckTests(unittest.TestCase):
    def test_healthy(self) -> None:
        transport = ScriptedTransport(
            {"https://allowed.example/ip": [response("192.0.2.1")] * 4}
        )
        report = run_healthcheck(config(), transport, clock=StepClock())
        self.assertEqual(report.status, HealthStatus.HEALTHY)
        self.assertEqual(report.exit_code, ExitCode.HEALTHY)
        self.assertEqual(report.summary["success_rate"], 1.0)

    def test_direct_library_config_cannot_bypass_validation(self) -> None:
        unsafe = HealthcheckConfig(
            proxy_url="http://proxy.internal:8080",
            endpoints=(
                EndpointConfig("metadata", "https://169.254.169.254/latest"),
            ),
            requests_per_endpoint=1_000_000_000,
        )
        with self.assertRaises(ConfigError):
            run_healthcheck(
                unsafe,
                ScriptedTransport({}),
                clock=StepClock(),
            )

    def test_degraded(self) -> None:
        transport = ScriptedTransport(
            {
                "https://allowed.example/ip": [
                    response("192.0.2.1"),
                    response("192.0.2.1"),
                    response("192.0.2.1"),
                    RuntimeError("temporary failure"),
                ]
            }
        )
        report = run_healthcheck(
            config(minimum_success_rate=1.0, fail_below_success_rate=0.5),
            transport,
            clock=StepClock(),
        )
        self.assertEqual(report.status, HealthStatus.DEGRADED)
        self.assertEqual(report.exit_code, ExitCode.DEGRADED)
        self.assertEqual(report.summary["success_rate"], 0.75)

    def test_failed(self) -> None:
        transport = ScriptedTransport(
            {"https://allowed.example/ip": [TimeoutError("timed out")] * 4}
        )
        report = run_healthcheck(config(), transport, clock=StepClock())
        self.assertEqual(report.status, HealthStatus.FAILED)
        self.assertEqual(report.exit_code, ExitCode.FAILED)
        self.assertEqual(report.summary["successful"], 0)

    def test_rotation_summary_is_request_ordered(self) -> None:
        transport = ScriptedTransport(
            {
                "https://allowed.example/ip": [
                    response("192.0.2.1"),
                    response("192.0.2.2"),
                    response("192.0.2.2"),
                    response("192.0.2.3"),
                ]
            }
        )
        report = run_healthcheck(
            config(minimum_unique_ips=3),
            transport,
            clock=StepClock(),
        )
        summary = report.rotation["by_endpoint"][0]
        self.assertEqual(summary["unique_ips"], 3)
        self.assertEqual(summary["sequence_changes"], 2)
        self.assertEqual(summary["change_rate"], 0.6667)
        self.assertEqual(
            summary["ip_frequencies"],
            {"192.0.2.1": 1, "192.0.2.2": 2, "192.0.2.3": 1},
        )

    def test_multiple_endpoints_and_required_endpoint_failure(self) -> None:
        multi_config = HealthcheckConfig(
            proxy_url="http://proxy.internal:8080",
            proxy_username="user",
            proxy_password="secret",
            endpoints=(
                EndpointConfig("primary", "https://allowed.example/ip"),
                EndpointConfig("backup", "https://backup.example/ip"),
            ),
            requests_per_endpoint=2,
            concurrency=2,
            timeout_seconds=1,
            retry_budget=0,
            retry_backoff_seconds=0,
            minimum_success_rate=0.75,
            fail_below_success_rate=0.5,
            maximum_p95_ms=1000,
            minimum_unique_ips=1,
        )
        transport = ScriptedTransport(
            {
                "https://allowed.example/ip": [response("192.0.2.1")] * 2,
                "https://backup.example/ip": [TimeoutError("down")] * 2,
            }
        )
        report = run_healthcheck(multi_config, transport, clock=StepClock())
        self.assertEqual(report.status, HealthStatus.FAILED)
        self.assertEqual(
            {endpoint["name"]: endpoint["status"] for endpoint in report.endpoints},
            {"primary": "healthy", "backup": "failed"},
        )

    def test_retry_budget_allows_recovery(self) -> None:
        transport = ScriptedTransport(
            {
                "https://allowed.example/ip": [
                    TimeoutError("first attempt"),
                    response("192.0.2.1"),
                ]
            }
        )
        report = run_healthcheck(
            config(requests=1, retry_budget=1),
            transport,
            clock=StepClock(),
        )
        self.assertEqual(report.status, HealthStatus.HEALTHY)
        self.assertEqual(report.results[0].attempts, 2)

    def test_secret_redaction_in_report_and_errors(self) -> None:
        secret_url = "http://business-user:super-secret@proxy.internal:8080"
        transport = ScriptedTransport(
            {
                "https://allowed.example/ip": [
                    RuntimeError(f"cannot connect via {secret_url}; password=super-secret")
                ]
            }
        )
        report = run_healthcheck(
            config(requests=1),
            transport,
            clock=StepClock(),
        )
        serialized = json.dumps(report.to_dict())
        self.assertNotIn("business-user", serialized)
        self.assertNotIn("super-secret", serialized)
        self.assertNotIn("proxy.internal", serialized)
        self.assertIn("***", serialized)
        self.assertEqual(
            redact_url(secret_url),
            "http://***:***@proxy.internal:8080/",
        )
        self.assertEqual(
            redact_url("https://allowed.example/ip?token=secret&format=json"),
            "https://allowed.example/<redacted-path>?<redacted-query>",
        )
        self.assertNotIn(
            "super-secret",
            redact_text("authorization=super-secret"),
        )

    def test_unique_ip_threshold_is_never_silently_skipped(self) -> None:
        transport = ScriptedTransport(
            {"https://allowed.example/ip": [response("192.0.2.1")] * 2}
        )
        report = run_healthcheck(
            config(requests=2, minimum_unique_ips=2),
            transport,
            clock=StepClock(),
        )
        self.assertEqual(report.status, HealthStatus.DEGRADED)
        self.assertIn("unique_ip_count_below_threshold", report.endpoints[0]["issues"])

    def test_non_retryable_proxy_auth_failure_is_not_retried(self) -> None:
        transport = ScriptedTransport(
            {"https://allowed.example/ip": [response("192.0.2.1", status=407)]}
        )
        report = run_healthcheck(
            config(requests=1, retry_budget=2),
            transport,
            clock=StepClock(),
        )
        self.assertEqual(report.results[0].attempts, 1)
        self.assertEqual(report.results[0].error_category, "proxy_auth")

    def test_exponential_backoff_is_capped(self) -> None:
        sleeps = []
        transport = ScriptedTransport(
            {"https://allowed.example/ip": [TimeoutError("down")] * 6}
        )
        report = run_healthcheck(
            config(
                requests=1,
                retry_budget=5,
                retry_backoff_seconds=30,
            ),
            transport,
            clock=StepClock(),
            sleeper=sleeps.append,
            jitter=lambda _low, high: high,
        )
        self.assertEqual(report.results[0].attempts, 6)
        self.assertEqual(sleeps, [30, 30, 30, 30, 30])

    def test_bearer_and_query_secrets_are_redacted(self) -> None:
        self.assertNotIn(
            "TOPSECRET",
            redact_text("Authorization: Bearer TOPSECRET"),
        )
        safe_url = redact_url(
            "https://allowed.example/ip?access_token=TOPSECRET&client_secret=SECOND"
        )
        self.assertNotIn("TOPSECRET", safe_url)
        self.assertNotIn("SECOND", safe_url)

    def test_endpoint_path_and_query_are_redacted_from_transport_errors(self) -> None:
        transport = ScriptedTransport(
            {
                "https://allowed.example/ip": [
                    RuntimeError(
                        "failed at https://allowed.example/customer/42?customer_id=ABC"
                    )
                ]
            }
        )
        report = run_healthcheck(
            config(requests=1),
            transport,
            clock=StepClock(),
        )
        serialized = json.dumps(report.to_dict())
        self.assertNotIn("customer/42", serialized)
        self.assertNotIn("customer_id", serialized)
        self.assertNotIn("ABC", serialized)


if __name__ == "__main__":
    unittest.main()
