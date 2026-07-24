export const EXECUTION_SCHEMA_VERSION = "1.1";

const MANUAL_CANDIDATES = Object.freeze({
  http_proxy: Object.freeze([
    "browser",
    "managed_unblocker",
    "ai_extraction",
  ]),
  browser: Object.freeze(["managed_unblocker", "ai_extraction"]),
});

function executionOutcome({ ok, statusCode, errorKind }) {
  if (ok) return "success";
  if (errorKind === "response_limit") return "response_limit";
  if (errorKind === "timeout") return "timeout";
  if (errorKind === "aborted") return "aborted";
  if (errorKind === "transport") return "transport_error";
  if (statusCode != null) return "http_error";
  return "transport_error";
}

function nextAction(outcome, statusCode) {
  if (outcome === "success") return "complete";
  if (outcome === "aborted") return "none";
  if (outcome === "response_limit") return "review_response_limit";
  if (outcome === "timeout" || outcome === "transport_error") {
    return "review_retry_or_escalation";
  }
  if ([401, 403, 407].includes(statusCode)) {
    return "review_policy_or_credentials";
  }
  if (statusCode === 429 || statusCode >= 500) {
    return "review_retry_or_escalation";
  }
  return "review_http_response";
}

export function buildExecutionContract({
  ok,
  attempts,
  elapsedMs,
  statusCode = null,
  responseBytes = null,
  errorKind = null,
  estimatedCostPerAttempt = null,
  costCurrency = null,
  selectedRoute = "http_proxy",
  routeReason = "configured_http_proxy",
}) {
  const outcome = executionOutcome({ ok, statusCode, errorKind });
  const cost = estimatedCostPerAttempt == null
    ? {
        basis: "not_configured",
        currency: null,
        unit_cost: null,
        estimated_total: null,
      }
    : {
        basis: "per_attempt",
        currency: costCurrency,
        unit_cost: estimatedCostPerAttempt,
        estimated_total: Number((attempts * estimatedCostPerAttempt).toFixed(8)),
      };

  return {
    schema_version: EXECUTION_SCHEMA_VERSION,
    route: {
      selected: selectedRoute,
      reason: routeReason,
      next_action: nextAction(outcome, statusCode),
      automatic_escalation: false,
      manual_candidates: [...(MANUAL_CANDIDATES[selectedRoute] || [])],
    },
    quality: {
      outcome,
      attempts,
      retries: Math.max(0, attempts - 1),
      elapsed_ms: elapsedMs,
      status_code: statusCode,
      response_bytes: responseBytes,
    },
    cost,
  };
}
