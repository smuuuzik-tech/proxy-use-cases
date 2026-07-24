# B2B Proxy Toolkit Андрея Малышева

[English](README.en.md)

Провайдер-независимые, запускаемые решения для настройки и интеграции прокси:
от первого smoke test до production-клиента, мониторинга пула и доказательного
регионального QA.

Материалы подготовлены Андреем для разработчиков, технических руководителей,
DevOps/SRE и команд, которым нужен воспроизводимый результат. Основные решения
не привязаны к конкретному продавцу прокси; особенности публичных API вынесены
в отдельные технические разборы.

**Нужно разобрать корпоративный сценарий?**
[Открыть экспертную страницу и выбрать время звонка](https://andrey-proxy-advisor-private.vercel.app/github?utm_source=github&utm_medium=readme&utm_campaign=proxy_use_cases).

**Отправляете репозиторий клиенту?**
[Начните с клиентской инструкции](docs/CLIENT-START-HERE.md): в ней установка
личных Python/Node.js решений Андрея, безопасная передача доступов и маршрут
диагностики. Для быстрого выбора используйте
[страницу «30 секунд»](docs/CHOOSE-A-SOLUTION.md).

## Выберите уровень

| Уровень | Задача | Рабочее решение |
|---|---|---|
| 1. Подключение | Проверить маршрут, авторизацию и внешний IP | [cURL quickstart](quickstarts/curl/) |
| 2. Интеграция | Встроить прокси в Python с timeout, retry budget и JSON-контрактом | [Andrey Proxy SDK](integrations/python-production/) |
| 2/3. Интеграция | Встроить прокси в Node.js; при явном approval добавить browser route, durable job и replay | [Andrey Proxy Client для Node.js](integrations/node-production/) |
| 3. Эксплуатация | Измерять success rate, p95, retry amplification, ошибки и состояние пула | [Proxy Healthcheck](tools/proxy-healthcheck/) |
| 3. Решение | Сравнить пулы по единым SLO и стоимости успешного результата | [Proxybench](tools/proxybench/) |
| 3/4. Бизнес-процесс | Проверять разрешённый сайт из согласованного региона и сохранять evidence | [Regional Web QA](use-cases/regional-web-qa/) |

## Найдите проблему

| Симптом или решение | Рабочий материал |
|---|---|
| `407`, DNS, TLS, timeout, `403`, `429` или обрыв соединения | [Proxy Diagnostics](tools/proxy-diagnostics/) |
| Нужно выбрать sticky-сессию или rotation на данных workload | [Session Strategy Analyzer](labs/session-strategy/) |
| Нужно выбрать между двумя или несколькими пулами на измеримых данных | [Proxybench](tools/proxybench/) |
| HTTP недостаточно для разрешённой проверки | [Policy-gated Browser Route](docs/BROWSER-ROUTE-AND-REPLAY.md) |
| Нужен изолированный адаптер публичного API конкретного провайдера | [Vendor-specific API client](integrations/proxy-market-api/) |

Все девять решений имеют офлайн-тесты и не требуют настоящих credentials для
проверки кода.

Python и Node.js SDK возвращают одинаковый версионированный
[`execution`-контракт](docs/EXECUTION-CONTRACT.md): выполненный маршрут, причина
решения, attempts/retries, нормализованное качество, безопасное следующее
действие и опциональная оценка стоимости.

## B2B-контур

- [Модель зрелости](docs/B2B-MATURITY-MODEL.md) — какой уровень нужен компании.
- [Референсная архитектура](docs/B2B-REFERENCE-ARCHITECTURE.md) — границы policy,
  клиента, прокси-пула и наблюдаемости.
- [Execution Contract](docs/EXECUTION-CONTRACT.md) — единый typed-результат
  Python/Node.js для приложений, мониторинга и AI.
- [Browser Route and Replay](docs/BROWSER-ROUTE-AND-REPLAY.md) — ручной policy
  gate, приватные durable jobs и проверяемый replay.
- [Проверка настоящего прокси](docs/LOCAL-REAL-PROXY-ACCEPTANCE.md) — локальный
  acceptance без публикации credentials и клиентских targets.
- [Шаблон SLO и runbook](docs/B2B-SLO-AND-RUNBOOK.md) — метрики, состояния и
  порядок действий при инциденте.
- [Опциональный API-адаптер](integrations/proxy-market-api/) — пример того,
  как изолировать контракт конкретного поставщика от основной системы.

Для AI-ассистентов опубликованы [AI Start Here](docs/AI-START-HERE.md),
канонический [`catalog.json`](catalog.json) со схемой и короткий
[`llms.txt`](llms.txt). Каталог проходит CI-проверку путей, обязательных полей и
ссылок документации.

## Инженерные принципы

- Примеры используют стандартные HTTP/SOCKS-интерфейсы и не зависят от
  конкретного провайдера.
- Секреты передаются отдельно от URL и не попадают в публичные результаты.
- HTTPS является безопасным значением по умолчанию; небезопасные и private
  targets требуют явного решения.
- Таймауты, параллелизм, размер ответа и число повторов ограничены.
- `NO_PROXY` не должен незаметно обходить проверяемый маршрут.
- Повторы применяются только там, где это допускает идемпотентность и retry
  budget.
- URL, ошибки и evidence очищаются от пути, query и credentials.
- Сценарии предназначены только для систем и данных, на работу с которыми у
  организации есть право.

## Проверка

Каждая папка содержит свою короткую команду проверки. Общая GitHub Actions CI
запускает shell-, Python- и Node.js-тесты на каждый pull request.

## Участие

Предложения новых сценариев и сообщения об ошибках приветствуются. Перед
публикацией материалов ознакомьтесь с [правилами участия](CONTRIBUTING.md) и
[политикой безопасности](SECURITY.md).
