# Proxy Healthcheck

Провайдер-независимый инструмент для операционной диагностики корпоративного
пула прокси. Он параллельно проверяет разрешённые компанией HTTPS-endpoint’ы,
измеряет доступность и задержку, фиксирует наблюдаемые внешние IP-адреса и
формирует машиночитаемый JSON-отчёт для CI, мониторинга и B2B SLA-процессов.

Инструмент предназначен только для инфраструктуры, которой организация владеет
или которую ей разрешено проверять. Он не содержит функций обхода ограничений,
антибот-систем, CAPTCHA или маскировки автоматизации.

## Что измеряется

- success rate по каждому endpoint’у и по всему запуску;
- min / average / p95 / max latency успешных проверок;
- число уникальных внешних IP и частота их повторного использования;
- изменения IP в последовательности запросов;
- количество фактических попыток с учётом retry budget;
- стабильная категория ошибки (`proxy_auth`, `dns`, `connect`, `tls`,
  `timeout`, `target_http`, `policy_redirect`, `application_response`);
- причины деградации без попадания логина и пароля прокси в отчёт.

## Быстрый старт

Требуется Python 3.11 или новее. У проекта нет runtime-зависимостей.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp healthcheck.example.json healthcheck.local.json
```

Замените примерный адрес прокси и endpoint’ы. Секреты лучше передавать через
менеджер секретов:

```bash
export PHC_PROXY_URL='http://proxy.company.internal:8080'
export PHC_PROXY_USERNAME='account-name'
export PHC_PROXY_PASSWORD='secret-from-secret-manager'
proxy-healthcheck --config healthcheck.local.json --output report.json
```

Можно запустить без файла, передав endpoint’ы JSON-массивом:

```bash
export PHC_PROXY_URL='http://proxy.company.internal:8080'
export PHC_PROXY_USERNAME='account-name'
export PHC_PROXY_PASSWORD='secret-from-secret-manager'
export PHC_ENDPOINTS='[{"name":"company-ip","url":"https://status.company.example/ip","ip_json_path":"ip"}]'
proxy-healthcheck --output -
```

`.env.example` является перечнем поддерживаемых переменных. Файл `.env`
автоматически не загружается: это снижает риск случайного чтения секрета не из
того окружения.

## Конфигурация

Формат файла — JSON. Переменные `PHC_*` имеют приоритет над значениями файла.

| Поле | Назначение | По умолчанию |
|---|---|---:|
| `proxy_url` | HTTP(S)-URL прокси без credentials | обязательно |
| `proxy_username` / `proxy_password` | Опциональная пара credentials; в production задавайте через `PHC_*` environment | — |
| `endpoints` | Именованные HTTPS-endpoint’ы, возвращающие IP в JSON | обязательно |
| `requests_per_endpoint` | Число логических проверок на endpoint | `5` |
| `concurrency` | Максимум одновременно выполняемых проверок | `10` |
| `timeout_seconds` | Общий deadline подключения и чтения одной попытки | `5` |
| `retry_budget` | Число дополнительных попыток на проверку | `1` |
| `retry_backoff_seconds` | База exponential backoff с full jitter; фактическая пауза capped at 30 seconds | `0.2` |
| `minimum_success_rate` | Нижняя граница healthy | `0.95` |
| `fail_below_success_rate` | Ниже этой границы статус failed | `0.50` |
| `maximum_p95_ms` | Максимальный healthy p95 | `2000` |
| `minimum_unique_ips` | Минимум уникальных IP; можно переопределить для endpoint | `1` |
| `allow_private_targets` | Явный opt-in для approved internal/loopback/non-global endpoint | `false` |

`ip_json_path` поддерживает точечный путь, например `data.address`. Возвращаемое
значение обязательно валидируется как IPv4 или IPv6.

Защитные верхние границы: до 20 endpoint’ов, 100 запросов на endpoint, 64
одновременных worker’ов, 5 повторов и 60 секунд на socket operation. Требование
уникальных IP не может превышать число запросов.

## Exit codes для CI

| Код | Значение |
|---:|---|
| `0` | healthy |
| `1` | degraded |
| `2` | failed |
| `64` | ошибка конфигурации |
| `70` | внутренняя ошибка или невозможность записать отчёт |

Код детерминирован порогами конфигурации. Все endpoint’ы считаются обязательными:
`failed` выставляется, когда хотя бы один из них не имеет успешных проверок или
не достигает `fail_below_success_rate`. Такой же статус выставляется, когда нет
ни одной успешной проверки или общий success rate ниже этого порога.
`degraded` означает, что хотя бы один endpoint не прошёл healthy-порог success
rate, p95 latency или количества уникальных IP.

Пример шага CI:

```bash
proxy-healthcheck --config healthcheck.json --output healthcheck-report.json
```

Код `1` можно считать предупреждением или блокирующим результатом в зависимости
от внутренних правил компании. JSON-отчёт при штатном запуске создаётся для всех
трёх состояний.

## Использование как библиотеки

```python
from proxy_healthcheck import load_config, run_healthcheck

config = load_config("healthcheck.json")
report = run_healthcheck(config)
print(report.status.value)
print(report.to_dict())
```

Собственный транспорт можно передать вторым аргументом. Именно так offline-тесты
подменяют сеть и воспроизводимо проверяют healthy, degraded, failed, ротацию и
редактирование секретов.

## Безопасность

- Используйте только принадлежащие компании прокси и разрешённые endpoint’ы.
- Endpoint’ы обязаны использовать HTTPS.
- Literal private, loopback, link-local и другие non-global IP запрещены по
  умолчанию; internal target требует `PHC_ALLOW_PRIVATE_TARGETS=true`.
- Проверка hostname не выполняет DNS resolution. Если URL может задавать
  недоверенный пользователь, применяйте внешний egress allowlist/firewall,
  защищённый от DNS rebinding.
- Системный `NO_PROXY` намеренно игнорируется: каждая проверка обязана пройти
  через заданный прокси.
- Redirects не выполняются автоматически и отражаются как policy/HTTP ошибка.
- Ответ контрольного endpoint ограничен 64 KiB.
- Не коммитьте `healthcheck.local.json`, `.env` и отчёты с внутренними адресами.
- Proxy endpoint и credentials задаются отдельно и не включаются в отчёт;
  сохраняются только схема и факт настройки authentication.
- Endpoint path, query, userinfo и fragment не включаются в отчёт.
- Сообщения транспортных ошибок проходят дополнительное редактирование.
- Наблюдаемые внешние IP остаются в отчёте, потому что это целевая метрика.
  Рассматривайте отчёт как операционные данные и задайте подходящий срок хранения.

## Проверка проекта

```bash
python -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/proxy-healthcheck-pycache python -m compileall -q src tests
```

Все тесты выполняются без сети и реальных credentials.

## English summary

Proxy Healthcheck is a dependency-free Python 3.11+ CLI and library for
provider-neutral diagnostics of company-owned proxy pools. It checks multiple
authorized HTTPS endpoints concurrently, reports success rate and latency,
summarizes observed external IP rotation, redacts proxy credentials, and returns
stable CI exit codes (`0` healthy, `1` degraded, `2` failed, `64` configuration,
`70` internal error).

Configuration is loaded from a JSON file and can be overridden with `PHC_*`
environment variables. Timeouts, per-check retry budget, success thresholds,
p95 latency, and expected unique-IP counts are explicit. The test suite is fully
offline and uses an injected mock transport. This tool is for authorized
infrastructure monitoring only; it does not implement anti-bot or restriction
bypass techniques. System `NO_PROXY` bypass is disabled, redirects are not
followed, response bodies are capped at 64 KiB, and error categories are stable.
