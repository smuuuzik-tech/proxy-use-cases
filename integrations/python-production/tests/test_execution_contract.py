import json
from pathlib import Path

from proxy_b2b_client.execution import build_execution_contract


ROOT = Path(__file__).resolve().parents[3]


def fixture(name):
    return json.loads(
        (ROOT / "contracts" / "fixtures" / name).read_text(encoding="utf-8")
    )


def test_success_contract_matches_cross_language_fixture():
    contract = build_execution_contract(
        ok=True,
        attempts=1,
        elapsed_ms=184,
        status_code=200,
        response_bytes=17,
    )

    assert contract.to_dict() == fixture("execution-success.json")


def test_timeout_contract_matches_cross_language_fixture():
    contract = build_execution_contract(
        ok=False,
        attempts=3,
        elapsed_ms=1500,
        error_code="deadline_exceeded",
        estimated_cost_per_attempt=0.002,
        cost_currency="USD",
    )

    assert contract.to_dict() == fixture("execution-timeout.json")


def test_http_outcomes_produce_stable_next_actions():
    auth = build_execution_contract(
        ok=False,
        attempts=1,
        elapsed_ms=10,
        status_code=407,
        error_code="http_status",
    )
    rate_limit = build_execution_contract(
        ok=False,
        attempts=2,
        elapsed_ms=25,
        status_code=429,
        error_code="http_status",
    )
    not_found = build_execution_contract(
        ok=False,
        attempts=1,
        elapsed_ms=10,
        status_code=404,
        error_code="http_status",
    )

    assert auth.route.next_action == "review_policy_or_credentials"
    assert rate_limit.route.next_action == "review_retry_or_escalation"
    assert not_found.route.next_action == "review_http_response"
    assert auth.route.automatic_escalation is False
