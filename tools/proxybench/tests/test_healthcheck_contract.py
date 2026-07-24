from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(
    0,
    str(REPOSITORY / "tools" / "proxy-healthcheck" / "src"),
)

from proxy_healthcheck import (  # noqa: E402
    EndpointConfig,
    HealthcheckConfig,
    TransportResponse,
    run_healthcheck,
)
from proxybench import load_benchmark, run_benchmark  # noqa: E402


class FixedTransport:
    def request(
        self,
        url: str,
        proxy_url: str,
        timeout_seconds: float,
    ) -> TransportResponse:
        return TransportResponse(200, b'{"ip":"192.0.2.1"}')


class StepClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        current = self.value
        self.value += 0.01
        return current


class HealthcheckContractTests(unittest.TestCase):
    def test_proxybench_consumes_current_healthcheck_report(self) -> None:
        health_config = HealthcheckConfig(
            proxy_url="http://proxy.example:8080",
            endpoints=(
                EndpointConfig("ip", "https://allowed.example/ip"),
            ),
            requests_per_endpoint=2,
            concurrency=1,
            retry_budget=0,
            retry_backoff_seconds=0,
            minimum_success_rate=0.95,
            fail_below_success_rate=0.5,
            maximum_p95_ms=2_000,
            minimum_unique_ips=1,
        )
        report = run_healthcheck(
            health_config,
            FixedTransport(),
            clock=StepClock(),
        ).to_dict()
        self.assertEqual(report["schema_version"], "1.1")

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("pool-a", "pool-b"):
                (directory / f"{name}.json").write_text(
                    json.dumps(report),
                    encoding="utf-8",
                )
            manifest = {
                "schema_version": "1.0",
                "name": "contract-test",
                "policy": {
                    "minimum_success_rate": 0.95,
                    "maximum_p95_ms": 2_000,
                    "maximum_retry_amplification": 1.5,
                    "rank_by": [
                        "success_rate",
                        "cost_per_success",
                        "p95_latency_ms",
                        "retry_amplification",
                    ],
                },
                "candidates": [
                    {"name": "pool-a", "report": "pool-a.json"},
                    {"name": "pool-b", "report": "pool-b.json"},
                ],
            }
            manifest_path = directory / "benchmark.json"
            manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            result = run_benchmark(load_benchmark(manifest_path))

        self.assertEqual(result["recommended_candidate"], "pool-a")
        self.assertEqual(
            [candidate["rank"] for candidate in result["candidates"]],
            [1, 2],
        )


if __name__ == "__main__":
    unittest.main()
