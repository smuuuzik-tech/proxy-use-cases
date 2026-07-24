from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum, IntEnum
from typing import Any


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


class ExitCode(IntEnum):
    """Stable process exit codes for CI and automation."""

    HEALTHY = 0
    DEGRADED = 1
    FAILED = 2
    CONFIG_ERROR = 64
    INTERNAL_ERROR = 70


class ErrorCategory(str, Enum):
    PROXY_AUTH = "proxy_auth"
    TARGET_AUTH = "target_auth"
    DNS = "dns"
    CONNECT = "connect"
    TLS = "tls"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    TARGET_HTTP = "target_http"
    POLICY_REDIRECT = "policy_redirect"
    APPLICATION_RESPONSE = "application_response"
    TRANSPORT = "transport"


@dataclass(frozen=True)
class CheckResult:
    endpoint: str
    request_index: int
    success: bool
    status_code: int | None
    latency_ms: float
    attempts: int
    observed_ip: str | None
    error_category: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Report:
    schema_version: str
    generated_at: str
    status: HealthStatus
    exit_code: int
    summary: dict[str, Any]
    endpoints: list[dict[str, Any]]
    rotation: dict[str, Any]
    decision: dict[str, Any]
    config: dict[str, Any]
    results: list[CheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "status": self.status.value,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "endpoints": self.endpoints,
            "rotation": self.rotation,
            "decision": self.decision,
            "config": self.config,
            "results": [result.to_dict() for result in self.results],
        }
