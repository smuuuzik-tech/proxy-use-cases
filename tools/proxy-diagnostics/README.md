# Диагностика 407, DNS, TLS и timeout

Запускаемый, провайдер-независимый инструмент для первой линии B2B-диагностики.
Он делает один ограниченный HTTPS-запрос через прокси, классифицирует сбой и
возвращает JSON, пригодный для тикета, CI или runbook.

## Когда использовать

- прокси отвечает `407 Proxy Authentication Required`;
- запрос зависает или завершается по timeout;
- неясно, где выполняется DNS для SOCKS;
- TLS handshake или проверка сертификата завершаются ошибкой;
- нужно отделить проблему прокси-пула от `403`, `429` или `5xx` целевого сервиса.

Инструмент не пытается обходить контроль доступа. Запускайте его только для
прокси и HTTPS-ресурсов, на работу с которыми у организации есть право.

## Быстрый запуск

Требуются Python 3.9+ и `curl`.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .

export PD_PROXY_URL='http://proxy.example:8000'
export PD_PROXY_USERNAME='business-user'
export PD_PROXY_PASSWORD='replace-me'

proxy-diagnostics \
  --target 'https://api.ipify.org?format=json' \
  --output report.json
```

Код возврата показывает класс проблемы:

| Код | Класс |
|---:|---|
| 0 | маршрут работает |
| 10 | аутентификация прокси |
| 11 | DNS |
| 12 | timeout |
| 13 | TLS |
| 14 | соединение с прокси |
| 15 | `403`, `429`, `5xx` или обрыв upstream |
| 20 | неизвестная ошибка |

## Безопасность

- credentials передаются `curl` через stdin, а не в аргументах процесса;
- отчёт не содержит username, password, query или путь target URL;
- разрешён только HTTPS target;
- literal private, loopback и link-local IP блокируются по умолчанию;
- `NO_PROXY` очищается, чтобы тест не обошёл прокси незаметно;
- connect и total timeout ограничены;
- отключение TLS-проверки не предусмотрено.

## Как читать тайминги

- `time_namelookup_ms` — подготовка разрешения имени;
- `time_connect_ms` — TCP connect;
- `time_tls_ms` — момент завершения TLS;
- `time_first_byte_ms` — первый байт ответа;
- `time_total_ms` — полный запрос.

Один запрос показывает класс отказа, но не качество пула. Для решения о
production-нагрузке используйте вместе с
[Proxy Healthcheck](../proxy-healthcheck/) и измеряйте success rate, p95 и
стоимость успешного результата.

## Проверка без настоящего прокси

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## Разобрать похожую B2B-задачу

[Описать симптомы и выбрать следующий тест](https://andrey-proxy-advisor-private.vercel.app/github?case=proxy_diagnostics&utm_source=github&utm_medium=case_readme&utm_campaign=b2b_proxy_cases&utm_content=proxy_diagnostics).

Не отправляйте в форму реальные пароли, токены и закрытые конфигурации.
