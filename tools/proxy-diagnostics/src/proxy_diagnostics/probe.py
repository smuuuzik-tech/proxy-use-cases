from __future__ import annotations

import ipaddress
import json
import os
import subprocess
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit, urlunsplit

from .redaction import redact_text, safe_proxy, safe_target


class ConfigError(ValueError):
    pass


class DiagnosticCode(str, Enum):
    OK = "ok"
    PROXY_AUTHENTICATION = "proxy_authentication"
    DNS = "dns"
    TIMEOUT = "timeout"
    TLS = "tls"
    CONNECT = "connect"
    RATE_LIMITED = "rate_limited"
    ACCESS_DENIED = "access_denied"
    UPSTREAM = "upstream"
    UNKNOWN = "unknown"


class ExitCode(IntEnum):
    OK = 0
    CONFIG = 2
    PROXY_AUTHENTICATION = 10
    DNS = 11
    TIMEOUT = 12
    TLS = 13
    CONNECT = 14
    UPSTREAM = 15
    UNKNOWN = 20


@dataclass(frozen=True)
class ProbeConfig:
    proxy_url: str
    target_url: str
    proxy_username: str | None = None
    proxy_password: str | None = None
    connect_timeout_seconds: float = 5.0
    total_timeout_seconds: float = 15.0
    allow_private_target: bool = False
    curl_binary: str = "curl"


@dataclass(frozen=True)
class ProbeReport:
    ok: bool
    diagnostic: DiagnosticCode
    exit_code: ExitCode
    summary: str
    proxy: dict[str, object]
    target_origin: str
    observations: dict[str, object]
    checks: tuple[str, ...]
    next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "proxy-diagnostics/v1",
            "ok": self.ok,
            "diagnostic": self.diagnostic,
            "exit_code": int(self.exit_code),
            "summary": self.summary,
            "proxy": self.proxy,
            "target_origin": self.target_origin,
            "observations": self.observations,
            "checks": list(self.checks),
            "next_actions": list(self.next_actions),
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]

_MARKER = "__PROXY_DIAGNOSTICS__"
_TLS_EXIT_CODES = {35, 51, 53, 58, 59, 60, 64, 66, 77, 80, 82, 83, 90, 91}
_DNS_EXIT_CODES = {5, 6}
_CONNECT_EXIT_CODES = {7}
_UPSTREAM_EXIT_CODES = {18, 47, 52, 55, 56, 92}


def validate_config(config: ProbeConfig) -> ProbeConfig:
    proxy = urlsplit(config.proxy_url)
    if proxy.scheme.lower() not in {
        "http",
        "https",
        "socks4",
        "socks4a",
        "socks5",
        "socks5h",
    }:
        raise ConfigError("proxy scheme must be HTTP, HTTPS, SOCKS4 or SOCKS5")
    if not proxy.hostname or not proxy.port:
        raise ConfigError("proxy URL must contain an explicit host and port")
    if proxy.path not in {"", "/"} or proxy.query or proxy.fragment:
        raise ConfigError("proxy URL must not contain a path, query or fragment")

    target = urlsplit(config.target_url)
    if target.scheme.lower() != "https":
        raise ConfigError("target URL must use HTTPS")
    if not target.hostname:
        raise ConfigError("target URL must contain a hostname")
    if target.username or target.password:
        raise ConfigError("target URL must not contain credentials")
    if _is_private_literal(target.hostname) and not config.allow_private_target:
        raise ConfigError("private, loopback and link-local target IPs are blocked")

    if not 0.2 <= config.connect_timeout_seconds <= 30:
        raise ConfigError("connect timeout must be between 0.2 and 30 seconds")
    if not config.connect_timeout_seconds <= config.total_timeout_seconds <= 120:
        raise ConfigError(
            "total timeout must be at least the connect timeout and at most 120 seconds"
        )
    if any(character in config.curl_binary for character in "\r\n\0"):
        raise ConfigError("curl binary contains an invalid character")
    return config


def run_probe(
    config: ProbeConfig,
    *,
    runner: Runner = subprocess.run,
    environ: Mapping[str, str] | None = None,
) -> ProbeReport:
    config = validate_config(config)
    curl_config = _build_curl_config(config)
    environment = dict(os.environ if environ is None else environ)
    environment["NO_PROXY"] = ""
    environment["no_proxy"] = ""

    try:
        completed = runner(
            [config.curl_binary, "--config", "-"],
            input=curl_config,
            capture_output=True,
            text=True,
            timeout=config.total_timeout_seconds + 3,
            check=False,
            env=environment,
        )
    except FileNotFoundError:
        return _report(
            config,
            DiagnosticCode.UNKNOWN,
            ExitCode.CONFIG,
            "curl is not installed or cannot be executed",
            {},
            ("curl_binary_available",),
            ("Install curl and run the same command again.",),
        )
    except subprocess.TimeoutExpired:
        return _report(
            config,
            DiagnosticCode.TIMEOUT,
            ExitCode.TIMEOUT,
            "the diagnostic process exceeded its bounded timeout",
            {"curl_exit_code": 28},
            ("process_timeout",),
            (
                "Check whether the proxy host and port are reachable.",
                "Compare connect timeout with total timeout before increasing either limit.",
            ),
        )

    measurements = _parse_measurements(completed.stdout)
    http_code = _as_int(measurements.get("http_code"))
    diagnostic, exit_code, summary, checks, actions = classify_failure(
        completed.returncode,
        http_code,
    )
    observations: dict[str, object] = {
        "curl_exit_code": completed.returncode,
        "http_code": http_code,
        "remote_ip": _safe_remote_ip(measurements.get("remote_ip")),
        "time_namelookup_ms": _milliseconds(measurements.get("time_namelookup")),
        "time_connect_ms": _milliseconds(measurements.get("time_connect")),
        "time_tls_ms": _milliseconds(measurements.get("time_appconnect")),
        "time_first_byte_ms": _milliseconds(measurements.get("time_starttransfer")),
        "time_total_ms": _milliseconds(measurements.get("time_total")),
    }
    stderr = redact_text(completed.stderr).strip()
    if stderr:
        observations["error"] = stderr

    return _report(
        config,
        diagnostic,
        exit_code,
        summary,
        observations,
        checks,
        actions,
    )


def classify_failure(
    curl_exit_code: int,
    http_code: int,
) -> tuple[DiagnosticCode, ExitCode, str, tuple[str, ...], tuple[str, ...]]:
    if http_code == 407:
        return (
            DiagnosticCode.PROXY_AUTHENTICATION,
            ExitCode.PROXY_AUTHENTICATION,
            "the proxy rejected authentication",
            ("proxy_endpoint_reached", "proxy_credentials_rejected"),
            (
                "Verify username, password, IP allowlist and account status.",
                "Confirm that credentials belong to the selected proxy product and endpoint.",
            ),
        )
    if curl_exit_code in _DNS_EXIT_CODES:
        return (
            DiagnosticCode.DNS,
            ExitCode.DNS,
            "name resolution failed",
            ("dns_resolution",),
            (
                "Resolve the proxy hostname from the same runtime.",
                "For SOCKS, compare socks5:// with socks5h:// to control where DNS runs.",
            ),
        )
    if curl_exit_code == 28:
        return (
            DiagnosticCode.TIMEOUT,
            ExitCode.TIMEOUT,
            "the request exceeded a bounded timeout",
            ("connect_or_response_timeout",),
            (
                "Compare DNS, connect, TLS and first-byte timings.",
                "Check pool saturation before increasing timeout or retry counts.",
            ),
        )
    if curl_exit_code in _TLS_EXIT_CODES:
        return (
            DiagnosticCode.TLS,
            ExitCode.TLS,
            "TLS negotiation or certificate validation failed",
            ("tls_handshake",),
            (
                "Check the certificate chain, SNI and system clock.",
                "Do not disable certificate verification as a permanent fix.",
            ),
        )
    if curl_exit_code in _CONNECT_EXIT_CODES:
        return (
            DiagnosticCode.CONNECT,
            ExitCode.CONNECT,
            "the proxy endpoint could not be reached",
            ("tcp_connect",),
            (
                "Verify proxy host, port, firewall and egress policy.",
                "Test from the same network and runtime as the workload.",
            ),
        )
    if http_code == 429:
        return (
            DiagnosticCode.RATE_LIMITED,
            ExitCode.UPSTREAM,
            "the target or an intermediary applied rate limiting",
            ("http_429",),
            (
                "Reduce concurrency and inspect Retry-After.",
                "Measure success rate per proxy pool before adding retries.",
            ),
        )
    if http_code == 403:
        return (
            DiagnosticCode.ACCESS_DENIED,
            ExitCode.UPSTREAM,
            "the target denied the request",
            ("http_403",),
            (
                "Confirm that the use case and target access are authorized.",
                "Compare headers, session policy and exit geography with the agreed baseline.",
            ),
        )
    if curl_exit_code in _UPSTREAM_EXIT_CODES or http_code >= 500:
        return (
            DiagnosticCode.UPSTREAM,
            ExitCode.UPSTREAM,
            "the connection was interrupted or the upstream returned a server error",
            ("upstream_response",),
            (
                "Separate proxy-pool health from target availability.",
                "Use a bounded retry budget only for idempotent operations.",
            ),
        )
    if curl_exit_code == 0 and 200 <= http_code < 400:
        return (
            DiagnosticCode.OK,
            ExitCode.OK,
            "the proxy route completed successfully",
            ("proxy_connect", "tls_handshake", "http_response"),
            (
                "Repeat through the production pool and track p95 plus success rate.",
            ),
        )
    return (
        DiagnosticCode.UNKNOWN,
        ExitCode.UNKNOWN,
        "the request failed outside the known diagnostic classes",
        ("unclassified_failure",),
        (
            "Inspect the sanitized error and curl exit code.",
            "Reproduce with the same endpoint, runtime and timeout budget.",
        ),
    )


def _report(
    config: ProbeConfig,
    diagnostic: DiagnosticCode,
    exit_code: ExitCode,
    summary: str,
    observations: dict[str, object],
    checks: Sequence[str],
    actions: Sequence[str],
) -> ProbeReport:
    return ProbeReport(
        ok=diagnostic is DiagnosticCode.OK,
        diagnostic=diagnostic,
        exit_code=exit_code,
        summary=summary,
        proxy=safe_proxy(config.proxy_url),
        target_origin=safe_target(config.target_url),
        observations=observations,
        checks=tuple(checks),
        next_actions=tuple(actions),
    )


def _build_curl_config(config: ProbeConfig) -> str:
    parsed = urlsplit(config.proxy_url)
    username = config.proxy_username
    password = config.proxy_password
    if parsed.username is not None:
        username = unquote(parsed.username)
        password = unquote(parsed.password or "")
    proxy_without_credentials = urlunsplit(
        (
            parsed.scheme,
            f"{parsed.hostname}:{parsed.port}",
            "",
            "",
            "",
        )
    )
    values = [
        ("url", config.target_url),
        ("proxy", proxy_without_credentials),
        ("connect-timeout", f"{config.connect_timeout_seconds:g}"),
        ("max-time", f"{config.total_timeout_seconds:g}"),
        ("output", os.devnull),
        ("write-out", (
            "\\n"
            + _MARKER
            + "%{http_code}|%{remote_ip}|%{time_namelookup}|%{time_connect}|"
            "%{time_appconnect}|%{time_starttransfer}|%{time_total}"
        )),
    ]
    if username:
        values.append(("proxy-user", f"{username}:{password or ''}"))
    lines = [f'{name} = "{_curl_quote(value)}"' for name, value in values]
    lines.extend(["silent", "show-error", "location"])
    return "\n".join(lines) + "\n"


def _parse_measurements(stdout: str) -> dict[str, str]:
    marker_index = stdout.rfind(_MARKER)
    if marker_index < 0:
        return {}
    fields = stdout[marker_index + len(_MARKER) :].strip().split("|")
    names = (
        "http_code",
        "remote_ip",
        "time_namelookup",
        "time_connect",
        "time_appconnect",
        "time_starttransfer",
        "time_total",
    )
    return dict(zip(names, fields))


def _curl_quote(value: str) -> str:
    if any(character in value for character in "\r\n\0"):
        raise ConfigError("a curl config value contains an invalid character")
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_private_literal(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not address.is_global


def _as_int(value: str | None) -> int:
    try:
        return int(value or "0")
    except ValueError:
        return 0


def _milliseconds(value: str | None) -> float | None:
    try:
        return round(float(value or "") * 1000, 3)
    except ValueError:
        return None


def _safe_remote_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def render_report(report: ProbeReport, *, compact: bool = False) -> str:
    return json.dumps(
        report.to_dict(),
        ensure_ascii=False,
        indent=None if compact else 2,
        sort_keys=True,
    )
