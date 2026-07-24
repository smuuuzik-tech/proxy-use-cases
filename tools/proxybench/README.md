# Proxybench

Провайдер-независимый инструмент Андрея Малышева для воспроизводимого сравнения
прокси-пулов по очищенным отчётам
[Proxy Healthcheck](../proxy-healthcheck/). Он не выполняет сетевые запросы:
на вход подаются результаты одинакового контролируемого теста, на выходе —
объяснимые quality/cost gates и ранжирование.

## Зачем он нужен

- сравнить два или больше пулов на одном workload;
- отделить обязательные SLO от предпочтений ранжирования;
- учитывать success rate, p95, retry amplification и стоимость успеха;
- получить `null` вместо опасной рекомендации, если SLO не прошёл никто;
- продолжить сравнение при повреждённом отчёте только через явный
  `allow_partial`;
- не переносить в итог IP-адреса, отдельные результаты, ошибки или пути
  исходных файлов.

`Proxybench` не сравнивает поставщиков «вообще». Вывод относится только к
одинаковым endpoint’ам, числу запросов, географии, времени запуска и
применённой политике.

## Быстрый старт

Требуется Python 3.11+, runtime-зависимостей нет.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp benchmark.example.json benchmark.local.json
mkdir -p reports
```

Сначала сформируйте по одному healthcheck-отчёту для каждого разрешённого
пула. Все отчёты должны быть получены с одной конфигурацией нагрузки:

```bash
proxy-healthcheck --config pool-a-healthcheck.json --output reports/pool-a.json
proxy-healthcheck --config pool-b-healthcheck.json --output reports/pool-b.json
proxybench --config benchmark.local.json --output benchmark-result.json
```

Пути к отчётам должны быть относительными и оставаться внутри каталога
manifest. Это защищает локальные файлы от случайного чтения AI-агентом или CI.

## Явная политика решения

`policy` разделяет два понятия:

1. Gates определяют, допустим ли кандидат:
   - healthcheck status обязан быть `healthy`;
   - success rate не ниже минимума;
   - p95 и retry amplification не выше лимитов;
   - cost per success проходит лимит, если cost gate задан.
2. `rank_by` задаёт точный порядок сравнения прошедших кандидатов.

Поддерживаются четыре метрики, каждая должна встретиться ровно один раз:
`success_rate`, `cost_per_success`, `p95_latency_ms`,
`retry_amplification`. Success rate сортируется по убыванию, остальные — по
возрастанию. Если важнее стоимость, поставьте `cost_per_success` первой.

`total_cost` — стоимость конкретного измеренного запуска, а не цена тарифа.
`cost_per_success = total_cost / successful`. Валюта не конвертируется.

## Частичные результаты

По умолчанию любой нечитаемый или противоречивый отчёт останавливает запуск.
`allow_partial: true` переводит такой кандидат в `unavailable`, не копируя
текст ошибки или путь. Для сравнения всё равно нужны минимум два валидных
кандидата.

## Exit codes

| Код | Значение |
|---:|---|
| `0` | есть кандидат, прошедший все gates |
| `1` | сравнение выполнено, но никто не прошёл gates |
| `64` | ошибка manifest или входного отчёта |
| `70` | ошибка записи результата |

## Контракты

- [`benchmark.schema.json`](src/proxybench/benchmark.schema.json) — manifest;
- [`result.schema.json`](src/proxybench/result.schema.json) — очищенный результат;
- [healthcheck report schema](../proxy-healthcheck/src/proxy_healthcheck/report.schema.json) —
  источник метрик.

## Проверка

```bash
python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/proxybench-pycache python -m compileall -q src tests
```

Все тесты работают без сети, прокси и реальных credentials.

## English summary

Proxybench compares two or more sanitized Proxy Healthcheck reports using
explicit eligibility gates and a caller-defined metric order. It never copies
observed IPs, individual request results, source paths, or raw errors into its
output. No candidate is recommended when every candidate misses the policy.
