from __future__ import annotations

import os
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proxy_healthcheck.transport import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    NoRedirectHandler,
    StrictProxyHandler,
    UrllibTransport,
    _read_limited,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self, amount: int) -> bytes:
        return self.body[:amount]


class ChunkedResponse:
    def read1(self, amount: int) -> bytes:
        return b"x"


class SuccessfulResponse:
    status = 200
    headers = {"content-type": "application/json"}

    def __init__(self) -> None:
        self._chunks = iter([b'{"ip":"192.0.2.1"}', b""])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read1(self, amount: int) -> bytes:
        return next(self._chunks)


class FakeOpener:
    def open(self, request, timeout):
        return SuccessfulResponse()


class TransportPolicyTests(unittest.TestCase):
    def test_urllib_transport_success_uses_defined_deadline(self) -> None:
        with patch(
            "proxy_healthcheck.transport.urllib.request.build_opener",
            return_value=FakeOpener(),
        ):
            result = UrllibTransport().request(
                "https://allowed.example/ip",
                "http://proxy.internal:8080",
                1.0,
            )
        self.assertEqual(result.status_code, 200)
        self.assertIn(b"192.0.2.1", result.body)

    def test_strict_proxy_handler_ignores_no_proxy(self) -> None:
        request = urllib.request.Request("http://allowed.example/ip")
        handler = StrictProxyHandler({"http": "http://proxy.internal:8080"})

        with patch.dict(os.environ, {"NO_PROXY": "allowed.example"}):
            result = handler.proxy_open(
                request,
                "http://proxy.internal:8080",
                "http",
            )

        self.assertIsNone(result)
        self.assertEqual(request.host, "proxy.internal:8080")

    def test_redirects_are_not_followed(self) -> None:
        handler = NoRedirectHandler()
        request = urllib.request.Request("https://allowed.example/ip")
        self.assertIsNone(
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://other.example/ip",
            )
        )

    def test_response_body_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            _read_limited(FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 1)))

    def test_response_read_has_a_total_deadline(self) -> None:
        times = iter([0.0, 0.6, 1.1])
        with self.assertRaisesRegex(TimeoutError, "total attempt deadline"):
            _read_limited(
                ChunkedResponse(),
                deadline=1.0,
                clock=lambda: next(times),
            )


if __name__ == "__main__":
    unittest.main()
