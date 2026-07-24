import httpx
import pytest

from proxy_b2b_client import B2BHttpClient, ClientSettings, ConfigError, ProxyClient


def settings(**overrides):
    values = {
        "proxy_url": "http://proxy.example.test:8080",
        "max_attempts": 3,
        "backoff_base": 0.1,
        "backoff_max": 1.0,
        "backoff_jitter": 0.05,
    }
    values.update(overrides)
    return ClientSettings(**values)


def test_success_returns_structured_result_without_network():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"service": "ok"})

    with B2BHttpClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = client.request(
            "GET",
            "https://api.example.test/health?api_key=very-secret",
            request_id="req-001",
        )

    assert result.ok is True
    assert result.status_code == 200
    assert result.attempts == 1
    assert result.response.json() == {"service": "ok"}
    assert seen[0].headers["x-request-id"] == "req-001"
    assert "very-secret" not in str(result.to_dict())
    assert result.to_dict()["url"] == (
        "https://api.example.test/<redacted-path>?<redacted-query>"
    )


def test_personal_sdk_facade_starts_from_environment_and_supports_get():
    seen = []
    env = {
        "B2B_PROXY_URL": "http://proxy.example.test:8080",
        "B2B_PROXY_USERNAME": "client",
        "B2B_PROXY_PASSWORD": "private-password",
    }

    with ProxyClient.from_env(
        env,
        transport=httpx.MockTransport(
            lambda request: seen.append(request) or httpx.Response(200)
        ),
        sleep=lambda _: None,
    ) as client:
        result = client.get(
            "https://api.example.test/items?token=private",
            request_id="sdk-quickstart",
        )

    assert result.ok is True
    assert seen[0].headers["user-agent"] == "andrey-proxy-sdk/0.1.0"
    assert result.to_dict()["url"].endswith("?<redacted-query>")
    assert "private-password" not in str(result.to_dict())


def test_retryable_5xx_uses_bounded_exponential_backoff():
    statuses = iter([503, 502, 200])
    sleeps = []
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(next(statuses))

    with B2BHttpClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        jitter=lambda _low, _high: 0.025,
    ) as client:
        result = client.request("GET", "https://api.example.test/data")

    assert result.ok is True
    assert result.attempts == 3
    assert calls == 3
    assert sleeps == [0.125, 0.225]


def test_non_retryable_4xx_returns_after_first_attempt():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "invalid request"})

    with B2BHttpClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = client.request("GET", "https://api.example.test/data")

    assert result.ok is False
    assert result.status_code == 400
    assert result.error_code == "http_status"
    assert result.attempts == 1
    assert calls == 1


def test_non_idempotent_post_is_never_retried():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with B2BHttpClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = client.request(
            "POST",
            "https://api.example.test/jobs",
            json_data={"job": "sync"},
        )

    assert result.status_code == 503
    assert result.attempts == 1
    assert calls == 1


def test_transport_error_retries_idempotent_request_and_stays_sanitized():
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ProxyError(
            "unsafe diagnostic password=hunter2",
            request=request,
        )

    with B2BHttpClient(
        settings(max_attempts=2),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        jitter=lambda _low, _high: 0,
    ) as client:
        result = client.request("GET", "https://api.example.test/data")

    payload = result.to_dict()
    assert calls == 2
    assert result.attempts == 2
    assert result.error_code == "transport_error"
    assert payload["error"]["message"] == "Proxy connection failed."
    assert "hunter2" not in str(payload)


def test_retry_after_is_honored_within_budget():
    statuses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    sleeps = []

    with B2BHttpClient(
        settings(retry_after_max=5),
        transport=httpx.MockTransport(lambda _request: next(statuses)),
        sleep=sleeps.append,
        jitter=lambda _low, _high: 0,
    ) as client:
        result = client.request("GET", "https://api.example.test/data")

    assert result.ok is True
    assert sleeps == [2]


def test_retry_after_above_budget_stops_without_amplification():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "120"})

    with B2BHttpClient(
        settings(retry_after_max=5),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = client.request("GET", "https://api.example.test/data")

    assert calls == 1
    assert result.error_code == "retry_after_exceeds_budget"


def test_response_size_is_bounded():
    with B2BHttpClient(
        settings(max_response_bytes=4),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"12345")
        ),
        sleep=lambda _: None,
    ) as client:
        result = client.request("GET", "https://api.example.test/data")

    assert result.error_code == "response_too_large"
    assert result.response is None


def test_request_id_conflict_and_ambiguous_body_are_rejected():
    with B2BHttpClient(
        settings(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200)),
        sleep=lambda _: None,
    ) as client:
        with pytest.raises(ConfigError, match="conflicts"):
            client.request(
                "GET",
                "https://api.example.test/data",
                headers={"X-Request-ID": "wire-id"},
                request_id="result-id",
            )
        with pytest.raises(ConfigError, match="mutually exclusive"):
            client.request(
                "POST",
                "https://api.example.test/data",
                content="raw",
                json_data={"ignored": True},
            )


def test_put_retry_can_be_disabled_per_request():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with B2BHttpClient(
        settings(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    ) as client:
        result = client.request(
            "PUT",
            "https://api.example.test/data",
            retry=False,
        )

    assert calls == 1
    assert result.attempts == 1
