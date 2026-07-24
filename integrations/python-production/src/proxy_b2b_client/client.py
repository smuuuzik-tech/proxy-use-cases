"""Synchronous production HTTP client with bounded, safe retries."""

from __future__ import annotations

import random
import time
import uuid
import ipaddress
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlsplit

import httpx

from .config import ClientSettings, ConfigError
from .execution import ExecutionContract, build_execution_contract
from .redaction import redact_url


IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ResponseTooLarge(RuntimeError):
    pass


class DeadlineExceeded(RuntimeError):
    pass


@dataclass
class RequestResult:
    """A machine-readable request result; raw response stays available to code."""

    ok: bool
    request_id: str
    method: str
    url: str
    attempts: int
    elapsed_ms: int
    status_code: Optional[int] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    response: Optional[httpx.Response] = field(default=None, repr=False)
    execution_error_kind: Optional[str] = field(default=None, repr=False)
    estimated_cost_per_attempt: Optional[float] = field(default=None, repr=False)
    cost_currency: Optional[str] = field(default=None, repr=False)

    @property
    def execution(self) -> ExecutionContract:
        return build_execution_contract(
            ok=self.ok,
            attempts=self.attempts,
            elapsed_ms=self.elapsed_ms,
            status_code=self.status_code,
            response_bytes=(
                len(self.response.content)
                if self.response is not None
                else None
            ),
            error_code=self.error_code,
            error_kind=self.execution_error_kind,
            estimated_cost_per_attempt=self.estimated_cost_per_attempt,
            cost_currency=self.cost_currency,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": self.ok,
            "request_id": self.request_id,
            "method": self.method,
            "url": self.url,
            "status_code": self.status_code,
            "attempts": self.attempts,
            "retries": max(0, self.attempts - 1),
            "elapsed_ms": self.elapsed_ms,
            "execution": self.execution.to_dict(),
        }
        if self.response is not None:
            payload["response"] = {
                "content_type": self.response.headers.get("content-type"),
                "bytes": len(self.response.content),
            }
        if self.error_code is not None:
            payload["error"] = {
                "code": self.error_code,
                "message": self.message,
            }
        return payload


def _validate_target_url(url: str, settings: ClientSettings) -> None:
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError as exc:
        raise ConfigError("Target URL is invalid.") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("Target URL must be an absolute HTTP or HTTPS URL.")
    if parsed.scheme.lower() != "https" and not settings.allow_http_targets:
        raise ConfigError("Target URL must use HTTPS unless B2B_ALLOW_HTTP_TARGETS=true.")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError("Target URL must not contain credentials.")
    if not settings.allow_private_targets and _is_private_target(parsed.hostname):
        raise ConfigError(
            "Private, loopback, link-local, and localhost targets require "
            "B2B_ALLOW_PRIVATE_TARGETS=true."
        )


def _is_private_target(hostname: str) -> bool:
    normalized = hostname.strip("[]").rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return bool(
            re.fullmatch(
                r"(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*",
                normalized,
            )
        )
    return not address.is_global or address.is_multicast


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        moment = parsedate_to_datetime(stripped)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max(0.0, (moment - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _transport_message(exc: httpx.TransportError) -> str:
    if isinstance(exc, httpx.ProxyError):
        return "Proxy connection failed."
    if isinstance(exc, httpx.TimeoutException):
        return "Request timed out."
    if isinstance(exc, httpx.ConnectError):
        return "Connection failed."
    if isinstance(exc, httpx.ProtocolError):
        return "HTTP protocol error."
    return "Network transport failed."


class B2BHttpClient:
    """Reusable HTTPX client for B2B requests sent through one proxy endpoint."""

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
        **client_kwargs: Any,
    ) -> "B2BHttpClient":
        """Create a ready client from validated B2B_PROXY_* environment values."""

        return cls(ClientSettings.from_env(env), **client_kwargs)

    def __init__(
        self,
        settings: ClientSettings,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        self._jitter = jitter
        timeout = httpx.Timeout(
            connect=settings.connect_timeout,
            read=settings.read_timeout,
            write=settings.write_timeout,
            pool=settings.pool_timeout,
        )
        limits = httpx.Limits(
            max_connections=settings.max_connections,
            max_keepalive_connections=settings.max_keepalive_connections,
        )
        kwargs: Dict[str, Any] = {
            "timeout": timeout,
            "limits": limits,
            "follow_redirects": settings.follow_redirects,
            "trust_env": False,
            "headers": {"User-Agent": "andrey-proxy-sdk/0.2.0"},
        }
        if transport is None:
            kwargs["proxy"] = settings.authenticated_proxy_url
        else:
            # Test/custom transports are authoritative and never open a real proxy socket.
            kwargs["transport"] = transport
        try:
            self._client = httpx.Client(**kwargs)
        except ImportError as exc:
            raise ConfigError(
                "SOCKS proxy support requires installation with the socks extra."
            ) from exc

    def __enter__(self) -> "B2BHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        request_id: Optional[str] = None,
        retry: Optional[bool] = None,
    ) -> RequestResult:
        """Send a GET request with the SDK's bounded retry and redaction policy."""

        return self.request(
            "GET",
            url,
            headers=headers,
            request_id=request_id,
            retry=retry,
        )

    def _delay_for_retry(self, failed_attempt: int) -> float:
        exponential = self.settings.backoff_base * (2 ** (failed_attempt - 1))
        bounded = min(self.settings.backoff_max, exponential)
        return bounded + self._jitter(0.0, self.settings.backoff_jitter)

    def _result(self, **values: Any) -> RequestResult:
        return RequestResult(
            estimated_cost_per_attempt=self.settings.estimated_cost_per_attempt,
            cost_currency=self.settings.cost_currency,
            **values,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        content: Optional[str] = None,
        json_data: Any = None,
        request_id: Optional[str] = None,
        retry: Optional[bool] = None,
    ) -> RequestResult:
        method = method.upper().strip()
        if not method:
            raise ConfigError("HTTP method is required.")
        _validate_target_url(url, self.settings)
        if content is not None and json_data is not None:
            raise ConfigError("content and json_data are mutually exclusive.")

        request_headers = dict(headers or {})
        supplied_ids = [
            value for name, value in request_headers.items()
            if name.lower() == "x-request-id"
        ]
        if len(supplied_ids) > 1:
            raise ConfigError("Only one X-Request-ID header is allowed.")
        header_request_id = supplied_ids[0] if supplied_ids else None
        if request_id and header_request_id and request_id != header_request_id:
            raise ConfigError("request_id conflicts with the X-Request-ID header.")
        correlation_id = request_id or header_request_id or str(uuid.uuid4())
        if not correlation_id.strip() or len(correlation_id) > 128:
            raise ConfigError("Request ID must contain 1..128 characters.")
        if "\n" in correlation_id or "\r" in correlation_id:
            raise ConfigError("Request ID must not contain line breaks.")

        request_headers = {
            name: value
            for name, value in request_headers.items()
            if name.lower() != "x-request-id"
        }
        request_headers["X-Request-ID"] = correlation_id
        retry_allowed = method in IDEMPOTENT_METHODS
        if retry is False:
            retry_allowed = False
        elif retry is True and not retry_allowed:
            raise ConfigError(
                "Automatic retries can be enabled only for idempotent HTTP methods."
            )
        attempt_limit = self.settings.max_attempts if retry_allowed else 1
        safe_target = redact_url(url)
        started = time.monotonic()

        for attempt in range(1, attempt_limit + 1):
            elapsed = time.monotonic() - started
            if elapsed >= self.settings.total_deadline:
                return self._result(
                    ok=False,
                    request_id=correlation_id,
                    method=method,
                    url=safe_target,
                    attempts=max(0, attempt - 1),
                    elapsed_ms=round(elapsed * 1000),
                    error_code="deadline_exceeded",
                    message="The total request deadline was exceeded.",
                )
            request_kwargs: Dict[str, Any] = {"headers": request_headers}
            remaining = self.settings.total_deadline - elapsed
            request_kwargs["timeout"] = httpx.Timeout(
                connect=min(self.settings.connect_timeout, remaining),
                read=min(self.settings.read_timeout, remaining),
                write=min(self.settings.write_timeout, remaining),
                pool=min(self.settings.pool_timeout, remaining),
            )
            if content is not None:
                request_kwargs["content"] = content
            if json_data is not None:
                request_kwargs["json"] = json_data
            try:
                request = self._client.build_request(method, url, **request_kwargs)
                response = self._client.send(request, stream=True)
                if (
                    response.status_code in RETRYABLE_STATUS_CODES
                    and retry_allowed
                    and attempt < attempt_limit
                ):
                    retry_after = _retry_after_seconds(response)
                    if (
                        retry_after is not None
                        and retry_after > self.settings.retry_after_max
                    ):
                        response.close()
                        return self._result(
                            ok=False,
                            request_id=correlation_id,
                            method=method,
                            url=safe_target,
                            attempts=attempt,
                            elapsed_ms=round((time.monotonic() - started) * 1000),
                            status_code=response.status_code,
                            error_code="retry_after_exceeds_budget",
                            message="Upstream requested a retry delay above the configured budget.",
                        )
                    response.close()
                    delay = self._delay_for_retry(attempt)
                    if retry_after is not None:
                        delay = max(delay, retry_after)
                    if time.monotonic() - started + delay >= self.settings.total_deadline:
                        return self._result(
                            ok=False,
                            request_id=correlation_id,
                            method=method,
                            url=safe_target,
                            attempts=attempt,
                            elapsed_ms=round((time.monotonic() - started) * 1000),
                            status_code=response.status_code,
                            error_code="deadline_exceeded",
                            message="The next retry would exceed the total request deadline.",
                        )
                    self._sleep(delay)
                    continue

                content_buffer = bytearray()
                try:
                    for chunk in response.iter_bytes():
                        if time.monotonic() - started >= self.settings.total_deadline:
                            raise DeadlineExceeded
                        if len(content_buffer) + len(chunk) > self.settings.max_response_bytes:
                            raise ResponseTooLarge
                        content_buffer.extend(chunk)
                finally:
                    response.close()
                response = httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=bytes(content_buffer),
                    request=response.request,
                    extensions=response.extensions,
                )
            except ResponseTooLarge:
                return self._result(
                    ok=False,
                    request_id=correlation_id,
                    method=method,
                    url=safe_target,
                    attempts=attempt,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    error_code="response_too_large",
                    message="Response body exceeded the configured size limit.",
                )
            except DeadlineExceeded:
                return self._result(
                    ok=False,
                    request_id=correlation_id,
                    method=method,
                    url=safe_target,
                    attempts=attempt,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    error_code="deadline_exceeded",
                    message="The total request deadline was exceeded.",
                )
            except httpx.TransportError as exc:
                if retry_allowed and attempt < attempt_limit:
                    delay = self._delay_for_retry(attempt)
                    if time.monotonic() - started + delay >= self.settings.total_deadline:
                        return self._result(
                            ok=False,
                            request_id=correlation_id,
                            method=method,
                            url=safe_target,
                            attempts=attempt,
                            elapsed_ms=round((time.monotonic() - started) * 1000),
                            error_code="deadline_exceeded",
                            message="The next retry would exceed the total request deadline.",
                        )
                    self._sleep(delay)
                    continue
                return self._result(
                    ok=False,
                    request_id=correlation_id,
                    method=method,
                    url=safe_target,
                    attempts=attempt,
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    error_code="transport_error",
                    execution_error_kind=(
                        "timeout"
                        if isinstance(exc, httpx.TimeoutException)
                        else "transport_error"
                    ),
                    message=_transport_message(exc),
                )

            ok = response.is_success
            return self._result(
                ok=ok,
                request_id=correlation_id,
                method=method,
                url=safe_target,
                attempts=attempt,
                elapsed_ms=round((time.monotonic() - started) * 1000),
                status_code=response.status_code,
                error_code=None if ok else "http_status",
                message=None
                if ok
                else "Upstream returned an unsuccessful HTTP status.",
                response=response,
            )

        raise RuntimeError("Unreachable retry state.")
