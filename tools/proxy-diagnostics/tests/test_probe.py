from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxy_diagnostics import (  # noqa: E402
    DiagnosticCode,
    ExitCode,
    ProbeConfig,
    run_probe,
)
from proxy_diagnostics.probe import ConfigError, classify_failure, render_report  # noqa: E402


def runner_for(
    return_code: int,
    http_code: int,
    *,
    stderr: str = "",
):
    def runner(command, **kwargs):
        assert command == ["curl", "--config", "-"]
        assert kwargs["input"]
        return subprocess.CompletedProcess(
            command,
            return_code,
            (
                "\n__PROXY_DIAGNOSTICS__"
                f"{http_code}|203.0.113.20|0.002|0.010|0.030|0.050|0.060"
            ),
            stderr,
        )

    return runner


class ProbeTests(unittest.TestCase):
    def config(self, **overrides) -> ProbeConfig:
        values = {
            "proxy_url": "http://client:secret@proxy.example:8000",
            "target_url": "https://allowed.example/catalog?q=private",
            "proxy_username": None,
            "proxy_password": None,
        }
        values.update(overrides)
        return ProbeConfig(**values)

    def test_success_report_is_bounded_and_redacted(self) -> None:
        report = run_probe(self.config(), runner=runner_for(0, 200))
        rendered = render_report(report)

        self.assertTrue(report.ok)
        self.assertEqual(report.diagnostic, DiagnosticCode.OK)
        self.assertEqual(report.exit_code, ExitCode.OK)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("catalog", rendered)
        self.assertNotIn("q=private", rendered)
        self.assertEqual(report.target_origin, "https://allowed.example/")

    def test_proxy_authentication_is_distinct(self) -> None:
        report = run_probe(
            self.config(),
            runner=runner_for(
                0,
                407,
                stderr="proxy http://client:secret@proxy.example:8000 rejected password=secret",
            ),
        )
        rendered = render_report(report)

        self.assertEqual(report.diagnostic, DiagnosticCode.PROXY_AUTHENTICATION)
        self.assertEqual(report.exit_code, ExitCode.PROXY_AUTHENTICATION)
        self.assertNotIn("client:secret", rendered)
        self.assertNotIn("password=secret", rendered)

    def test_failure_classes(self) -> None:
        cases = [
            (5, 0, DiagnosticCode.DNS, ExitCode.DNS),
            (28, 0, DiagnosticCode.TIMEOUT, ExitCode.TIMEOUT),
            (60, 0, DiagnosticCode.TLS, ExitCode.TLS),
            (7, 0, DiagnosticCode.CONNECT, ExitCode.CONNECT),
            (0, 429, DiagnosticCode.RATE_LIMITED, ExitCode.UPSTREAM),
            (0, 403, DiagnosticCode.ACCESS_DENIED, ExitCode.UPSTREAM),
            (56, 0, DiagnosticCode.UPSTREAM, ExitCode.UPSTREAM),
        ]
        for curl_code, http_code, diagnostic, exit_code in cases:
            with self.subTest(curl_code=curl_code, http_code=http_code):
                report = run_probe(
                    self.config(),
                    runner=runner_for(curl_code, http_code),
                )
                self.assertEqual(report.diagnostic, diagnostic)
                self.assertEqual(report.exit_code, exit_code)

    def test_credentials_are_passed_via_stdin_not_process_arguments(self) -> None:
        captured = {}

        def capture(command, **kwargs):
            captured["command"] = command
            captured["input"] = kwargs["input"]
            return runner_for(0, 200)(command, **kwargs)

        run_probe(self.config(), runner=capture)
        self.assertEqual(captured["command"], ["curl", "--config", "-"])
        self.assertIn('proxy-user = "client:secret"', captured["input"])
        self.assertNotIn("secret", " ".join(captured["command"]))

    def test_private_target_and_unsafe_scheme_are_blocked(self) -> None:
        with self.assertRaises(ConfigError):
            run_probe(
                self.config(target_url="http://allowed.example/"),
                runner=runner_for(0, 200),
            )
        with self.assertRaises(ConfigError):
            run_probe(
                self.config(target_url="https://169.254.169.254/latest/meta-data"),
                runner=runner_for(0, 200),
            )

    def test_classifier_handles_unknown_failure(self) -> None:
        diagnostic, exit_code, *_ = classify_failure(2, 0)
        self.assertEqual(diagnostic, DiagnosticCode.UNKNOWN)
        self.assertEqual(exit_code, ExitCode.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
