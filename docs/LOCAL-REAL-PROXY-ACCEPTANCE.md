# Как локально проверить настоящий прокси

Этот план используется, когда вы готовы дать доступ к тестовому прокси. Пароль
лучше не отправлять сообщением: он помещается в локальный
`acceptance.private.json`, который игнорируется Git и доступен только владельцу
файла.

После заполнения файла достаточно написать: **«приватный конфиг готов»**. Тогда
проверку можно выполнить локально, не публикуя endpoint, credentials, IP или
клиентский target.

## Что нужно подготовить

1. Proxy endpoint без inline credentials:
   `http://host:port`, `https://host:port` или поддерживаемый SOCKS5.
2. Username и password отдельно, если используется авторизация.
3. Разрешённый HTTPS endpoint для обычного HTTP-запроса.
4. Разрешённый HTTPS target для browser check.
5. Точный список hostnames основного документа и необходимых subresources.
6. Ожидаемый JSON field/value для проверки exit IP — опционально.
7. Ожидаемая модель: статический, sticky или rotating proxy.

Не используем production-аккаунт клиента, приватную админку или персональные
данные без отдельного явного решения.

## Подготовка

```bash
cd integrations/node-production
npm ci
npm install --no-save --package-lock=false playwright@1.61.0
npx playwright install chromium

cp acceptance.example.json acceptance.private.json
chmod 600 acceptance.private.json
```

Заполните `acceptance.private.json` локально. Этот файл и все job artifacts
находятся в `.gitignore`.

`http.connection_mode` принимает `pooled` (по умолчанию) или `fresh_tunnel`.
Сначала используйте `pooled`; менять режим стоит после сравнительной проверки.

Если у прокси нет авторизации, удалите `username` и `password`. Если endpoint не
возвращает JSON с ожидаемым IP, удалите `body_assertion` и
`fingerprint_json_field`.

Проверка без сети:

```bash
npm test
npm run check
```

Запуск с настоящим прокси:

```bash
npm run acceptance:local
```

## Что проверяет один acceptance run

### 1. Конфигурация и policy

- private config является обычным файлом, не symlink;
- permissions не шире `0600`;
- placeholders отсутствуют;
- credentials не находятся внутри proxy URL;
- browser route явно подтверждён;
- target совпадает с точным allowlist;
- HTTP/private targets не включаются случайно.

Любая ошибка здесь останавливает работу до первого сетевого запроса.

### 2. Обычный HTTP route

- соединение действительно создаётся через явный `ProxyAgent`;
- системные `HTTP_PROXY`, `HTTPS_PROXY` и `NO_PROXY` не меняют маршрут;
- proxy authentication работает;
- TLS и HTTP status получены;
- timeout/retry budget ограничены;
- число attempts и итоговый outcome записаны в `execution`;
- optional JSON assertion проверяет ожидаемый exit IP, но не публикует его;
- `fingerprint_json_field` сохраняет только короткий SHA-256 fingerprint
  наблюдения — по нему можно сравнивать повторы без сохранения IP.

### 3. Browser route

- Chromium стартует с тем же proxy endpoint;
- используется новый изолированный context;
- service workers, downloads и WebSocket ограничены;
- navigation и subresources проходят exact-host allowlist;
- небезопасные методы блокируются;
- request budget, navigation timeout и total deadline соблюдаются;
- final target остаётся разрешённым;
- HTTP status попадает в тот же `execution` contract;
- screenshot/trace создаются только при явном включении.

### 4. Durable job и replay

- manifest сначала получает `running`, затем финальное состояние;
- events отражают переход;
- report содержит только санитизированные поля;
- receipt соответствует SHA-256 report;
- offline replay подтверждает целостность;
- audit не находит proxy URL, username, password или target URL в текстовых
  artifacts.

## Локальные артефакты

По умолчанию:

```text
integrations/node-production/.local-acceptance/<job-id>/
```

Внутри будут manifest, events, report, receipt и
`acceptance-summary.json`. Screenshot и trace появляются только при включённых
флагах и считаются чувствительными.

Ничего из этой директории не отправляется в GitHub.

## Негативные проверки

Проводятся последовательно, после успешного базового запуска:

| Проверка | Безопасный способ | Ожидаемый результат |
|---|---|---|
| Host вне allowlist | Изменить browser target, не добавляя host в allowlist | Отказ до запуска target |
| Request budget | Временно поставить `max_requests: 1` | `response_limit` |
| Неверный password | Только с отдельного разрешения, затем сразу восстановить | Санитизированная proxy/transport failure |
| Изменённый report | Менять копию job directory | Replay отклоняет SHA-256 |
| Public permissions | Сделать копию config с mode `0644` | Отказ до сети |

Неверный password не проверяется автоматически: такая попытка может попасть в
security logs поставщика.

## Проверка sticky и rotation

Для контролируемого сравнения двух режимов укажите тот же разрешённый JSON
endpoint через переменные окружения и запустите:

```bash
export B2B_ROTATION_TARGET_URL='https://authorized.example.net/identity'
export B2B_ROTATION_TARGET_LABEL='authorized identity endpoint'
export B2B_ROTATION_JSON_FIELD='ip'
export B2B_ROTATION_SAMPLES_PER_MODE='10'
npm exec -- andrey-proxy-rotation
```

Команда сравнит `pooled` и `fresh_tunnel`. Raw IP и fingerprints не попадут в
отчёт. Поле `automatic_mode_change=false` означает, что production-конфигурация
не меняется без вашего решения. Подробности:
[Стратегии соединения и ротация](CONNECTION-STRATEGIES-AND-ROTATION.md).

Для полноценного сравнительного теста используйте Proxy Healthcheck и
Proxybench на одинаковом workload.

## Критерии приёмки

Прокси считается готовым к пилотной интеграции, если:

- HTTP и browser execution имеют `quality.outcome=success`;
- body assertion, если настроен, прошёл;
- final browser target разрешён;
- replay и audit успешны;
- credentials отсутствуют в stdout и текстовых artifacts;
- limits не отключались;
- повторные запуски соответствуют ожидаемой sticky/rotation модели.

После этого отдельно определяются production SLO: success rate, p95, retry
amplification и стоимость успешного результата.

## English summary

Use a local owner-only JSON config for real proxy acceptance. The runner checks
the HTTP and browser routes, exact policy gates, bounded resources, durable job
state, receipt integrity, offline replay, and secret-free text artifacts.
