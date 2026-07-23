# Проверка прокси через cURL

Минимальный provider-neutral quickstart для первой проверки HTTP(S)- или
SOCKS-прокси. Он подходит для ручной диагностики и как базовый smoke test перед
интеграцией прокси в B2B-систему.

**Последняя проверка:** 2026-07-23
**Требования:** Bash 3.2+ и cURL 7.53.0+

> **English summary:** Set `PROXY_URL` and, if required, `PROXY_USER` plus
> `PROXY_PASSWORD`, then run `./check_proxy.sh`. The script sends one HTTPS GET
> request through the proxy, prints only the response body to stdout, enforces
> connection/total timeouts, and returns cURL's non-zero exit code on failure.

## Что именно проверяется

Скрипт отправляет один HTTPS GET-запрос через указанный прокси. По умолчанию
используется `https://api.ipify.org?format=json`, поэтому успешный ответ содержит
публичный IP-адрес выхода:

```json
{"ip":"203.0.113.10"}
```

Это пример формата: фактический адрес будет другим. В stdout попадает только тело
ответа. Диагностика ошибок отправляется в stderr. Скрипт:

- запрещает credentials внутри `PROXY_URL`;
- передаёт proxy credentials через stdin-конфигурацию cURL, а не аргумент
  командной строки;
- передаёт `CHECK_URL` через ту же stdin-конфигурацию и запрещает credentials
  внутри endpoint URL;
- переопределяет `NO_PROXY`, чтобы тестовый хост не был случайно вызван напрямую;
- завершает запрос, если соединение занимает больше
  `CONNECT_TIMEOUT_SECONDS` или вся операция — больше `MAX_TIME_SECONDS`;
- считает HTTP 4xx/5xx ошибкой и сохраняет исходный ненулевой exit code cURL;
- не читает пользовательский `.curlrc`.

Сервис проверки IP является внешней системой и увидит IP выхода и стандартные
метаданные HTTP-запроса. Для корпоративного контура задайте собственный HTTPS
endpoint через `CHECK_URL`.

## Быстрый старт

```bash
cd quickstarts/curl
cp .env.example .env
chmod +x check_proxy.sh
```

Отредактируйте `.env`, затем загрузите только доверенный локальный файл:

```bash
set -a
source ./.env
set +a
./check_proxy.sh
```

`.env` исключён из Git в этой папке. Не помещайте рабочие credentials в
`.env.example`, README, issue, CI-лог или скриншот.

Без `.env` можно передать значения на один запуск:

```bash
PROXY_URL="http://proxy.example.com:8080" ./check_proxy.sh
```

Для прокси с аутентификацией:

```bash
PROXY_URL="http://proxy.example.com:8080" \
PROXY_USER="replace_me" \
PROXY_PASSWORD="replace_me" \
./check_proxy.sh
```

Не добавляйте логин и пароль в URL. Такой формат легко попадает в историю
команд, логи и сообщения об ошибках. Скрипт его намеренно отклоняет.

## Настройки

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---:|---|---|
| `PROXY_URL` | да | — | URL прокси со схемой `http`, `https`, `socks4`, `socks4a`, `socks5` или `socks5h` |
| `PROXY_USER` | нет | — | Имя пользователя; задаётся только вместе с паролем |
| `PROXY_PASSWORD` | нет | — | Пароль; задаётся только вместе с пользователем |
| `CHECK_URL` | нет | `https://api.ipify.org?format=json` | HTTPS endpoint, возвращающий JSON или текст |
| `CONNECT_TIMEOUT_SECONDS` | нет | `10` | Лимит DNS, TCP и TLS-установления соединения |
| `MAX_TIME_SECONDS` | нет | `30` | Лимит всей операции |

Если endpoint возвращает простой текст, stdout может выглядеть так:

```text
203.0.113.10
```

Скрипт проверяет транспортный и HTTP-результат, но не пытается угадать схему
чужого JSON. В автоматизации валидируйте тело отдельно под контракт своего
endpoint.

## Обработка ошибок

При ошибке тело HTTP 4xx/5xx не выдаётся как успешный результат, в stderr
появляется короткое сообщение, а процесс возвращает код cURL. Частые коды:

| Код | Значение | Что проверить |
|---:|---|---|
| 5 | не удалось разрешить имя прокси | hostname и DNS |
| 6 | не удалось разрешить имя endpoint | `CHECK_URL` и DNS |
| 7 | соединение не установлено | адрес, порт, firewall и allowlist |
| 22 | HTTP 4xx/5xx | аутентификацию, лимиты и ответ endpoint |
| 28 | timeout | доступность, сеть и значения timeout |

Например:

```text
curl: (28) Connection timed out after 10001 milliseconds
check_proxy.sh: proxy check failed (curl exit code 28).
```

Скрипт не печатает proxy URL, логин или пароль. Не запускайте его с `bash -x`:
режим трассировки оболочки может раскрыть переменные окружения.

## Локальная проверка без настоящего прокси

Из корня репозитория:

```bash
bash -n quickstarts/curl/check_proxy.sh
bash -n tests/shell/test_curl_quickstart.sh
bash tests/shell/test_curl_quickstart.sh
```

Тест использует локальную заглушку cURL: сетевые запросы и реальные credentials
не нужны.

## Законные и этичные границы

Используйте прокси только для систем, данных и сценариев, на которые у вашей
организации есть право и полномочия. Соблюдайте применимое законодательство,
договоры, правила целевых сервисов, требования к персональным данным, rate
limits и внутренние политики безопасности. Не применяйте пример для обхода
контроля доступа, сокрытия вредоносной активности, несанкционированного сбора
данных или вмешательства в работу чужих систем.

Для B2B-внедрения этот quickstart является только smoke test. Перед production
нужны централизованное хранение секретов, журналирование без credentials,
повторные попытки с backoff, мониторинг качества, лимиты нагрузки, ротация
доступов и процедура реагирования на инциденты.

## Справка cURL

- [`--proxy`](https://curl.se/docs/manpage.html#-x)
- [`--proxy-user`](https://curl.se/docs/manpage.html#-U)
- [`--noproxy`](https://curl.se/docs/manpage.html#--noproxy)
- [`--connect-timeout`](https://curl.se/docs/manpage.html#--connect-timeout)
- [`--max-time`](https://curl.se/docs/manpage.html#-m)
- [exit codes](https://curl.se/docs/manpage.html#EXIT-CODES)
