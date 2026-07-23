# Proxy.Market API: безопасная B2B-интеграция

Независимый технический разбор публичного control-plane API и небольшой
Python-клиент для автоматизации. Основной репозиторий остаётся
провайдер-независимым; здесь показано, как изолировать особенности конкретного
API.

Основа разбора:

- [интерактивная документация](https://api.dashboard.proxy.market/docs);
- [OpenAPI 3.0, версия API 1.1](https://api.dashboard.proxy.market/openapi/openapi.yaml).

Актуальность сверки: 23 июля 2026 года. Перед production-внедрением повторно
сравните клиент с текущей OpenAPI-схемой.

## Что умеет API

Публичная схема описывает 14 операций:

| Контур | Чтение | Изменение состояния |
|---|---|---|
| Аккаунт и выданные прокси | баланс, список прокси | продление |
| Каталог | продукты, назначения | покупка прокси V2, legacy-покупка |
| Пакеты трафика | цены, пакеты, статистика | покупка трафика |
| География пакета | страны, регионы и города | создание прокси в пакете |

Это API управления ресурсами. Оно выдаёт и изменяет учётные сущности, но не
заменяет HTTP/SOCKS-подключение к уже полученному прокси.

Полная карта методов, полей и неоднозначностей схемы находится в
[техническом аудите](../../docs/PROXY-MARKET-API-REFERENCE.md).

## Главный риск: ключ находится в URL

Каждый endpoint содержит `{api_key}` в пути. Поэтому секрет может оказаться в:

- access-логах ingress, reverse proxy и WAF;
- APM-трассировках и отчётах об ошибках;
- HTTP debug-логах;
- истории shell или браузера;
- URL, случайно приложенном к тикету.

Клиент ниже не печатает URL в своих исключениях, скрывает ключ в `repr`,
не следует редиректам, не использует proxy-настройки окружения по умолчанию и
ограничивает размер ответа.
Однако он не может изменить upstream-контракт: реальный HTTP-запрос всё равно
содержит ключ в пути. В production необходимо маскировать весь сегмент после
`/dev-api/.../`, отключить HTTP debug-логирование и предусмотреть ротацию ключа.

Не передавайте настоящий ключ в issue, pull request, CI output или пример
конфигурации.

Если корпоративный egress требует `HTTPS_PROXY`, включайте
`trust_environment=True` только после проверки редактирования URL в его логах.

## Установка

```bash
cd integrations/proxy-market-api
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export PROXY_MARKET_API_KEY='получить-из-secret-manager'
```

## Безопасное чтение

```python
import os

from proxy_market_api import ProxyMarketClient


with ProxyMarketClient(os.environ["PROXY_MARKET_API_KEY"]) as api:
    balance = api.balance()
    products = api.products(
        country="ru",
        product_type="server",
        proxy_type="ipv4",
        per_page=50,
    )
    packages = api.packages(per_page=50)
    usage = api.traffic_statistics(
        proxy_type="server",
        date_from="2026-07-01",
        date_to="2026-07-23",
    )

print(
    {
        "balance_available": "balance" in balance,
        "products_found": len(products.get("data", [])),
        "packages_found": len(packages.get("data", [])),
        "traffic_bytes": usage.get("total"),
    }
)
```

Пример намеренно не выводит баланс, идентификаторы пакетов или данные прокси.
Нужные бизнес-метрики следует публиковать отдельно от сырого API-ответа.

## Получение выданных прокси

```python
with ProxyMarketClient(os.environ["PROXY_MARKET_API_KEY"]) as api:
    response = api.list_proxies(
        tariff="ipv4",
        proxy_type="server",
        page=1,
        page_size=100,
    )

for proxy in response.get("list", {}).get("data", []):
    # Не логируем login, password, attached_ip и change_ip_link.
    print(
        {
            "id": proxy.get("id"),
            "country": proxy.get("country"),
            "expires_at": proxy.get("expires_at"),
            "proxy_type": proxy.get("proxy_type"),
        }
    )
```

Ответ списка может содержать `login`, `password`, адреса, порты, привязанный IP
и ссылку ручной смены IP. Сырые ответы нельзя отправлять в обычные application
logs.

## Платные и изменяющие состояние операции

Клиент требует точную строку подтверждения:

```python
from proxy_market_api import (
    BILLABLE_OPERATION_CONFIRMATION,
    ProxyMarketClient,
)


with ProxyMarketClient(os.environ["PROXY_MARKET_API_KEY"]) as api:
    result = api.buy_proxies_v2(
        product_id=123,
        duration=30,
        count=5,
        confirmation=BILLABLE_OPERATION_CONFIRMATION,
    )
```

Это локальный предохранитель, а не серверная идемпотентность. В опубликованной
схеме не описан idempotency key, поэтому `buy_proxies_v2`, `buy_traffic`,
`prolong_proxies`, `buy_proxies_legacy` и `create_package_proxy` нельзя
автоматически повторять после timeout или неоднозначного сетевого сбоя.

Production-процесс для таких операций:

1. сохранить внутренний request ID и ожидаемое изменение;
2. получить явное бизнес-подтверждение;
3. отправить запрос ровно один раз;
4. при timeout не повторять покупку автоматически;
5. сверить баланс, список заказов или ресурсов доступными read-методами;
6. перед ручным повтором проверить, не выполнилась ли первая операция.

## Рекомендуемый B2B-поток

```mermaid
flowchart LR
    A["Secret manager"] --> B["API adapter"]
    B --> C["Каталог и цены"]
    C --> D["Внутренний approval"]
    D --> E["Покупка без auto-retry"]
    E --> F["order_id / пакет"]
    F --> G["Получение прокси"]
    G --> H["Vault или runtime secret"]
    H --> I["Workload через HTTP/SOCKS"]
    I --> J["Healthcheck, SLO и расход трафика"]
```

Control-plane и data-plane следует разделять:

- этот клиент управляет балансом, каталогом, заказами и пакетами;
- прикладной HTTP-клиент использует уже выданный proxy endpoint;
- доступ к покупке не нужен приложению, которое только отправляет трафик;
- секрет API и пароли прокси должны иметь разных потребителей и разные правила
  ротации.

## Ошибки

Клиент различает:

- `ProxyMarketConfigurationError` — запрос отклонён локально;
- `ProxyMarketTransportError` — timeout, сеть или не-JSON ответ;
- `ProxyMarketAmbiguousMutationError` — результат изменения состояния
  неизвестен; исключение содержит `retry_safe = False` и требует reconciliation;
- `ProxyMarketApiError` — HTTP-ошибка, например `403`;
- `ProxyMarketBusinessError` — HTTP `2xx`, но `success: false`, например
  `LOW_BALANCE`.

По одной только HTTP-семантике нельзя считать покупку успешной. Платные методы
работают fail-closed: требуют буквальное `success: true`, не принимают
непустой business code и проверяют `order_id` там, где он описан контрактом.
Для create-proxy допускается документированный пустой ответ, после чего ресурс
нужно подтвердить повторным чтением пакета.

## Проверка без настоящего API

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

Тесты используют `httpx.MockTransport`: они не обращаются к сервису, не требуют
ключа и не выполняют покупок.

## Что уточнить у провайдера до production

- лимиты запросов, ответ `429` и правила backoff;
- серверную идемпотентность или способ безопасной сверки покупок;
- валюту, округление и точность денежных значений;
- максимальные `page`/`perPage` и период статистики;
- форматы дат, timezone и стабильность полей;
- SLA, request ID, changelog и правила вывода версий;
- возможность передавать API key в заголовке вместо URL.
