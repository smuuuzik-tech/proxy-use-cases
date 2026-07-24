# Andrey Proxy SDK для Python

Личная provider-neutral разработка Андрея Малышева для быстрой и безопасной
интеграции прокси в Python-сервисы клиентов. SDK не требует API конкретного
поставщика: ему достаточно стандартного HTTP(S)- или SOCKS-адреса прокси.

Провайдер-независимый синхронный Python/HTTPX-клиент для корпоративных
интеграций, мониторинга и разрешённых задач с публичными данными. Это рабочий
пример уровня 2/3: переиспользуемый connection pool, ограниченные ресурсы,
безопасные повторы, correlation ID и стабильный JSON-результат.

## Защитные свойства

- HTTP(S)- и опционально SOCKS-прокси; HTTPX `0.28+`;
- target использует HTTPS по умолчанию;
- redirects не выполняются автоматически;
- loopback, link-local и private IP требуют явного opt-in;
- отдельные `connect`, `read`, `write`, `pool` timeout;
- общий deadline до 600 секунд и ответ не более 10 MiB;
- `trust_env=False`: системные proxy variables не меняют маршрут;
- повторы только для `GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`;
- `408`, `425`, `429`, `5xx`, transport errors, backoff и jitter;
- `Retry-After` поддерживает seconds и HTTP-date; слишком большая пауза
  останавливает повтор;
- proxy URL и credentials задаются раздельно;
- путь, query, userinfo и fragment не попадают в JSON-результат;
- тело ответа не печатается CLI, но доступно библиотечному коду;
- typed-блок `execution` одинаков с Node.js SDK и содержит route, quality,
  next action и опциональную оценку cost;
- офлайн-тесты используют `httpx.MockTransport`.

Literal IP/localhost проверяются локально. Если target URL поступает от
недоверенного пользователя, добавьте policy-layer allowlist и сетевой egress
control: клиент не делает DNS resolution до передачи запроса прокси и сам по
себе не защищает от DNS rebinding.

> Используйте решение только для систем и данных, на работу с которыми у вашей
> организации есть право. Проверьте договоры, правила целевых сервисов и
> требования к персональным данным.

## Установка

Требуется Python 3.9+.

Установка напрямую из этого репозитория:

```bash
python -m pip install \
  "git+https://github.com/smuuuzik-tech/proxy-use-cases.git#subdirectory=integrations/python-production"
```

Локальная разработка:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Для SOCKS5:

```bash
python -m pip install -e '.[socks]'
```

Для разработки:

```bash
python -m pip install -e '.[dev]'
pytest
```

## Конфигурация

Клиент не загружает `.env` автоматически. В production передавайте credentials
через secret manager, CI/CD variables или защищённое окружение.

```bash
export B2B_PROXY_URL='http://proxy.example.net:8080'
export B2B_PROXY_USERNAME='account-name'
export B2B_PROXY_PASSWORD='secret-from-secret-manager'
```

Не используйте `http://user:password@host:port`: такой proxy URL отклоняется.
Поддерживаются `http`, `https`, `socks5`, `socks5h`; SOCKS требует extra
`.[socks]`.

Основные limits перечислены в [.env.example](.env.example). Значения
проверяются на конечность и имеют верхние границы.

Если известна оценка одной сетевой попытки, можно добавить оба значения:

```bash
export B2B_ESTIMATED_COST_PER_ATTEMPT='0.002'
export B2B_COST_CURRENCY='USD'
```

Без них SDK явно возвращает `cost.basis=not_configured`.

## Безопасный CLI

Простой GET:

```bash
proxy-b2b https://service.example/health --pretty
```

URL можно убрать из process arguments:

```bash
export B2B_TARGET_URL='https://service.example/health'
proxy-b2b --pretty
```

Для заголовков и тела используйте защищённые файлы или stdin, а не аргументы
командной строки:

```bash
umask 077
printf '%s\n' '{"Content-Type":"application/json"}' > headers.private.json
printf '%s\n' '{"state":"active"}' > body.private.json
export B2B_REQUEST_ID='sync-2026-07-23-001'

proxy-b2b https://service.example/resources/42 \
  --method PUT \
  --headers-file headers.private.json \
  --json-body-file body.private.json \
  --pretty
```

Значение `-` читает один input из stdin. Заголовки должны быть JSON object со
строковыми значениями. `NaN` и `Infinity` в JSON отклоняются.

Пример результата:

```json
{
  "attempts": 1,
  "elapsed_ms": 184,
  "execution": {
    "schema_version": "1.1",
    "route": {
      "selected": "http_proxy",
      "reason": "configured_http_proxy",
      "next_action": "complete",
      "automatic_escalation": false,
      "manual_candidates": [
        "browser",
        "managed_unblocker",
        "ai_extraction"
      ]
    },
    "quality": {
      "outcome": "success",
      "attempts": 1,
      "retries": 0,
      "elapsed_ms": 184,
      "status_code": 200,
      "response_bytes": 17
    },
    "cost": {
      "basis": "not_configured",
      "currency": null,
      "unit_cost": null,
      "estimated_total": null
    }
  },
  "method": "GET",
  "ok": true,
  "request_id": "c275f985-809d-4428-9546-993e31392c66",
  "response": {
    "bytes": 17,
    "content_type": "application/json"
  },
  "retries": 0,
  "status_code": 200,
  "url": "https://service.example/<redacted-path>"
}
```

Exit codes:

| Код | Значение |
|---:|---|
| `0` | Успешный HTTP `2xx` |
| `2` | Ошибка аргументов или конфигурации |
| `3` | Неуспешный HTTP-статус или policy limit |
| `4` | Исчерпаны попытки из-за transport/proxy/timeout |
| `5` | Непредвиденная внутренняя ошибка |

Кроме стандартного `--help`, штатные результаты и ошибки CLI печатаются как
JSON в stdout. Заголовки, request body, response body, proxy endpoint и
credentials не печатаются.

## Использование как библиотеки

Самый короткий вариант:

```python
from proxy_b2b_client import ProxyClient

with ProxyClient.from_env() as proxy:
    result = proxy.get(
        "https://service.example/api/items?page=1",
        request_id="inventory-sync-0001",
    )

if not result.ok:
    raise RuntimeError(result.to_dict())

items = result.response.json()
```

`result.execution` — typed dataclass. Для передачи в мониторинг используйте
`result.execution.to_dict()`. Полный формат и правила ручной эскалации:
[Execution Contract](../../docs/EXECUTION-CONTRACT.md).

Расширенная конфигурация:

```python
from proxy_b2b_client import B2BHttpClient, ClientSettings

settings = ClientSettings.from_env()

with B2BHttpClient(settings) as client:
    result = client.request(
        "GET",
        "https://service.example/api/items?page=1",
        headers={"Accept": "application/json"},
        request_id="inventory-sync-0001",
    )

if not result.ok:
    raise RuntimeError(result.to_dict())

items = result.response.json()
```

Создавайте один клиент на worker или длительную задачу. Для `PUT`/`DELETE` можно
запретить повтор конкретного запроса:

```python
result = client.request("PUT", url, json_data=payload, retry=False)
```

Переданные одновременно `content` и `json_data`, а также конфликтующий
`request_id`/`X-Request-ID`, отклоняются.

## Retry policy

`B2B_MAX_ATTEMPTS` включает первую попытку. Backoff:

```text
min(backoff_max, backoff_base × 2^(attempt-1)) + random(0, jitter)
```

Пауза `Retry-After` имеет приоритет, если не превышает
`B2B_RETRY_AFTER_MAX_SECONDS` и общий deadline. `POST` и `PATCH` автоматически
не повторяются. Даже для `PUT`/`DELETE` включайте повтор только при подтверждённой
идемпотентности API.

## Проверка

```bash
pytest
```

Тесты без сети проверяют retries, `Retry-After`, лимит ответа, redaction,
correlation ID, безопасный target policy, конфигурационные границы и JSON-контракт
CLI.

## English summary

Provider-neutral synchronous Python/HTTPX client for B2B proxy workloads. It
uses explicit proxy configuration with `trust_env=False`, HTTPS-by-default
targets, granular timeouts, an overall deadline, bounded response bodies,
idempotency-aware retries, `Retry-After`, correlation IDs, sanitized results,
and stable CLI exit codes. Request headers and bodies are accepted from files or
stdin rather than command-line values.
