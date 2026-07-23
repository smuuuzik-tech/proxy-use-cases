import pytest
import math
import httpx

from proxy_b2b_client import B2BHttpClient, ClientSettings, ConfigError


def test_config_builds_encoded_runtime_proxy_url_and_redacts_repr():
    settings = ClientSettings(
        proxy_url="http://proxy.example.test:8080",
        proxy_username="team@example.com",
        proxy_password="p@ss/word",
    )

    assert (
        settings.authenticated_proxy_url
        == "http://team%40example.com:p%40ss%2Fword@proxy.example.test:8080"
    )
    rendered = repr(settings)
    assert "team@example.com" not in rendered
    assert "p@ss/word" not in rendered
    assert "proxy.example.test" not in rendered


def test_inline_proxy_credentials_are_rejected_without_echoing_secret():
    secret = "do-not-print-me"

    with pytest.raises(ConfigError) as captured:
        ClientSettings(proxy_url=f"http://user:{secret}@proxy.example.test:8080")

    assert secret not in str(captured.value)
    assert "must not contain credentials" in str(captured.value)


@pytest.mark.parametrize(
    "env, expected_message",
    [
        ({}, "B2B_PROXY_URL is required"),
        (
            {"B2B_PROXY_URL": "ftp://proxy.example.test:21"},
            "must use http, https, socks5, or socks5h",
        ),
        (
            {
                "B2B_PROXY_URL": "http://proxy.example.test:8080",
                "B2B_PROXY_USERNAME": "user",
            },
            "must be set together",
        ),
        (
            {
                "B2B_PROXY_URL": "http://proxy.example.test:8080",
                "B2B_MAX_ATTEMPTS": "11",
            },
            "must be in range 1..10",
        ),
        (
            {
                "B2B_PROXY_URL": "http://proxy.example.test:8080",
                "B2B_FOLLOW_REDIRECTS": "true",
            },
            "Automatic redirects are disabled",
        ),
    ],
)
def test_invalid_environment_configuration(env, expected_message):
    with pytest.raises(ConfigError, match=expected_message):
        ClientSettings.from_env(env)


@pytest.mark.parametrize(
    "name,value",
    [
        ("B2B_TIMEOUT_CONNECT_SECONDS", str(math.nan)),
        ("B2B_TIMEOUT_READ_SECONDS", str(math.inf)),
        ("B2B_BACKOFF_MAX_SECONDS", "999999"),
        ("B2B_MAX_CONNECTIONS", "999999999"),
    ],
)
def test_non_finite_and_unbounded_values_are_rejected(name, value):
    with pytest.raises(ConfigError):
        ClientSettings.from_env(
            {
                "B2B_PROXY_URL": "http://proxy.example.test:8080",
                name: value,
            }
        )


def test_http_and_private_targets_require_explicit_opt_in():
    transport = httpx.MockTransport(
        lambda _request: pytest.fail("network should not be reached")
    )
    with B2BHttpClient(ClientSettings(proxy_url="http://proxy.example.test:8080"), transport=transport) as client:
        with pytest.raises(ConfigError, match="HTTPS"):
            client.request("GET", "http://api.example.test/data")
        with pytest.raises(ConfigError, match="PRIVATE_TARGETS"):
            client.request("GET", "https://169.254.169.254/latest/meta-data")
        with pytest.raises(ConfigError, match="PRIVATE_TARGETS"):
            client.request("GET", "https://100.100.100.200/latest/meta-data")
        with pytest.raises(ConfigError, match="PRIVATE_TARGETS"):
            client.request("GET", "https://224.0.0.1/")
        for target in ("https://localhost./", "https://127.1/", "https://2130706433/"):
            with pytest.raises(ConfigError, match="PRIVATE_TARGETS"):
                client.request("GET", target)
