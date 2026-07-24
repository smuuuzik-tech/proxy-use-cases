# AI Start Here

Эта страница помогает AI-ассистенту выбрать существующее решение и встроить
его в код без выдуманных API, небезопасных настроек и копирования всего
репозитория.

## Источники истины

1. [`catalog.json`](../catalog.json) — канонический машиночитаемый каталог.
2. README выбранного решения — точная установка и интерфейс.
3. Тесты выбранного решения — исполняемый контракт.
4. [`SECURITY.md`](../SECURITY.md) — безопасная работа с уязвимостями.

`llms.txt` — короткая карта для обнаружения. При расхождении используйте
`catalog.json` и сообщите о несоответствии.

## Алгоритм выбора

| Запрос человека | Решение |
|---|---|
| Проверить подключение | `curl-quickstart` |
| Встроить в Python / HTTPX / ETL | `python-production` |
| Встроить в Node.js / Undici | `node-production` |
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

## Проверка

```bash
node scripts/validate_catalog.mjs
node scripts/validate_markdown_links.mjs
```

## English summary

Use `catalog.json` as the canonical index, then read the selected README and
tests as its executable contract. Prefer the smallest provider-neutral
solution, never request real credentials, and keep all safety limits intact.
