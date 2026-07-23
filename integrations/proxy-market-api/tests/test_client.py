import json

import httpx
import pytest

from proxy_market_api import (
    BILLABLE_OPERATION_CONFIRMATION,
    ProxyMarketAmbiguousMutationError,
    ProxyMarketApiError,
    ProxyMarketBusinessError,
    ProxyMarketClient,
    ProxyMarketConfigurationError,
    ProxyMarketTransportError,
)


def client_with(handler, api_key="top/secret?value"):
    return ProxyMarketClient(api_key, transport=httpx.MockTransport(handler))


def json_response(status_code, payload):
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        json=payload,
    )


def test_repr_does_not_expose_api_key():
    client = client_with(lambda request: json_response(200, {}))
    try:
        assert "top/secret?value" not in repr(client)
        assert "<redacted>" in repr(client)
    finally:
        client.close()


def test_balance_encodes_api_key_in_required_path():
    seen = {}

    def handler(request):
        seen["raw_path"] = request.url.raw_path
        return json_response(200, {"balance": 125.5})

    with client_with(handler) as client:
        assert client.balance() == {"balance": 125.5}

    assert b"top%2Fsecret%3Fvalue" in seen["raw_path"]


def test_http_error_redacts_api_key_from_message():
    def handler(request):
        return json_response(
            403, {"message": "invalid top/secret?value", "code": 0}
        )

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketApiError) as raised:
            client.balance()

    assert raised.value.status_code == 403
    assert raised.value.code == 0
    assert "top/secret?value" not in str(raised.value)
    assert "<redacted>" in str(raised.value)


def test_http_error_redacts_url_encoded_api_key_from_message():
    def handler(request):
        return json_response(
            403, {"message": "invalid top%2fsecret%3fvalue", "code": 0}
        )

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketApiError) as raised:
            client.balance()

    assert "top%2fsecret%3fvalue" not in str(raised.value)
    assert "<redacted>" in str(raised.value)


def test_http_error_redacts_mixed_case_percent_encoding():
    def handler(request):
        return json_response(403, {"message": "invalid top%2fsecret%3Fvalue"})

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketApiError) as raised:
            client.balance()

    assert "top%2fsecret%3Fvalue" not in str(raised.value)
    assert "<redacted>" in str(raised.value)


def test_non_json_error_does_not_include_request_url():
    def handler(request):
        return httpx.Response(502, text="upstream failed")

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketTransportError) as raised:
            client.balance()

    assert "top/secret?value" not in str(raised.value)
    assert "non-JSON" in str(raised.value)


def test_transport_error_suppresses_underlying_url():
    def handler(request):
        raise httpx.ConnectError("failed", request=request)

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketTransportError) as raised:
            client.balance()

    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "top/secret?value" not in str(raised.value)


def test_business_failure_is_not_treated_as_success():
    def handler(request):
        return json_response(
            200,
            {
                "success": False,
                "message": "Insufficient funds",
                "code": "LOW_BALANCE",
            },
        )

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketBusinessError) as raised:
            client.buy_traffic(
                traffic_gb=10,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )

    assert raised.value.code == "LOW_BALANCE"


def test_low_balance_code_without_success_flag_is_failure():
    def handler(request):
        return json_response(200, {"code": "LOW_BALANCE", "balance": 0})

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketBusinessError) as raised:
            client.buy_traffic(
                traffic_gb=10,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )

    assert raised.value.code == "LOW_BALANCE"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"success": 0},
        {"success": "false"},
        {"success": True, "code": "UNKNOWN_CODE"},
    ],
)
def test_mutation_responses_fail_closed(payload):
    def handler(request):
        return json_response(200, payload)

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketBusinessError):
            client.buy_traffic(
                traffic_gb=10,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


def test_purchase_requires_positive_order_id():
    def handler(request):
        return json_response(200, {"success": True})

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketBusinessError):
            client.buy_proxies_v2(
                product_id=1,
                duration=30,
                count=1,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


def test_business_code_is_redacted_if_upstream_echoes_secret():
    def handler(request):
        return json_response(
            200,
            {
                "success": False,
                "message": "rejected",
                "code": "top/secret?value",
            },
        )

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketBusinessError) as raised:
            client.buy_traffic(
                traffic_gb=10,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )

    assert raised.value.code == "<redacted>"
    assert "top/secret?value" not in str(raised.value)


def test_list_proxies_uses_documented_request_shape():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return json_response(200, {"success": True, "list": {"data": []}})

    with client_with(handler) as client:
        client.list_proxies(
            tariff="ipv4",
            proxy_type="server",
            page=2,
            page_size=50,
            order_id=71,
        )

    assert seen == {
        "method": "POST",
        "body": {
            "type": "ipv4",
            "proxy_type": "server",
            "page": 2,
            "page_size": 50,
            "sort": 0,
            "order_id": 71,
        },
    }


def test_list_proxies_requires_proxy_type_without_package():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.list_proxies()


def test_products_maps_python_names_to_api_query_names():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return json_response(200, {"data": [], "metadata": {}})

    with client_with(handler) as client:
        client.products(
            country="ru",
            product_type="server",
            proxy_type="ipv4",
            per_page=25,
        )

    assert seen == {
        "country": "ru",
        "productType": "server",
        "proxyType": "ipv4",
        "perPage": "25",
    }


def test_pagination_is_bounded_locally():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.products(per_page=1001)
        with pytest.raises(ProxyMarketConfigurationError):
            client.packages(page=0)


def test_statistics_validates_date_order():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.traffic_statistics(
                proxy_type="resident",
                date_from="2026-06-02",
                date_to="2026-06-01",
            )


def test_statistics_sends_documented_query():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return json_response(200, {"data": [], "total": 0})

    with client_with(handler) as client:
        client.traffic_statistics(
            proxy_type="mobile",
            package_id=42,
            date_from="2026-06-01",
            date_to="2026-06-30",
        )

    assert seen == {
        "proxy_type": "mobile",
        "package_id": "42",
        "from": "2026-06-01",
        "to": "2026-06-30",
    }


@pytest.mark.parametrize(
    "method_name,kwargs",
    [
        ("buy_proxies_v2", {"product_id": 1, "duration": 30, "count": 2}),
        ("buy_traffic", {"traffic_gb": 10}),
        ("prolong_proxies", {"duration": 30, "proxy_ids": [1, 2]}),
        (
            "create_package_proxy",
            {"package_id": 1, "country": "ru", "rotation": 0},
        ),
    ],
)
def test_mutations_require_explicit_confirmation(method_name, kwargs):
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            getattr(client, method_name)(**kwargs)


def test_buy_proxies_v2_sends_documented_payload():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return json_response(
            200, {"success": True, "balance": 100, "order_id": 77}
        )

    with client_with(handler) as client:
        result = client.buy_proxies_v2(
            product_id=123,
            duration=30,
            count=5,
            confirmation=BILLABLE_OPERATION_CONFIRMATION,
        )

    assert seen == {"productId": 123, "duration": 30, "count": 5}
    assert result["order_id"] == 77


def test_v2_duration_rejects_boolean_even_though_bool_is_an_int():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.buy_proxies_v2(
                product_id=1,
                duration=True,
                count=1,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 1, "duration": 30, "proxy_version": 100, "country": "us"},
        {
            "count": 1,
            "duration": 30,
            "proxy_version": 100,
            "speed": 1,
        },
        {
            "count": 1,
            "duration": True,
            "proxy_version": 101,
        },
    ],
)
def test_legacy_purchase_enforces_published_contract(kwargs):
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.buy_proxies_legacy(
                **kwargs,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


def test_prolong_converts_ids_to_comma_separated_string():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return json_response(200, {"success": True})

    with client_with(handler) as client:
        client.prolong_proxies(
            duration=60,
            proxy_ids=[3, 8, 13],
            confirmation=BILLABLE_OPERATION_CONFIRMATION,
        )

    assert seen["ProlongationForm"]["proxies"] == "3,8,13"


def test_prolong_rejects_boolean_proxy_id():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.prolong_proxies(
                duration=30,
                proxy_ids=[True],
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


def test_prolong_rejects_duplicate_proxy_ids():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.prolong_proxies(
                duration=30,
                proxy_ids=[1, 1],
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


@pytest.mark.parametrize("rotation", [-2, 61])
def test_create_package_proxy_validates_rotation(rotation):
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.create_package_proxy(
                package_id=1,
                country="ru",
                rotation=rotation,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


def test_create_package_proxy_rejects_boolean_rotation():
    with client_with(lambda request: json_response(200, {})) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.create_package_proxy(
                package_id=1,
                country="ru",
                rotation=True,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"country": " ru "},
        {"region_id": -1},
        {"city_id": True},
        {"ip_auth": "not-an-ip"},
        {"ip_auth": "192.0.2.1, 198.51.100.0/24"},
    ],
)
def test_create_package_proxy_validates_sensitive_inputs(kwargs):
    request = {"package_id": 1, "country": "ru", "rotation": 0}
    request.update(kwargs)
    with client_with(lambda incoming: httpx.Response(200)) as client:
        with pytest.raises(ProxyMarketConfigurationError):
            client.create_package_proxy(
                **request,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )


def test_empty_success_response_is_supported_for_create_proxy():
    def handler(request):
        return httpx.Response(200)

    with client_with(handler) as client:
        assert (
            client.create_package_proxy(
                package_id=1,
                country="ru",
                rotation=-1,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )
            == {}
        )


def test_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://unexpected.example/collect"},
            json={"message": "redirect"},
        )

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketApiError) as raised:
            client.balance()

    assert raised.value.status_code == 302
    assert len(calls) == 1


def test_response_body_is_bounded():
    def handler(request):
        return httpx.Response(200, content=b'{"data":"' + (b"x" * 100) + b'"}')

    client = ProxyMarketClient(
        "secret",
        transport=httpx.MockTransport(handler),
        max_response_bytes=50,
    )
    with client:
        with pytest.raises(ProxyMarketTransportError) as raised:
            client.balance()

    assert "max_response_bytes" in str(raised.value)


def test_mutation_transport_error_is_explicitly_ambiguous_and_not_retry_safe():
    def handler(request):
        raise httpx.ConnectError("failed", request=request)

    with client_with(handler) as client:
        with pytest.raises(ProxyMarketAmbiguousMutationError) as raised:
            client.buy_traffic(
                traffic_gb=1,
                confirmation=BILLABLE_OPERATION_CONFIRMATION,
            )

    assert raised.value.retry_safe is False
    assert raised.value.operation == "buy_traffic"
    assert raised.value.__context__ is None
    assert "do not retry" in str(raised.value)


def test_plain_http_base_url_is_rejected_by_default():
    with pytest.raises(ProxyMarketConfigurationError):
        ProxyMarketClient("secret", base_url="http://example.test")


def test_custom_https_base_url_requires_explicit_opt_in():
    with pytest.raises(ProxyMarketConfigurationError):
        ProxyMarketClient("secret", base_url="https://staging.example.test")

    client = ProxyMarketClient(
        "secret",
        base_url="https://staging.example.test",
        allow_custom_base_url=True,
        transport=httpx.MockTransport(lambda request: json_response(200, {})),
    )
    client.close()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://user:password@example.test",
        "https://example.test/unexpected-path",
        "https://example.test?secret=value",
        "https://example.test#fragment",
    ],
)
def test_base_url_must_be_a_clean_origin(base_url):
    with pytest.raises(ProxyMarketConfigurationError):
        ProxyMarketClient("secret", base_url=base_url)


@pytest.mark.parametrize("timeout_seconds", [True, 0, float("inf"), float("nan"), 121])
def test_timeout_must_be_finite_and_bounded(timeout_seconds):
    with pytest.raises(ProxyMarketConfigurationError):
        ProxyMarketClient("secret", timeout_seconds=timeout_seconds)
