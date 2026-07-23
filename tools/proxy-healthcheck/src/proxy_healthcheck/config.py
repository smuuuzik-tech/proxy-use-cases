from __future__ import annotations

import json
import ipaddress
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

from .redaction import redact_url


class ConfigError(ValueError):
    pass


MAX_ENDPOINTS = 20
MAX_REQUESTS_PER_ENDPOINT = 100
MAX_CONCURRENCY = 64
MAX_TIMEOUT_SECONDS = 60.0
MAX_RETRY_BUDGET = 5
MAX_RETRY_BACKOFF_SECONDS = 30.0
MAX_P95_MS = 600_000.0


@dataclass(frozen=True)
class EndpointConfig:
    name: str
    url: str = field(repr=False)
    ip_json_path: str = "ip"
    expected_status: tuple[int, ...] = (200,)
    minimum_unique_ips: int | None = None


@dataclass(frozen=True)
class HealthcheckConfig:
    proxy_url: str = field(repr=False)
    endpoints: tuple[EndpointConfig, ...]
    proxy_username: str | None = field(default=None, repr=False)
    proxy_password: str | None = field(default=None, repr=False)
    requests_per_endpoint: int = 5
    concurrency: int = 10
    timeout_seconds: float = 5.0
    retry_budget: int = 1
    retry_backoff_seconds: float = 0.2
    minimum_success_rate: float = 0.95
    fail_below_success_rate: float = 0.50
    maximum_p95_ms: float = 2000.0
    minimum_unique_ips: int = 1
    allow_private_targets: bool = False

    @property
    def authenticated_proxy_url(self) -> str:
        parsed = urlsplit(self.proxy_url)
        if not self.proxy_username:
            return self.proxy_url
        username = quote(self.proxy_username, safe="")
        password = quote(self.proxy_password or "", safe="")
        return urlunsplit(
            (
                parsed.scheme,
                f"{username}:{password}@{parsed.netloc}",
                "",
                "",
                "",
            )
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "proxy": {
                "scheme": urlsplit(self.proxy_url).scheme,
                "authentication": (
                    "configured" if self.proxy_username else "none"
                ),
            },
            "endpoints": [
                {
                    "name": endpoint.name,
                    "url": redact_url(endpoint.url),
                    "ip_json_path": endpoint.ip_json_path,
                    "expected_status": list(endpoint.expected_status),
                    "minimum_unique_ips": endpoint.minimum_unique_ips,
                }
                for endpoint in self.endpoints
            ],
            "requests_per_endpoint": self.requests_per_endpoint,
            "concurrency": self.concurrency,
            "timeout_seconds": self.timeout_seconds,
            "retry_budget": self.retry_budget,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "minimum_success_rate": self.minimum_success_rate,
            "fail_below_success_rate": self.fail_below_success_rate,
            "maximum_p95_ms": self.maximum_p95_ms,
            "minimum_unique_ips": self.minimum_unique_ips,
            "allow_private_targets": self.allow_private_targets,
        }


_ENV_CASTS: dict[str, tuple[str, type]] = {
    "PHC_PROXY_URL": ("proxy_url", str),
    "PHC_PROXY_USERNAME": ("proxy_username", str),
    "PHC_PROXY_PASSWORD": ("proxy_password", str),
    "PHC_REQUESTS_PER_ENDPOINT": ("requests_per_endpoint", int),
    "PHC_CONCURRENCY": ("concurrency", int),
    "PHC_TIMEOUT_SECONDS": ("timeout_seconds", float),
    "PHC_RETRY_BUDGET": ("retry_budget", int),
    "PHC_RETRY_BACKOFF_SECONDS": ("retry_backoff_seconds", float),
    "PHC_MINIMUM_SUCCESS_RATE": ("minimum_success_rate", float),
    "PHC_FAIL_BELOW_SUCCESS_RATE": ("fail_below_success_rate", float),
    "PHC_MAXIMUM_P95_MS": ("maximum_p95_ms", float),
    "PHC_MINIMUM_UNIQUE_IPS": ("minimum_unique_ips", int),
}


def load_config(
    path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> HealthcheckConfig:
    environment = os.environ if environ is None else environ
    raw: dict[str, Any] = {}
    if path:
        config_path = Path(path)
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"cannot read config file: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON config: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("config root must be a JSON object")

    for env_name, (field, cast) in _ENV_CASTS.items():
        if env_name in environment:
            try:
                raw[field] = cast(environment[env_name])
            except ValueError as exc:
                raise ConfigError(f"{env_name} has an invalid value") from exc

    if "PHC_ENDPOINTS" in environment:
        try:
            raw["endpoints"] = json.loads(environment["PHC_ENDPOINTS"])
        except json.JSONDecodeError as exc:
            raise ConfigError("PHC_ENDPOINTS must be valid JSON") from exc
    if "PHC_ALLOW_PRIVATE_TARGETS" in environment:
        normalized = environment["PHC_ALLOW_PRIVATE_TARGETS"].strip().lower()
        if normalized not in {"true", "false"}:
            raise ConfigError("PHC_ALLOW_PRIVATE_TARGETS must be true or false")
        raw["allow_private_targets"] = normalized == "true"
    allow_private_targets = raw.get("allow_private_targets", False)
    if not isinstance(allow_private_targets, bool):
        raise ConfigError("allow_private_targets must be a JSON boolean")

    endpoints_raw = raw.get("endpoints", [])
    if not isinstance(endpoints_raw, list):
        raise ConfigError("endpoints must be a JSON array")
    endpoints: list[EndpointConfig] = []
    for index, item in enumerate(endpoints_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"endpoints[{index}] must be an object")
        try:
            expected = item.get("expected_status", [200])
            endpoints.append(
                EndpointConfig(
                    name=str(item["name"]),
                    url=str(item["url"]),
                    ip_json_path=str(item.get("ip_json_path", "ip")),
                    expected_status=tuple(int(status) for status in expected),
                    minimum_unique_ips=(
                        int(item["minimum_unique_ips"])
                        if item.get("minimum_unique_ips") is not None
                        else None
                    ),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"invalid endpoints[{index}]: {exc}") from exc

    try:
        config = HealthcheckConfig(
            proxy_url=str(raw.get("proxy_url", "")),
            endpoints=tuple(endpoints),
            proxy_username=(
                str(raw["proxy_username"])
                if raw.get("proxy_username") is not None
                else None
            ),
            proxy_password=(
                str(raw["proxy_password"])
                if raw.get("proxy_password") is not None
                else None
            ),
            requests_per_endpoint=int(raw.get("requests_per_endpoint", 5)),
            concurrency=int(raw.get("concurrency", 10)),
            timeout_seconds=float(raw.get("timeout_seconds", 5.0)),
            retry_budget=int(raw.get("retry_budget", 1)),
            retry_backoff_seconds=float(raw.get("retry_backoff_seconds", 0.2)),
            minimum_success_rate=float(raw.get("minimum_success_rate", 0.95)),
            fail_below_success_rate=float(raw.get("fail_below_success_rate", 0.50)),
            maximum_p95_ms=float(raw.get("maximum_p95_ms", 2000.0)),
            minimum_unique_ips=int(raw.get("minimum_unique_ips", 1)),
            allow_private_targets=allow_private_targets,
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid config value: {exc}") from exc
    _validate(config)
    return config


def _validate(config: HealthcheckConfig) -> None:
    if not config.proxy_url:
        raise ConfigError("proxy_url is required (file or PHC_PROXY_URL)")
    proxy = urlsplit(config.proxy_url)
    if proxy.scheme not in {"http", "https"} or not proxy.hostname:
        raise ConfigError("proxy_url must be an http:// or https:// URL with a hostname")
    try:
        proxy.port
    except ValueError as exc:
        raise ConfigError("proxy_url contains an invalid port") from exc
    if proxy.username is not None or proxy.password is not None:
        raise ConfigError(
            "proxy_url must not contain credentials; use proxy_username and proxy_password"
        )
    if proxy.path not in {"", "/"} or proxy.query or proxy.fragment:
        raise ConfigError("proxy_url must contain only scheme, host, and port")
    if (
        config.proxy_username is not None
        and not config.proxy_username.strip()
    ) or (
        config.proxy_password is not None
        and not config.proxy_password.strip()
    ):
        raise ConfigError("proxy credentials must not contain only whitespace")
    has_username = config.proxy_username is not None and bool(config.proxy_username)
    has_password = config.proxy_password is not None and bool(config.proxy_password)
    if has_username != has_password:
        raise ConfigError("proxy_username and proxy_password must be provided together")
    if not config.endpoints:
        raise ConfigError("at least one endpoint is required")
    if len(config.endpoints) > MAX_ENDPOINTS:
        raise ConfigError(f"endpoints cannot contain more than {MAX_ENDPOINTS} entries")
    names: set[str] = set()
    for endpoint in config.endpoints:
        if not endpoint.name or endpoint.name in names:
            raise ConfigError("endpoint names must be non-empty and unique")
        names.add(endpoint.name)
        parsed = urlsplit(endpoint.url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ConfigError(f"endpoint {endpoint.name!r} must use HTTPS")
        try:
            parsed.port
        except ValueError as exc:
            raise ConfigError(
                f"endpoint {endpoint.name!r} contains an invalid port"
            ) from exc
        if parsed.username is not None or parsed.password is not None:
            raise ConfigError(f"endpoint {endpoint.name!r} must not contain credentials")
        if parsed.fragment:
            raise ConfigError(f"endpoint {endpoint.name!r} must not contain a fragment")
        if not config.allow_private_targets and _is_non_global_target(parsed.hostname):
            raise ConfigError(
                f"endpoint {endpoint.name!r} is private or non-global; "
                "set PHC_ALLOW_PRIVATE_TARGETS=true only for an approved internal target"
            )
        if not endpoint.expected_status:
            raise ConfigError(f"endpoint {endpoint.name!r} expected_status cannot be empty")
        if any(status < 100 or status > 599 for status in endpoint.expected_status):
            raise ConfigError(
                f"endpoint {endpoint.name!r} expected_status values must be between 100 and 599"
            )
        if endpoint.minimum_unique_ips is not None and endpoint.minimum_unique_ips < 1:
            raise ConfigError(f"endpoint {endpoint.name!r} minimum_unique_ips must be >= 1")
        if (
            endpoint.minimum_unique_ips is not None
            and endpoint.minimum_unique_ips > config.requests_per_endpoint
        ):
            raise ConfigError(
                f"endpoint {endpoint.name!r} minimum_unique_ips cannot exceed "
                "requests_per_endpoint"
            )
    if not 1 <= config.requests_per_endpoint <= MAX_REQUESTS_PER_ENDPOINT:
        raise ConfigError(
            f"requests_per_endpoint must be between 1 and {MAX_REQUESTS_PER_ENDPOINT}"
        )
    if not 1 <= config.concurrency <= MAX_CONCURRENCY:
        raise ConfigError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    if (
        not math.isfinite(config.timeout_seconds)
        or not 0 < config.timeout_seconds <= MAX_TIMEOUT_SECONDS
    ):
        raise ConfigError(f"timeout_seconds must be finite and between 0 and {MAX_TIMEOUT_SECONDS}")
    if not 0 <= config.retry_budget <= MAX_RETRY_BUDGET:
        raise ConfigError(f"retry_budget must be between 0 and {MAX_RETRY_BUDGET}")
    if (
        not math.isfinite(config.retry_backoff_seconds)
        or not 0 <= config.retry_backoff_seconds <= MAX_RETRY_BACKOFF_SECONDS
    ):
        raise ConfigError(
            "retry_backoff_seconds must be finite and between 0 and "
            f"{MAX_RETRY_BACKOFF_SECONDS}"
        )
    if not math.isfinite(config.minimum_success_rate) or not math.isfinite(
        config.fail_below_success_rate
    ):
        raise ConfigError("success thresholds must be finite")
    if not 0 <= config.fail_below_success_rate <= config.minimum_success_rate <= 1:
        raise ConfigError(
            "success thresholds must satisfy 0 <= fail_below_success_rate "
            "<= minimum_success_rate <= 1"
        )
    if (
        not math.isfinite(config.maximum_p95_ms)
        or not 0 < config.maximum_p95_ms <= MAX_P95_MS
    ):
        raise ConfigError(f"maximum_p95_ms must be finite and between 0 and {MAX_P95_MS}")
    if not 1 <= config.minimum_unique_ips <= config.requests_per_endpoint:
        raise ConfigError(
            "minimum_unique_ips must be between 1 and requests_per_endpoint"
        )


def _is_non_global_target(hostname: str) -> bool:
    normalized = hostname.strip("[]").rstrip(".").lower()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
        return not address.is_global or address.is_multicast
    except ValueError:
        return bool(
            re.fullmatch(
                r"(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*",
                normalized,
            )
        )
