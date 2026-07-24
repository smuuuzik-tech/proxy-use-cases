from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from session_strategy import AnalysisError, analyze_records, load_jsonl  # noqa: E402


def observation(
    strategy: str,
    request_id: str,
    session_id: str,
    exit_ip: str,
    *,
    success: bool = True,
    status_code: int = 200,
    latency_ms: float = 100,
    cost_units: float = 1,
):
    return {
        "strategy": strategy,
        "request_id": request_id,
        "session_id": session_id,
        "exit_ip": exit_ip,
        "success": success,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "cost_units": cost_units,
    }


class AnalysisTests(unittest.TestCase):
    def test_compares_sticky_and_rotating(self) -> None:
        records = [
            observation("sticky", "s1", "cart", "192.0.2.1", latency_ms=100),
            observation("sticky", "s2", "cart", "192.0.2.1", latency_ms=200),
            observation(
                "sticky",
                "s3",
                "cart",
                "192.0.2.1",
                success=False,
                status_code=429,
                latency_ms=300,
            ),
            observation("rotating", "r1", "a", "198.51.100.1", latency_ms=80),
            observation("rotating", "r2", "b", "198.51.100.2", latency_ms=90),
            observation("rotating", "r3", "c", "198.51.100.3", latency_ms=100),
        ]
        report = analyze_records(records)

        sticky = report["strategies"]["sticky"]
        rotating = report["strategies"]["rotating"]
        self.assertEqual(sticky["session_ip_continuity"], 1.0)
        self.assertEqual(rotating["exit_ip_change_rate"], 1.0)
        self.assertEqual(sticky["success_rate"], 0.6667)
        self.assertEqual(rotating["success_rate"], 1.0)
        self.assertEqual(sticky["failed_request_classes"], {"rate_limited": 1})
        self.assertAlmostEqual(
            report["comparison"]["success_rate_delta_rotating_minus_sticky"],
            0.3333,
        )

    def test_nearest_rank_p95_uses_successful_requests(self) -> None:
        records = [
            observation(
                "sticky",
                f"r{index}",
                "session",
                "192.0.2.1",
                latency_ms=index * 10,
            )
            for index in range(1, 21)
        ]
        report = analyze_records(records)
        self.assertEqual(
            report["strategies"]["sticky"]["p95_latency_ms"],
            190.0,
        )

    def test_invalid_input_is_rejected(self) -> None:
        with self.assertRaises(AnalysisError):
            analyze_records(
                [observation("random", "1", "s", "192.0.2.1")]
            )
        with self.assertRaises(AnalysisError):
            analyze_records(
                [observation("sticky", "1", "s", "not-an-ip")]
            )
        invalid = observation("sticky", "1", "s", "192.0.2.1")
        invalid["success"] = "yes"
        with self.assertRaises(AnalysisError):
            analyze_records([invalid])

    def test_load_jsonl_reports_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text(
                json.dumps(observation("sticky", "1", "s", "192.0.2.1"))
                + "\n{broken\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(AnalysisError, "line 2"):
                load_jsonl(path)


if __name__ == "__main__":
    unittest.main()
