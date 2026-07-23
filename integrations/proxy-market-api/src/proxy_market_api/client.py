from __future__ import annotations

import json as jsonlib
import math
import re
from datetime import date
from ipaddress import ip_network
from typing import Any, Dict, Iterable, Mapping, Optional
from urllib.parse import quote, urlsplit

import httpx


DEFAULT_BASE_URL = "https://api.dashboard.proxy.market"
BILLABLE_OPERATION_CONFIRMATION = "CONFIRM_BILLABLE_OPERATION"
_PROXY_TYPES = frozenset({"resident", "mobile", "server"})
_LIST_TYPES = frozenset({"ipv4", "ipv4-shared", "ipv6", "all"})
_V2_DURATIONS = frozenset({1, 3, 5, 7, 10, 14, 20, 30, 60, 90, 180, 360})
_LEGACY_DURATIONS = frozenset({30, 60, 90, 180, 360})


class ProxyMarketConfigurationError(ValueError):
    """The local request configuration is invalid."""


class ProxyMarketTransportError(RuntimeError):
    """The API could not be reached or did not return JSON."""


class ProxyMarketAmbiguousMutationError(ProxyMarketTransportError):
    """A mutation may have reached the API and must not be retried blindly."""

    retry_safe = False

    def __init__(self, *, operation: str, reason: str) -> None:
        self.operation = operation
        super().__init__(
            f"{operation} has an ambiguous result ({reason}); "
            "do not retry before reconciliation"
        )


class ProxyMarketApiError(RuntimeError):
    """The API returned a non-successful HTTP status."""

    def __init__(
        self,
        *,
        operation: str,
        status_code: int,
        message: str,
        code: Any = None,
    ) -> None:
        self.operation = operation
        self.status_code = status_code
        self.code = code
        super().__init__(
            f"{operation} failed with HTTP {status_code}: {message}"
        )


class ProxyMarketBusinessError(RuntimeError):
    """HTTP succeeded, but the API reported a failed business operation."""

    def __init__(self, *, operation: str, message: str, code: Any = None) -> None:
        self.operation = operation
        self.code = code
        suffix = f" ({code})" if code is not None else ""
        super().__init__(f"{operation} was rejected: {message}{suffix}")


class ProxyMarketClient:
    """Small defensive client for the public Proxy.Market API v1.1.

    The upstream contract places ``api_key`` in the URL path. This client never
    includes a request URL in its own exceptions or repr, but callers must still
    redact URL paths in HTTP, proxy, APM and ingress logs.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 15.0,
        transport: Optional[httpx.BaseTransport] = None,
        allow_insecure_base_url: bool = False,
        allow_custom_base_url: bool = False,
        trust_environment: bool = False,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProxyMarketConfigurationError("api_key must be a non-empty string")
        normalized_base_url = base_url.rstrip("/")
        parsed_base_url = urlsplit(normalized_base_url)
        if not parsed_base_url.netloc or parsed_base_url.scheme not in ("http", "https"):
            raise ProxyMarketConfigurationError("base_url must be an HTTP(S) origin")
        if parsed_base_url.username or parsed_base_url.password:
            raise ProxyMarketConfigurationError("base_url must not contain credentials")
        if parsed_base_url.path not in ("", "/") or parsed_base_url.query:
            raise ProxyMarketConfigurationError(
                "base_url must not contain a path or query"
            )
        if parsed_base_url.fragment:
            raise ProxyMarketConfigurationError("base_url must not contain a fragment")
        if normalized_base_url != DEFAULT_BASE_URL and not allow_custom_base_url:
            raise ProxyMarketConfigurationError(
                "custom base_url requires allow_custom_base_url=True"
            )
        if not allow_insecure_base_url and parsed_base_url.scheme != "https":
            raise ProxyMarketConfigurationError(
                "base_url must use HTTPS unless allow_insecure_base_url=True"
            )
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or timeout_seconds > 120
        ):
            raise ProxyMarketConfigurationError(
                "timeout_seconds must be finite and from 0 to 120"
            )
        if (
            not isinstance(max_response_bytes, int)
            or isinstance(max_response_bytes, bool)
            or max_response_bytes < 1
            or max_response_bytes > 10_000_000
        ):
            raise ProxyMarketConfigurationError(
                "max_response_bytes must be from 1 to 10000000"
            )

        self._api_key = api_key
        self._encoded_api_key = quote(api_key, safe="")
        self._base_url = normalized_base_url
        self._max_response_bytes = max_response_bytes
        self._client = httpx.Client(
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
            trust_env=trust_environment,
            headers={
                "Accept": "application/json",
                "User-Agent": "proxy-market-control-plane/0.1",
            },
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self._base_url!r}, "
            "api_key=<redacted>)"
        )

    def __enter__(self) -> "ProxyMarketClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def balance(self) -> Dict[str, Any]:
        return self._request("GET", "/dev-api/balance/{api_key}", operation="balance")

    def list_proxies(
        self,
        *,
        tariff: str = "all",
        proxy_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 10,
        sort: int = 0,
        package_id: Optional[int] = None,
        order_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return proxies, including credentials present in the upstream response."""
        if tariff not in _LIST_TYPES:
            raise ProxyMarketConfigurationError(
                f"tariff must be one of {sorted(_LIST_TYPES)}"
            )
        if proxy_type is not None and proxy_type not in _PROXY_TYPES:
            raise ProxyMarketConfigurationError(
                f"proxy_type must be one of {sorted(_PROXY_TYPES)}"
            )
        if proxy_type is None and package_id is None:
            raise ProxyMarketConfigurationError(
                "proxy_type is required when package_id is not provided"
            )
        self._require_positive("page", page)
        self._require_positive("page_size", page_size)
        if package_id is not None:
            self._require_positive("package_id", package_id)
        if order_id is not None:
            self._require_positive("order_id", order_id)
        if page_size > 1_000:
            raise ProxyMarketConfigurationError("page_size must not exceed 1000")
        if isinstance(sort, bool) or not isinstance(sort, int) or sort not in (0, 1):
            raise ProxyMarketConfigurationError("sort must be 0 or 1")

        body = self._without_none(
            {
                "type": tariff,
                "proxy_type": proxy_type,
                "page": page,
                "page_size": page_size,
                "sort": sort,
                "package_id": package_id,
                "order_id": order_id,
            }
        )
        return self._request(
            "POST",
            "/dev-api/list/{api_key}",
            operation="list_proxies",
            json=body,
        )

    def products(
        self,
        *,
        country: Optional[str] = None,
        product_type: Optional[str] = None,
        proxy_type: Optional[str] = None,
        duration: Optional[int] = None,
        page: Optional[int] = None,
        per_page: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._validate_optional_pagination(page, per_page)
        if country is not None:
            self._require_nonempty_string("country", country)
        if product_type is not None:
            self._require_nonempty_string("product_type", product_type)
        if proxy_type is not None:
            self._require_nonempty_string("proxy_type", proxy_type)
        if duration is not None:
            self._require_positive("duration", duration)
        params = self._without_none(
            {
                "country": country,
                "productType": product_type,
                "proxyType": proxy_type,
                "duration": duration,
                "page": page,
                "perPage": per_page,
            }
        )
        return self._request(
            "GET",
            "/dev-api/v2/products/{api_key}",
            operation="products",
            params=params,
        )

    def purposes(self) -> Dict[str, Any]:
        return self._request(
            "GET", "/dev-api/v2/purposes/{api_key}", operation="purposes"
        )

    def traffic_prices(self) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/dev-api/v2/traffic-prices/{api_key}",
            operation="traffic_prices",
        )

    def packages(
        self, *, page: Optional[int] = None, per_page: Optional[int] = None
    ) -> Dict[str, Any]:
        self._validate_optional_pagination(page, per_page)
        return self._request(
            "GET",
            "/dev-api/v2/packages/{api_key}",
            operation="packages",
            params=self._without_none({"page": page, "perPage": per_page}),
        )

    def traffic_statistics(
        self,
        *,
        proxy_type: str,
        date_from: str,
        date_to: str,
        package_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if proxy_type not in _PROXY_TYPES:
            raise ProxyMarketConfigurationError(
                f"proxy_type must be one of {sorted(_PROXY_TYPES)}"
            )
        parsed_from = self._parse_iso_date("date_from", date_from)
        parsed_to = self._parse_iso_date("date_to", date_to)
        if parsed_from > parsed_to:
            raise ProxyMarketConfigurationError(
                "date_from must not be later than date_to"
            )
        if package_id is not None:
            self._require_positive("package_id", package_id)
        return self._request(
            "GET",
            "/dev-api/v2/traffic-statistics/{api_key}",
            operation="traffic_statistics",
            params=self._without_none(
                {
                    "proxy_type": proxy_type,
                    "package_id": package_id,
                    "from": date_from,
                    "to": date_to,
                }
            ),
        )

    def package_countries(self) -> Dict[str, Any]:
        return self._request(
            "GET",
            "/dev-api/v2/package/countries/{api_key}",
            operation="package_countries",
        )

    def package_regions_and_cities(self, *, country: str) -> Dict[str, Any]:
        self._require_nonempty_string("country", country)
        return self._request(
            "GET",
            "/dev-api/v2/package/regions-and-cities/{api_key}",
            operation="package_regions_and_cities",
            params={"country": country},
        )

    def buy_proxies_v2(
        self,
        *,
        product_id: int,
        duration: int,
        count: int,
        promo_code: Optional[str] = None,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_billable_confirmation(confirmation)
        self._require_positive("product_id", product_id)
        self._require_positive("count", count)
        self._require_int_in("duration", duration, _V2_DURATIONS)
        return self._request(
            "POST",
            "/dev-api/v2/buy-proxies/{api_key}",
            operation="buy_proxies_v2",
            json=self._without_none(
                {
                    "productId": product_id,
                    "duration": duration,
                    "count": count,
                    "promoCode": promo_code,
                }
            ),
            mutation=True,
            require_success=True,
            required_positive_fields=("order_id",),
        )

    def buy_proxies_legacy(
        self,
        *,
        count: int,
        duration: int,
        proxy_version: int,
        country: str = "ru",
        speed: Optional[int] = None,
        promo_code: Optional[str] = None,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_billable_confirmation(confirmation)
        self._require_positive("count", count)
        self._require_int_in("duration", duration, _LEGACY_DURATIONS)
        self._require_int_in("proxy_version", proxy_version, frozenset({100, 101}))
        if country != "ru":
            raise ProxyMarketConfigurationError(
                "legacy country must be 'ru' according to the published schema"
            )
        if speed is not None:
            self._require_int_in("speed", speed, frozenset({1, 2, 3}))
            if proxy_version != 101:
                raise ProxyMarketConfigurationError(
                    "speed is only documented for legacy IPv6 purchases"
                )
        return self._request(
            "POST",
            "/dev-api/buy-proxy/{api_key}",
            operation="buy_proxies_legacy",
            json={
                "PurchaseBilling": self._without_none(
                    {
                        "count": count,
                        "duration": duration,
                        "type": proxy_version,
                        "country": country,
                        "promocode": promo_code,
                        "speed": speed,
                    }
                )
            },
            mutation=True,
            require_success=True,
            required_positive_fields=("order_id",),
        )

    def prolong_proxies(
        self,
        *,
        duration: int,
        proxy_ids: Iterable[int],
        promo_code: Optional[str] = None,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_billable_confirmation(confirmation)
        self._require_int_in("duration", duration, _LEGACY_DURATIONS)
        ids = list(proxy_ids)
        if not ids or any(
            not isinstance(item, int) or isinstance(item, bool) or item <= 0
            for item in ids
        ):
            raise ProxyMarketConfigurationError(
                "proxy_ids must contain positive integers"
            )
        if len(ids) != len(set(ids)):
            raise ProxyMarketConfigurationError("proxy_ids must not contain duplicates")
        return self._request(
            "POST",
            "/dev-api/prolong/{api_key}",
            operation="prolong_proxies",
            json={
                "ProlongationForm": self._without_none(
                    {
                        "duration": duration,
                        "promocode": promo_code,
                        "proxies": ",".join(str(item) for item in ids),
                    }
                )
            },
            mutation=True,
            require_success=True,
        )

    def buy_traffic(
        self,
        *,
        traffic_gb: int,
        promo_code: Optional[str] = None,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_billable_confirmation(confirmation)
        self._require_positive("traffic_gb", traffic_gb)
        return self._request(
            "POST",
            "/dev-api/v2/buy-traffic/{api_key}",
            operation="buy_traffic",
            json=self._without_none(
                {"traffic": traffic_gb, "promoCode": promo_code}
            ),
            mutation=True,
            require_success=True,
        )

    def create_package_proxy(
        self,
        *,
        package_id: int,
        country: str,
        rotation: int,
        region_id: Optional[int] = None,
        city_id: Optional[int] = None,
        ip_auth: Optional[str] = None,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_billable_confirmation(confirmation)
        self._require_positive("package_id", package_id)
        self._require_nonempty_string("country", country)
        if not isinstance(rotation, int) or isinstance(rotation, bool):
            raise ProxyMarketConfigurationError("rotation must be an integer")
        if rotation < -1 or rotation > 60:
            raise ProxyMarketConfigurationError("rotation must be from -1 to 60")
        if region_id is not None:
            self._require_positive("region_id", region_id)
        if city_id is not None:
            self._require_positive("city_id", city_id)
        if ip_auth is not None:
            self._validate_ip_auth(ip_auth)
        return self._request(
            "POST",
            "/dev-api/v2/package/create-proxy/{api_key}",
            operation="create_package_proxy",
            json=self._without_none(
                {
                    "packageId": package_id,
                    "country": country,
                    "rotation": rotation,
                    "regionId": region_id,
                    "cityId": city_id,
                    "ipAuth": ip_auth,
                }
            ),
            mutation=True,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Mapping[str, Any]] = None,
        mutation: bool = False,
        require_success: bool = False,
        required_positive_fields: tuple = (),
    ) -> Dict[str, Any]:
        url = f"{self._base_url}{path.format(api_key=self._encoded_api_key)}"
        transport_error = None
        try:
            with self._client.stream(
                method,
                url,
                params=params,
                json=json,
            ) as response:
                content = self._read_limited(response, operation)
                status_code = response.status_code
                reason_phrase = response.reason_phrase
        except httpx.TimeoutException:
            if mutation:
                transport_error = ProxyMarketAmbiguousMutationError(
                    operation=operation, reason="timeout"
                )
            else:
                transport_error = ProxyMarketTransportError(
                    f"{operation} timed out; request URL was suppressed"
                )
        except httpx.RequestError:
            if mutation:
                transport_error = ProxyMarketAmbiguousMutationError(
                    operation=operation, reason="transport failure"
                )
            else:
                transport_error = ProxyMarketTransportError(
                    f"{operation} transport failed; request URL was suppressed"
                )
        if transport_error is not None:
            raise transport_error

        payload = self._decode_payload(content, operation)
        if status_code < 200 or status_code >= 300:
            raise ProxyMarketApiError(
                operation=operation,
                status_code=status_code,
                message=self._message(payload, reason_phrase),
                code=self._redact_value(payload.get("code")),
            )
        success = payload.get("success")
        code = payload.get("code")
        if (
            ("success" in payload and success is not True)
            or code == "LOW_BALANCE"
            or (require_success and success is not True)
            or (require_success and code not in (None, ""))
        ):
            raise ProxyMarketBusinessError(
                operation=operation,
                message=self._message(payload, "business operation failed"),
                code=self._redact_value(payload.get("code")),
            )
        for field in required_positive_fields:
            value = payload.get(field)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ProxyMarketBusinessError(
                    operation=operation,
                    message=f"response did not confirm a valid {field}",
                    code=self._redact_value(code),
                )
        return payload

    def _read_limited(self, response: httpx.Response, operation: str) -> bytes:
        chunks = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise ProxyMarketTransportError(
                    f"{operation} response exceeded max_response_bytes"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _decode_payload(self, content: bytes, operation: str) -> Dict[str, Any]:
        if not content:
            return {}
        decode_failed = False
        try:
            payload = jsonlib.loads(content)
        except (UnicodeDecodeError, ValueError):
            decode_failed = True
        if decode_failed:
            raise ProxyMarketTransportError(
                f"{operation} returned a non-JSON response; request URL was suppressed"
            )
        if not isinstance(payload, dict):
            raise ProxyMarketTransportError(
                f"{operation} returned a non-object JSON response"
            )
        return payload

    def _message(self, payload: Mapping[str, Any], fallback: str) -> str:
        raw = payload.get("message") or payload.get("error") or fallback
        return str(self._redact_value(raw))

    def _redact_value(self, raw: Any) -> Any:
        if raw is None or not isinstance(raw, str):
            return raw
        result = raw.replace(self._api_key, "<redacted>")
        return re.sub(
            re.escape(self._encoded_api_key),
            "<redacted>",
            result,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _without_none(values: Mapping[str, Any]) -> Dict[str, Any]:
        return {key: value for key, value in values.items() if value is not None}

    @staticmethod
    def _require_positive(name: str, value: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ProxyMarketConfigurationError(
                f"{name} must be a positive integer"
            )

    @staticmethod
    def _require_nonempty_string(name: str, value: str) -> None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        ):
            raise ProxyMarketConfigurationError(
                f"{name} must be a non-empty string without surrounding whitespace"
            )

    @staticmethod
    def _require_int_in(name: str, value: int, allowed: frozenset) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value not in allowed
        ):
            raise ProxyMarketConfigurationError(
                f"{name} must be one of {sorted(allowed)}"
            )

    @classmethod
    def _validate_optional_pagination(
        cls, page: Optional[int], per_page: Optional[int]
    ) -> None:
        if page is not None:
            cls._require_positive("page", page)
        if per_page is not None:
            cls._require_positive("per_page", per_page)
            if per_page > 1_000:
                raise ProxyMarketConfigurationError(
                    "per_page must not exceed 1000"
                )

    @staticmethod
    def _validate_ip_auth(value: str) -> None:
        ProxyMarketClient._require_nonempty_string("ip_auth", value)
        entries = value.split(",")
        if len(entries) > 32 or any(not entry for entry in entries):
            raise ProxyMarketConfigurationError(
                "ip_auth must contain 1 to 32 comma-separated IPs or subnets"
            )
        try:
            for entry in entries:
                if entry != entry.strip():
                    raise ValueError
                ip_network(entry, strict=False)
        except ValueError as exc:
            raise ProxyMarketConfigurationError(
                "ip_auth must contain valid comma-separated IPs or subnets"
            ) from exc

    @staticmethod
    def _parse_iso_date(name: str, value: str) -> date:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ProxyMarketConfigurationError(
                f"{name} must use YYYY-MM-DD"
            ) from exc

    @staticmethod
    def _require_billable_confirmation(confirmation: Optional[str]) -> None:
        if confirmation != BILLABLE_OPERATION_CONFIRMATION:
            raise ProxyMarketConfigurationError(
                "billable or state-changing operation requires confirmation="
                f"{BILLABLE_OPERATION_CONFIRMATION!r}"
            )
