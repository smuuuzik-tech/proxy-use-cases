"""Typed, sanitized execution metadata shared across SDK implementations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple, cast

SchemaVersion = Literal["1.0"]
RouteName = Literal["http_proxy", "browser", "managed_unblocker", "ai_extraction"]
RouteReason = Literal["configured_http_proxy"]
NextAction = Literal[
    "complete",
    "none",
    "review_http_response",
    "review_policy_or_credentials",
    "review_response_limit",
    "review_retry_or_escalation",
]
ExecutionOutcome = Literal[
    "success",
    "http_error",
    "transport_error",
    "timeout",
    "aborted",
    "response_limit",
]
CostBasis = Literal["not_configured", "per_attempt"]
ManualCandidate = Literal["browser", "managed_unblocker", "ai_extraction"]

SCHEMA_VERSION: SchemaVersion = "1.0"
MANUAL_CANDIDATES: Tuple[ManualCandidate, ...] = (
    "browser",
    "managed_unblocker",
    "ai_extraction",
)


@dataclass(frozen=True)
class ExecutionRoute:
    selected: RouteName
    reason: RouteReason
    next_action: NextAction
    automatic_escalation: Literal[False]
    manual_candidates: List[ManualCandidate]


@dataclass(frozen=True)
class ExecutionQuality:
    outcome: ExecutionOutcome
    attempts: int
    retries: int
    elapsed_ms: int
    status_code: Optional[int]
    response_bytes: Optional[int]


@dataclass(frozen=True)
class ExecutionCost:
    basis: CostBasis
    currency: Optional[str]
    unit_cost: Optional[float]
    estimated_total: Optional[float]


@dataclass(frozen=True)
class ExecutionContract:
    """Versioned metadata suitable for logs, automation, and AI assistants."""

    schema_version: SchemaVersion
    route: ExecutionRoute
    quality: ExecutionQuality
    cost: ExecutionCost

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _outcome(
    *,
    ok: bool,
    status_code: Optional[int],
    error_code: Optional[str],
    error_kind: Optional[str],
) -> ExecutionOutcome:
    if ok:
        return "success"
    if error_kind in {
        "http_error",
        "transport_error",
        "timeout",
        "aborted",
        "response_limit",
    }:
        return cast(ExecutionOutcome, error_kind)
    if error_code == "response_too_large":
        return "response_limit"
    if error_code == "deadline_exceeded":
        return "timeout"
    if error_code == "transport_error":
        return "transport_error"
    if status_code is not None:
        return "http_error"
    return "transport_error"


def _next_action(
    *,
    outcome: str,
    status_code: Optional[int],
) -> NextAction:
    if outcome == "success":
        return "complete"
    if outcome == "aborted":
        return "none"
    if outcome == "response_limit":
        return "review_response_limit"
    if outcome in {"timeout", "transport_error"}:
        return "review_retry_or_escalation"
    if status_code in {401, 403, 407}:
        return "review_policy_or_credentials"
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return "review_retry_or_escalation"
    return "review_http_response"


def build_execution_contract(
    *,
    ok: bool,
    attempts: int,
    elapsed_ms: int,
    status_code: Optional[int] = None,
    response_bytes: Optional[int] = None,
    error_code: Optional[str] = None,
    error_kind: Optional[str] = None,
    estimated_cost_per_attempt: Optional[float] = None,
    cost_currency: Optional[str] = None,
) -> ExecutionContract:
    """Build the canonical contract without target, credentials, or raw errors."""

    outcome = _outcome(
        ok=ok,
        status_code=status_code,
        error_code=error_code,
        error_kind=error_kind,
    )
    if estimated_cost_per_attempt is None:
        cost = ExecutionCost(
            basis="not_configured",
            currency=None,
            unit_cost=None,
            estimated_total=None,
        )
    else:
        cost = ExecutionCost(
            basis="per_attempt",
            currency=cost_currency,
            unit_cost=estimated_cost_per_attempt,
            estimated_total=round(attempts * estimated_cost_per_attempt, 8),
        )

    return ExecutionContract(
        schema_version=SCHEMA_VERSION,
        route=ExecutionRoute(
            selected="http_proxy",
            reason="configured_http_proxy",
            next_action=_next_action(
                outcome=outcome,
                status_code=status_code,
            ),
            automatic_escalation=False,
            manual_candidates=list(MANUAL_CANDIDATES),
        ),
        quality=ExecutionQuality(
            outcome=outcome,
            attempts=attempts,
            retries=max(0, attempts - 1),
            elapsed_ms=elapsed_ms,
            status_code=status_code,
            response_bytes=response_bytes,
        ),
        cost=cost,
    )
