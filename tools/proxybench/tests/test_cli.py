from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxybench.cli import main  # noqa: E402


def report(successful: int = 10) -> dict:
    return {
        "schema_version": "1.1",
        "status": "healthy",
        "summary": {
            "requests": 10,
            "successful": successful,
            "success_rate": successful / 10,
            "attempts": 10,
            "latency_ms": {"p95": 100},
        },
        "results": [{"attempts": 1} for _ in range(10)],
    }


def write_case(directory: Path) -> Path:
    (directory / "a.json").write_text(json.dumps(report()), encoding="utf-8")
    (directory / "b.json").write_text(json.dumps(report(9)), encoding="utf-8")
    payload = {
        "schema_version": "1.0",
        "name": "cli-test",
        "policy": {
            "minimum_success_rate": 0.8,
            "maximum_p95_ms": 1000,
            "maximum_retry_amplification": 2,
            "rank_by": [
                "success_rate",
                "cost_per_success",
                "p95_latency_ms",
                "retry_amplification",
            ],
        },
        "candidates": [
            {"name": "a", "report": "a.json"},
            {"name": "b", "report": "b.json"},
        ],
    }
    path = directory / "benchmark.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class CliTests(unittest.TestCase):
    def test_writes_private_atomic_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = write_case(directory)
            output = directory / "result.json"
            self.assertEqual(
                main(["--config", str(config), "--output", str(output)]),
                0,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["recommended_candidate"], "a")
            if os.name != "nt":
                self.assertEqual(
                    stat.S_IMODE(output.stat().st_mode),
                    0o600,
                )
            self.assertEqual(list(directory.glob(".result.json.*.tmp")), [])

    def test_errors_are_machine_readable_and_do_not_echo_input(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(
                ["--config", "/private/secret/customer-token.json"]
            )
        self.assertEqual(exit_code, 64)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "UNREADABLE_INPUT")
        self.assertNotIn("customer-token", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
