# AI Start Here

Эта страница помогает AI-ассистенту выбрать существующее решение и встроить
его в код без выдуманных API, небезопасных настроек и копирования всего
репозитория.

## Источники истины

1. [`catalog.json`](../catalog.json) — канонический машиночитаемый каталог.
2. README выбранного решения — точная установка и интерфейс.
3. Тесты выбранного решения — исполняемый контракт.
4. [`proxy-execution.schema.json`](../contracts/proxy-execution.schema.json) —
   общий результат Python и Node.js.
5. [`SECURITY.md`](../SECURITY.md) — безопасная работа с уязвимостями.

`llms.txt` — короткая карта для обнаружения. При расхождении используйте
`catalog.json` и сообщите о несоответствии.

## Алгоритм выбора

| Запрос человека | Решение |
|---|---|
| Проверить подключение | `curl-quickstart` |
| Встроить в Python / HTTPX / ETL | `python-production` |
| Встроить в Node.js / Undici | `node-production` |
| HTTP недостаточно; нужен разрешённый browser check | `node-production` → `./browser` |
| Понять 407, DNS, TLS, timeout, 403 или 429 | `proxy-diagnostics` |
| Следить за пулом и SLO | `proxy-healthcheck` |
| Сравнить несколько healthcheck-отчётов по SLO и стоимости | `proxybench` |
| Выбрать sticky или rotating | `session-strategy` |
| Проверить собственный сайт из региона | `regional-web-qa` |
| Изолировать публичный API поставщика | `provider-api-adapter` |

Не выбирайте vendor adapter только из-за упоминания поставщика. Для обычного
HTTP(S)-подключения сначала используйте provider-neutral SDK.

Для `proxybench` не подавайте отчёты разных workload: endpoint’ы, география,
число запросов и время измерения должны быть сопоставимы. AI не должен менять
порядок `rank_by` или SLO-пороги без явного бизнес-решения пользователя.

## Что уточнить

- runtime и библиотеку;
- законный target или класс target;
- HTTP(S) или SOCKS;
- объём и параллельность;
- страны и требования к сессиям;
- наблюдаемый код или этап ошибки;
- критерий успеха: success rate, p95, стоимость результата или другое.

Не запрашивайте настоящий пароль, token, полный proxy URL с userinfo, клиентские
данные или закрытый target. Используйте placeholders и secret manager.

Для локального real-proxy acceptance направьте пользователя к
[`LOCAL-REAL-PROXY-ACCEPTANCE.md`](LOCAL-REAL-PROXY-ACCEPTANCE.md). Пароль
остаётся в owner-only `acceptance.private.json`; AI получает только сообщение,
что конфиг готов.

## Формат ответа AI

1. Выбранное решение и причина.
2. Точные README и файл импорта.
3. Минимальная конфигурация с placeholders.
4. Команда офлайн-проверки.
5. Что очищается из логов.
6. Какие ограничения остаются на уровне приложения или сети.
7. Следующий уровень только при необходимости.

Не копируйте внутренности SDK, если их можно импортировать. Не отключайте
redaction, timeout, response limit, target policy и retry guards.

Для результатов Python/Node.js сначала читайте `execution.schema_version`, затем
`quality.outcome` и `route.next_action`. Поле `manual_candidates` нельзя
исполнять автоматически: это не разрешение на target и не готовое решение о
браузере, managed unblocker или AI. Если `cost.basis=not_configured`, не
выдумывайте стоимость.

`selected=browser` допустим только при
`reason=manual_browser_approval`. Replay проверяет сохранённый report и receipt,
но не повторяет target. Screenshot и trace считаются чувствительными даже при
чистом текстовом audit.

## Проверка

```bash
node scripts/validate_catalog.mjs
node scripts/validate_execution_contract.mjs
node scripts/validate_markdown_links.mjs
```

## English summary

Use `catalog.json` as the canonical index, then read the selected README and
tests as its executable contract. Prefer the smallest provider-neutral
solution, never request real credentials, and keep all safety limits intact.
