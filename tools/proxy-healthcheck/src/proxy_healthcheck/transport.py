from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
import time
from base64 import b64encode
from dataclasses import dataclass
from typing import Mapping, Protocol

MAX_RESPONSE_BYTES = 65_536


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] | None = None


class Transport(Protocol):
    def request(self, url: str, proxy_url: str, timeout_seconds: float) -> TransportResponse:
        """Perform one GET via proxy, or raise an exception."""


class UrllibTransport:
    """Small transport that always uses the configured proxy and never follows redirects."""

    def __init__(self, user_agent: str = "proxy-healthcheck/0.1") -> None:
        self.user_agent = user_agent

    def request(self, url: str, proxy_url: str, timeout_seconds: float) -> TransportResponse:
        deadline = time.monotonic() + timeout_seconds
        proxy_handler = StrictProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler, NoRedirectHandler())
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json, text/plain;q=0.9",
                "User-Agent": self.user_agent,
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return TransportResponse(
                    status_code=response.status,
                    body=_read_limited(response, deadline=deadline),
                    headers=dict(response.headers.items()),
                )
        except urllib.error.HTTPError as exc:
            return TransportResponse(
                status_code=exc.code,
                body=_read_limited(exc, deadline=deadline),
                headers=dict(exc.headers.items()) if exc.headers else None,
            )


class StrictProxyHandler(urllib.request.ProxyHandler):
    """Proxy handler that intentionally ignores system NO_PROXY bypass rules."""

    def proxy_open(
        self,
        req: urllib.request.Request,
        proxy: str,
        type: str,
    ) -> urllib.response.addinfourl | None:
        original_type = req.type
        proxy_type, user, password, hostport = urllib.request._parse_proxy(proxy)
        if proxy_type is None:
            proxy_type = original_type

        if user and password:
            user_pass = f"{urllib.parse.unquote(user)}:{urllib.parse.unquote(password)}"
            credentials = b64encode(user_pass.encode()).decode("ascii")
            req.add_header("Proxy-authorization", f"Basic {credentials}")
        hostport = urllib.parse.unquote(hostport)
        req.set_proxy(hostport, proxy_type)
        if original_type == proxy_type or original_type == "https":
            return None
        return self.parent.open(req, timeout=req.timeout)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Return redirects to the caller as HTTP status values instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_limited(
    response: object,
    *,
    deadline: float | None = None,
    clock=time.monotonic,
) -> bytes:
    body = bytearray()
    read_chunk = getattr(response, "read1", None) or response.read
    while True:
        if deadline is not None:
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError("response exceeded the total attempt deadline")
            socket_object = getattr(
                getattr(getattr(response, "fp", None), "raw", None),
                "_sock",
                None,
            )
            if socket_object is not None:
                socket_object.settimeout(max(0.001, remaining))
        chunk = read_chunk(min(8192, MAX_RESPONSE_BYTES + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(f"response body exceeds {MAX_RESPONSE_BYTES} bytes")
