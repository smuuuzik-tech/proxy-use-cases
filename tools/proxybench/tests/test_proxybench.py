from __future__ import annotations

import json
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxybench import BenchmarkError, load_benchmark, run_benchmark  # noqa: E402


def health_report(
    *,
    status: str = "healthy",
    requests: int = 100,
    successful: int = 99,
    p95: float | None = 500,
    attempts: int | None = 105,
    schema_version: str = "1.1",
) -> dict:
    summary = {
        "requests": requests,
        "successful": successful,
        "failed": requests - successful,
        "success_rate": round(successful / requests, 4),
        "latency_ms": {"p95": p95},
    }
    if attempts is not None:
        summary["attempts"] = attempts
    result_attempts = [1] * requests
    if attempts is not None:
        remaining = attempts - requests
        index = 0
        while remaining:
            increment = min(5, remaining)
            result_attempts[index] += increment
            remaining -= increment
            index += 1
    return {
        "schema_version": schema_version,
        "generated_at": "2026-07-24T00:00:00+00:00",
        "status": status,
        "exit_code": 0 if status == "healthy" else 1,
        "summary": summary,
        "endpoints": [],
        "rotation": {"ip_frequencies": {"192.0.2.1": 100}},
        "decision": {"reasons": []},
        "config": {},
        "results": [
            {
                "attempts": result_attempts[index],
                "observed_ip": "192.0.2.1",
                "error": "token=TOPSECRET",
            }
            for index in range(requests)
        ],
    }


def manifest(candidates: list[dict], **overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "name": "pool-comparison",
        "currency": "USD",
        "allow_partial": False,
        "policy": {
            "minimum_success_rate": 0.95,
            "maximum_p95_ms": 2_000,
            "maximum_retry_amplification": 1.5,
            "maximum_cost_per_success": 0.02,
            "rank_by": [
                "success_rate",
                "cost_per_success",
                "p95_latency_ms",
                "retry_amplification",
            ],
        },
        "candidates": candidates,
    }
    value.update(overrides)
    return value


class BenchmarkTests(unittest.TestCase):
    def test_example_manifest_uses_supported_schema(self) -> None:
        loaded = load_benchmark(ROOT / "benchmark.example.json")
        self.assertEqual(loaded.name, "approved-pool-comparison")
        self.assertEqual(len(loaded.candidates), 2)

    def test_json_schemas_are_packaged(self) -> None:
        package = files("proxybench")
        manifest_schema = json.loads(
            package.joinpath("benchmark.schema.json").read_text(encoding="utf-8")
        )
        result_schema = json.loads(
            package.joinpath("result.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest_schema["properties"]["schema_version"]["const"],
            "1.0",
        )
        self.assertEqual(
            result_schema["properties"]["schema_version"]["const"],
            "1.0",
        )

    def write_case(
        self,
        directory: Path,
        candidates: list[tuple[str, dict, float]],
        **manifest_overrides,
    ) -> Path:
        reports = directory / "reports"
        reports.mkdir()
        entries = []
        for name, report, cost in candidates:
            report_path = reports / f"{name}.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            entries.append(
                {
                    "name": name,
                    "report": f"reports/{name}.json",
                    "total_cost": cost,
                }
            )
        manifest_path = directory / "benchmark.json"
        manifest_path.write_text(
            json.dumps(manifest(entries, **manifest_overrides)),
            encoding="utf-8",
        )
        return manifest_path

    def test_recommends_eligible_candidate_with_explicit_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("pool-a", health_report(successful=99, p95=500), 0.50),
                    ("pool-b", health_report(successful=98, p95=300), 0.20),
                ],
            )
            result = run_benchmark(load_benchmark(path))
        self.assertEqual(result["recommended_candidate"], "pool-a")
        self.assertEqual(result["candidates"][0]["rank"], 1)
        self.assertTrue(result["candidates"][0]["eligible"])

    def test_rank_policy_can_make_cost_the_first_preference(self) -> None:
        policy = manifest([])["policy"]
        policy["rank_by"] = [
            "cost_per_success",
            "success_rate",
            "p95_latency_ms",
            "retry_amplification",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("pool-a", health_report(successful=99), 0.50),
                    ("pool-b", health_report(successful=98), 0.20),
                ],
                policy=policy,
            )
            result = run_benchmark(load_benchmark(path))
        self.assertEqual(result["recommended_candidate"], "pool-b")

    def test_degraded_healthcheck_is_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("degraded", health_report(status="degraded"), 0.20),
                    ("healthy", health_report(successful=98), 0.30),
                ],
            )
            result = run_benchmark(load_benchmark(path))
        evaluated = {item["name"]: item for item in result["candidates"]}
        self.assertFalse(evaluated["degraded"]["eligible"])
        self.assertIn("healthcheck_status", evaluated["degraded"]["failed_gates"])
        self.assertEqual(result["recommended_candidate"], "healthy")

    def test_no_recommendation_when_every_candidate_misses_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("pool-a", health_report(successful=80), 0.20),
                    ("pool-b", health_report(successful=70), 0.20),
                ],
            )
            result = run_benchmark(load_benchmark(path))
        self.assertIsNone(result["recommended_candidate"])
        self.assertTrue(all(item["rank"] is None for item in result["candidates"]))

    def test_legacy_report_attempts_are_supported(self) -> None:
        first = health_report(
            requests=2,
            successful=2,
            attempts=None,
            schema_version="1.0",
        )
        first["results"] = [{"attempts": 1}, {"attempts": 2}]
        second = health_report(
            requests=2,
            successful=2,
            attempts=None,
            schema_version="1.0",
        )
        second["results"] = [{"attempts": 1}, {"attempts": 1}]
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [("pool-a", first, 0.01), ("pool-b", second, 0.01)],
            )
            result = run_benchmark(load_benchmark(path))
        metrics = {item["name"]: item["metrics"] for item in result["candidates"]}
        self.assertEqual(metrics["pool-a"]["retry_amplification"], 1.5)
        self.assertEqual(metrics["pool-b"]["retry_amplification"], 1.0)

    def test_partial_mode_uses_two_valid_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = self.write_case(
                directory,
                [
                    ("pool-a", health_report(), 0.20),
                    ("pool-b", health_report(successful=98), 0.20),
                    ("broken", health_report(), 0.20),
                ],
                allow_partial=True,
            )
            (directory / "reports" / "broken.json").write_text(
                "not-json",
                encoding="utf-8",
            )
            result = run_benchmark(load_benchmark(path))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(
            result["unavailable"],
            [{"name": "broken", "code": "UNREADABLE_INPUT"}],
        )

    def test_output_does_not_copy_sensitive_report_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("pool-a", health_report(), 0.20),
                    ("pool-b", health_report(successful=98), 0.20),
                ],
            )
            serialized = json.dumps(run_benchmark(load_benchmark(path)))
        self.assertNotIn("192.0.2.1", serialized)
        self.assertNotIn("TOPSECRET", serialized)
        self.assertNotIn("reports/", serialized)
        self.assertEqual(
            json.loads(serialized)["privacy"],
            {
                "copies_observed_ips": False,
                "copies_individual_results": False,
                "copies_source_paths": False,
            },
        )

    def test_rejects_inconsistent_report(self) -> None:
        inconsistent = health_report()
        inconsistent["summary"]["success_rate"] = 0.1
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("pool-a", inconsistent, 0.20),
                    ("pool-b", health_report(), 0.20),
                ],
            )
            with self.assertRaisesRegex(BenchmarkError, "cannot be evaluated"):
                run_benchmark(load_benchmark(path))

    def test_rejects_inconsistent_attempt_count(self) -> None:
        inconsistent = health_report()
        inconsistent["summary"]["attempts"] += 1
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_case(
                Path(temporary),
                [
                    ("pool-a", inconsistent, 0.20),
                    ("pool-b", health_report(), 0.20),
                ],
            )
            with self.assertRaisesRegex(BenchmarkError, "cannot be evaluated"):
                run_benchmark(load_benchmark(path))

    def test_rejects_report_path_traversal(self) -> None:
        payload = manifest(
            [
                {"name": "a", "report": "../secret.json", "total_cost": 1},
                {"name": "b", "report": "b.json", "total_cost": 1},
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benchmark.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkError, "manifest directory"):
                load_benchmark(path)

    def test_rejects_report_symlink_outside_manifest_directory(self) -> None:
        payload = manifest(
            [
                {"name": "a", "report": "reports/a.json", "total_cost": 1},
                {"name": "b", "report": "b.json", "total_cost": 1},
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "case"
            directory.mkdir()
            reports = directory / "reports"
            reports.mkdir()
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            (reports / "a.json").symlink_to(outside)
            path = directory / "benchmark.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkError, "outside"):
                load_benchmark(path)

    def test_cost_gate_requires_comparable_costs(self) -> None:
        payload = manifest(
            [
                {"name": "a", "report": "a.json", "total_cost": 1},
                {"name": "b", "report": "b.json"},
            ]
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benchmark.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkError, "every candidate"):
                load_benchmark(path)

    def test_currency_must_use_canonical_uppercase_form(self) -> None:
        payload = manifest(
            [
                {"name": "a", "report": "a.json", "total_cost": 1},
                {"name": "b", "report": "b.json", "total_cost": 1},
            ],
            currency="usd",
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benchmark.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(BenchmarkError, "three-letter"):
                load_benchmark(path)


if __name__ == "__main__":
    unittest.main()
