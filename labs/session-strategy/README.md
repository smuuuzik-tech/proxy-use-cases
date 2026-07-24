# Sticky или rotation: анализ на данных workload

Лаборатория сравнивает две стратегии сессий по журналу реальных или тестовых
запросов. На выходе — не универсальный совет, а измеримые различия в success
rate, p95, стоимости успешного результата и сохранении exit IP.

## Для каких B2B-задач

- sticky-сессия для корзины, авторизованного шага или многостраничного процесса;
- rotation для независимых карточек, поисковых запросов или распределённого
  мониторинга;
- проверка, действительно ли прокси-пул соблюдает session TTL;
- сравнение стратегии на одинаковой географии, целевых ресурсах и concurrency.

## Формат входных данных

Одна строка JSONL — один запрос:

```json
{"strategy":"sticky","request_id":"s-001","session_id":"cart-1","exit_ip":"192.0.2.10","status_code":200,"latency_ms":420,"cost_units":1.2,"success":true}
```

Обязательные поля:

| Поле | Значение |
|---|---|
| `strategy` | `sticky` или `rotating` |
| `request_id` | безопасный технический идентификатор |
| `session_id` | логическая B2B-сессия без персональных данных |
| `exit_ip` | наблюдаемый IP |
| `status_code` | HTTP-код или `0` для transport failure |
| `latency_ms` | полная задержка |
| `cost_units` | стоимость запроса в одной выбранной единице |
| `success` | бизнес-результат запроса |

Не помещайте в журнал URL с query, cookies, credentials и содержимое ответа.

## Запуск

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .

proxy-session-analyzer examples/workload.jsonl --output report.json
```

Отчёт содержит:

- success rate каждой стратегии;
- p95 только по успешным запросам;
- cost per success;
- continuity IP внутри sticky-сессий;
- change rate exit IP для rotation;
- распределение HTTP-кодов и классов ошибок;
- разницы между стратегиями.

## Как принимать решение

Сравнивайте стратегии на одинаковом target mix и при одинаковой нагрузке.
Sticky полезна, когда бизнес-транзакция должна сохранять контекст; rotation —
когда запросы независимы. Побеждает не стратегия с минимальной средней
задержкой, а стратегия с лучшей долей и стоимостью успешного результата при
соблюдении требований процесса.

## Проверка

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## Разобрать свою модель сессий

[Сопоставить workload, географию и критерии успеха](https://andrey-proxy-advisor-private.vercel.app/github?case=session_strategy&utm_source=github&utm_medium=case_readme&utm_campaign=b2b_proxy_cases&utm_content=session_strategy).

Используйте инструмент только для разрешённых систем и данных.
