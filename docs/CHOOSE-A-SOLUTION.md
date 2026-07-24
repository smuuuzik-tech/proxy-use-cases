# Как выбрать решение за 30 секунд

Эту страницу можно отправить клиенту вместе с репозиторием.

## Прокси ещё не подключён

Начните с [cURL quickstart](../quickstarts/curl/). Если он вернул ошибку,
запустите [Proxy Diagnostics](../tools/proxy-diagnostics/) и передайте
очищенный отчёт инженеру.

## Подключение нужно встроить в сервис

| Runtime | Решение |
|---|---|
| Python / HTTPX / worker / ETL | [Andrey Proxy SDK для Python](../integrations/python-production/) |
| Node.js / JavaScript / TypeScript / Undici | [Andrey Proxy Client для Node.js](../integrations/node-production/) |
| Playwright внутри Node.js-сервиса, exact allowlist и replay | [Policy-gated Browser Route](BROWSER-ROUTE-AND-REPLAY.md) |
| Playwright и проверка собственного сайта | [Regional Web QA](../use-cases/regional-web-qa/) |

SDK нужны, когда важны pooling, timeout, retry budget, correlation ID и
стабильный результат. Для одного ручного запроса SDK избыточен.

Browser Route выбирайте только после проверки обычного HTTP route и явного
решения владельца сценария. Для настоящего прокси начните с
[локального acceptance](LOCAL-REAL-PROXY-ACCEPTANCE.md).

## Интеграция работает, но нестабильно

- Инцидент: [Proxy Diagnostics](../tools/proxy-diagnostics/).
- Мониторинг: [Proxy Healthcheck](../tools/proxy-healthcheck/).
- Сравнение нескольких пулов:
  [Proxybench](../tools/proxybench/).
- Sticky/rotating: [Session Strategy Analyzer](../labs/session-strategy/).
- Метрики и реакция: [SLO и runbook](B2B-SLO-AND-RUNBOOK.md).

`Proxybench` имеет смысл только после одинакового контролируемого healthcheck
для каждого кандидата. Он не рекомендует победителя, если обязательные SLO не
прошёл никто.

## Есть API конкретного поставщика

Изолируйте его за adapter boundary. В репозитории есть
[защитный пример](../integrations/proxy-market-api/), но он не является
универсальной рекомендацией поставщика.

Не отправляйте пароли, tokens, cookies, private targets и клиентские данные.
Для разбора достаточно runtime, типа прокси, объёма, географии, кодов ошибок и
измеримого критерия успеха.
