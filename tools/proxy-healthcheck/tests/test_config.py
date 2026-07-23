from __future__ import annotations

import json
import io
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxy_healthcheck import ConfigError, load_config  # noqa: E402
from proxy_healthcheck.cli import main  # noqa: E402
from proxy_healthcheck.models import ExitCode  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_file_and_environment_overrides(self) -> None:
        payload = {
            "proxy_url": "http://proxy.example:8080",
            "endpoints": [{"name": "ip", "url": "https://allowed.example/ip"}],
            "requests_per_endpoint": 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = load_config(
                path,
                environ={
                    "PHC_REQUESTS_PER_ENDPOINT": "7",
                    "PHC_TIMEOUT_SECONDS": "3.5",
                },
            )
        self.assertEqual(loaded.requests_per_endpoint, 7)
        self.assertEqual(loaded.timeout_seconds, 3.5)

    def test_rejects_non_https_endpoint(self) -> None:
        environment = {
            "PHC_PROXY_URL": "http://proxy.example:8080",
            "PHC_ENDPOINTS": '[{"name":"unsafe","url":"http://example.com/ip"}]',
        }
        with self.assertRaisesRegex(ConfigError, "must use HTTPS"):
            load_config(environ=environment)

    def test_cli_config_error_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{}", encoding="utf-8")
            self.assertEqual(main(["--config", str(path)]), ExitCode.CONFIG_ERROR)

    def test_cli_argument_error_uses_config_exit_code(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = main(["--unknown"])
        self.assertEqual(exit_code, ExitCode.CONFIG_ERROR)
        self.assertIn("configuration error", stderr.getvalue())

    def test_rejects_unbounded_and_non_finite_values(self) -> None:
        base = {
            "PHC_PROXY_URL": "http://proxy.example:8080",
            "PHC_ENDPOINTS": '[{"name":"ip","url":"https://example.com/ip"}]',
        }
        for name, value in (
            ("PHC_REQUESTS_PER_ENDPOINT", "1000000000"),
            ("PHC_CONCURRENCY", "1000000"),
            ("PHC_RETRY_BUDGET", "1000000"),
            ("PHC_TIMEOUT_SECONDS", str(math.inf)),
            ("PHC_MAXIMUM_P95_MS", str(math.nan)),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ConfigError):
                    load_config(environ={**base, name: value})

    def test_unique_ip_threshold_cannot_exceed_request_count(self) -> None:
        environment = {
            "PHC_PROXY_URL": "http://proxy.example:8080",
            "PHC_REQUESTS_PER_ENDPOINT": "2",
            "PHC_MINIMUM_UNIQUE_IPS": "3",
            "PHC_ENDPOINTS": '[{"name":"ip","url":"https://example.com/ip"}]',
        }
        with self.assertRaisesRegex(ConfigError, "requests_per_endpoint"):
            load_config(environ=environment)

    def test_proxy_credentials_must_be_separate_and_complete(self) -> None:
        base = {
            "PHC_ENDPOINTS": '[{"name":"ip","url":"https://example.com/ip"}]',
        }
        with self.assertRaisesRegex(ConfigError, "must not contain credentials"):
            load_config(
                environ={
                    **base,
                    "PHC_PROXY_URL": "http://user:secret@proxy.example:8080",
                }
            )
        with self.assertRaisesRegex(ConfigError, "provided together"):
            load_config(
                environ={
                    **base,
                    "PHC_PROXY_URL": "http://proxy.example:8080",
                    "PHC_PROXY_USERNAME": "user",
                }
            )

    def test_private_targets_require_explicit_opt_in(self) -> None:
        environment = {
            "PHC_PROXY_URL": "http://proxy.example:8080",
            "PHC_ENDPOINTS": '[{"name":"metadata","url":"https://169.254.169.254/"}]',
        }
        with self.assertRaisesRegex(ConfigError, "PHC_ALLOW_PRIVATE_TARGETS=true"):
            load_config(environ=environment)

        loaded = load_config(
            environ={**environment, "PHC_ALLOW_PRIVATE_TARGETS": "true"}
        )
        self.assertTrue(loaded.allow_private_targets)

    def test_private_target_opt_in_must_be_a_real_boolean(self) -> None:
        payload = {
            "proxy_url": "http://proxy.example:8080",
            "allow_private_targets": "false",
            "endpoints": [{"name": "ip", "url": "https://example.com/ip"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "JSON boolean"):
                load_config(path, environ={})

    def test_endpoint_invalid_port_and_fragment_are_configuration_errors(self) -> None:
        base = {"PHC_PROXY_URL": "http://proxy.example:8080"}
        for url in (
            "https://example.com:99999/ip",
            "https://example.com/ip#secret",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ConfigError):
                    load_config(
                        environ={
                            **base,
                            "PHC_ENDPOINTS": json.dumps(
                                [{"name": "ip", "url": url}]
                            ),
                        }
                    )

    def test_proxy_secrets_are_hidden_from_repr_and_proxy_url_is_strict(self) -> None:
        loaded = load_config(
            environ={
                "PHC_PROXY_URL": "http://proxy.example:8080",
                "PHC_PROXY_USERNAME": "account",
                "PHC_PROXY_PASSWORD": "secret-value",
                "PHC_ENDPOINTS": '[{"name":"ip","url":"https://example.com/ip"}]',
            }
        )
        self.assertNotIn("account", repr(loaded))
        self.assertNotIn("secret-value", repr(loaded))
        self.assertNotIn("proxy.example", repr(loaded))
        with self.assertRaisesRegex(ConfigError, "only scheme, host, and port"):
            load_config(
                environ={
                    "PHC_PROXY_URL": "http://proxy.example:8080/path?query=1",
                    "PHC_ENDPOINTS": '[{"name":"ip","url":"https://example.com/ip"}]',
                }
            )


if __name__ == "__main__":
    unittest.main()
