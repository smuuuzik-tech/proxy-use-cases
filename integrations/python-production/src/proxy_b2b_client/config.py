"""Validated configuration with credentials kept separate from proxy URLs."""

from __future__ import annotations

import os
import math
from dataclasses import dataclass, field
from typing import Mapping, Optional
from urllib.parse import quote, urlsplit, urlunsplit


class ConfigError(ValueError):
    """Raised when client configuration is missing or unsafe."""


_ALLOWED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


def _parse_float(
    env: Mapping[str, str],
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float,
) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ConfigError(f"{name} must be finite and in range {minimum}..{maximum}.")
    return value


def _parse_int(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: Optional[int] = None,
) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc
    if value < minimum or (maximum is not None and value > maximum):
        bounds = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
        raise ConfigError(f"{name} must be in range {bounds}.")
    return value


def _parse_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false.")


def _parse_optional_float(
    env: Mapping[str, str],
    name: str,
    *,
    minimum: float,
    maximum: float,
) -> Optional[float]:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ConfigError(f"{name} must be finite and in range {minimum}..{maximum}.")
    return value


@dataclass(frozen=True)
class ClientSettings:
    """Settings for one reusable HTTPX client and its retry policy."""

    proxy_url: str = field(repr=False)
    proxy_username: Optional[str] = field(default=None, repr=False)
    proxy_password: Optional[str] = field(default=None, repr=False)
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    write_timeout: float = 30.0
    pool_timeout: float = 5.0
    max_attempts: int = 3
    backoff_base: float = 0.5
    backoff_max: float = 8.0
    backoff_jitter: float = 0.25
    max_connections: int = 100
    max_keepalive_connections: int = 20
    follow_redirects: bool = False
    retry_after_max: float = 30.0
    total_deadline: float = 120.0
    max_response_bytes: int = 1_048_576
    allow_http_targets: bool = False
    allow_private_targets: bool = False
    estimated_cost_per_attempt: Optional[float] = None
    cost_currency: Optional[str] = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.proxy_url)
        if parsed.scheme.lower() not in _ALLOWED_PROXY_SCHEMES:
            raise ConfigError(
                "B2B_PROXY_URL must use http, https, socks5, or socks5h."
            )
        if not parsed.hostname:
            raise ConfigError("B2B_PROXY_URL must contain a host.")
        try:
            parsed.port
        except ValueError as exc:
            raise ConfigError("B2B_PROXY_URL contains an invalid port.") from exc
        if parsed.username is not None or parsed.password is not None:
            raise ConfigError(
                "B2B_PROXY_URL must not contain credentials; use separate variables."
            )
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ConfigError("B2B_PROXY_URL must contain only scheme, host, and port.")

        has_username = self.proxy_username is not None and bool(self.proxy_username)
        has_password = self.proxy_password is not None and bool(self.proxy_password)
        if (
            self.proxy_username is not None
            and not self.proxy_username.strip()
        ) or (
            self.proxy_password is not None
            and not self.proxy_password.strip()
        ):
            raise ConfigError("Proxy credentials must not contain only whitespace.")
        if has_username != has_password:
            raise ConfigError(
                "B2B_PROXY_USERNAME and B2B_PROXY_PASSWORD must be set together."
            )
        if self.max_attempts < 1 or self.max_attempts > 10:
            raise ConfigError("max_attempts must be in range 1..10.")
        for name, value in (
            ("connect_timeout", self.connect_timeout),
            ("read_timeout", self.read_timeout),
            ("write_timeout", self.write_timeout),
            ("pool_timeout", self.pool_timeout),
        ):
            if not math.isfinite(value) or not 0 < value <= 120:
                raise ConfigError(f"{name} must be finite and in range 0..120.")
        if (
            not math.isfinite(self.backoff_base)
            or not math.isfinite(self.backoff_max)
            or self.backoff_base < 0
            or self.backoff_max < 0
            or self.backoff_max > 60
        ):
            raise ConfigError("Backoff values must be finite and in range 0..60.")
        if self.backoff_max < self.backoff_base:
            raise ConfigError("backoff_max must be at least backoff_base.")
        if (
            not math.isfinite(self.backoff_jitter)
            or not 0 <= self.backoff_jitter <= 10
        ):
            raise ConfigError("backoff_jitter must be finite and in range 0..10.")
        if not 1 <= self.max_connections <= 1000 or not 0 <= self.max_keepalive_connections <= 1000:
            raise ConfigError("Connection limits are invalid.")
        if self.max_keepalive_connections > self.max_connections:
            raise ConfigError(
                "max_keepalive_connections must not exceed max_connections."
            )
        if self.follow_redirects:
            raise ConfigError(
                "Automatic redirects are disabled; validate and request the next URL explicitly."
            )
        if not math.isfinite(self.retry_after_max) or not 0 <= self.retry_after_max <= 300:
            raise ConfigError("retry_after_max must be finite and in range 0..300.")
        if not math.isfinite(self.total_deadline) or not 1 <= self.total_deadline <= 600:
            raise ConfigError("total_deadline must be finite and in range 1..600.")
        if not 1 <= self.max_response_bytes <= 10_485_760:
            raise ConfigError("max_response_bytes must be in range 1..10485760.")
        if (self.estimated_cost_per_attempt is None) != (self.cost_currency is None):
            raise ConfigError(
                "estimated_cost_per_attempt and cost_currency must be set together."
            )
        if self.estimated_cost_per_attempt is not None and (
            not math.isfinite(self.estimated_cost_per_attempt)
            or not 0 <= self.estimated_cost_per_attempt <= 1_000_000
        ):
            raise ConfigError(
                "estimated_cost_per_attempt must be finite and in range 0..1000000."
            )
        if self.cost_currency is not None and (
            len(self.cost_currency) != 3
            or not self.cost_currency.isalpha()
            or not self.cost_currency.isupper()
            or not self.cost_currency.isascii()
        ):
            raise ConfigError("cost_currency must be a three-letter uppercase code.")

    @property
    def authenticated_proxy_url(self) -> str:
        """Build the runtime URL without exposing it in repr or public results."""

        parsed = urlsplit(self.proxy_url)
        if not self.proxy_username:
            return urlunsplit(
                (parsed.scheme.lower(), parsed.netloc, "", "", "")
            )
        username = quote(self.proxy_username, safe="")
        password = quote(self.proxy_password or "", safe="")
        netloc = f"{username}:{password}@{parsed.netloc}"
        return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> "ClientSettings":
        source = os.environ if env is None else env
        proxy_url = source.get("B2B_PROXY_URL", "").strip()
        if not proxy_url:
            raise ConfigError("B2B_PROXY_URL is required.")

        username = source.get("B2B_PROXY_USERNAME")
        password = source.get("B2B_PROXY_PASSWORD")
        username = username if username else None
        password = password if password else None

        return cls(
            proxy_url=proxy_url,
            proxy_username=username,
            proxy_password=password,
            connect_timeout=_parse_float(
                source, "B2B_TIMEOUT_CONNECT_SECONDS", 10.0, minimum=0.001, maximum=120
            ),
            read_timeout=_parse_float(
                source, "B2B_TIMEOUT_READ_SECONDS", 30.0, minimum=0.001, maximum=120
            ),
            write_timeout=_parse_float(
                source, "B2B_TIMEOUT_WRITE_SECONDS", 30.0, minimum=0.001, maximum=120
            ),
            pool_timeout=_parse_float(
                source, "B2B_TIMEOUT_POOL_SECONDS", 5.0, minimum=0.001, maximum=120
            ),
            max_attempts=_parse_int(
                source, "B2B_MAX_ATTEMPTS", 3, minimum=1, maximum=10
            ),
            backoff_base=_parse_float(
                source, "B2B_BACKOFF_BASE_SECONDS", 0.5, maximum=60
            ),
            backoff_max=_parse_float(
                source, "B2B_BACKOFF_MAX_SECONDS", 8.0, maximum=60
            ),
            backoff_jitter=_parse_float(
                source, "B2B_BACKOFF_JITTER_SECONDS", 0.25, maximum=10
            ),
            max_connections=_parse_int(
                source, "B2B_MAX_CONNECTIONS", 100, minimum=1, maximum=1000
            ),
            max_keepalive_connections=_parse_int(
                source, "B2B_MAX_KEEPALIVE_CONNECTIONS", 20, minimum=0, maximum=1000
            ),
            follow_redirects=_parse_bool(
                source, "B2B_FOLLOW_REDIRECTS", False
            ),
            retry_after_max=_parse_float(
                source, "B2B_RETRY_AFTER_MAX_SECONDS", 30.0, maximum=300
            ),
            total_deadline=_parse_float(
                source, "B2B_TOTAL_DEADLINE_SECONDS", 120.0, minimum=1, maximum=600
            ),
            max_response_bytes=_parse_int(
                source, "B2B_MAX_RESPONSE_BYTES", 1_048_576, minimum=1, maximum=10_485_760
            ),
            allow_http_targets=_parse_bool(
                source, "B2B_ALLOW_HTTP_TARGETS", False
            ),
            allow_private_targets=_parse_bool(
                source, "B2B_ALLOW_PRIVATE_TARGETS", False
            ),
            estimated_cost_per_attempt=_parse_optional_float(
                source,
                "B2B_ESTIMATED_COST_PER_ATTEMPT",
                minimum=0,
                maximum=1_000_000,
            ),
            cost_currency=(
                source["B2B_COST_CURRENCY"].strip().upper()
                if source.get("B2B_COST_CURRENCY", "").strip()
                else None
            ),
        )
