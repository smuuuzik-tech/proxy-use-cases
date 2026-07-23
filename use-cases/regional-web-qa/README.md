# Региональный web QA через Playwright

Провайдер-независимый B2B-runner для проверки собственных или явно разрешённых
сайтов из согласованного региона через прокси. Chromium создаёт приватный
PNG-скриншот и JSON evidence report для QA, release approval или аудита.

Подходит для проверки локализованного контента, региональных цен, каталога, CDN,
редиректов, consent-баннеров и регионального стенда. Не предназначен для обхода
антибот-защиты, контроля доступа или правил сторонних сайтов.

## Безопасные значения по умолчанию

- `CHECK_URL` использует HTTPS и стандартный порт 443;
- точные hostname без wildcard;
- main navigation, iframe и subresources проходят через context-level policy;
- отдельный `RESOURCE_ALLOWED_HOSTS` ограничивает CDN/API/шрифты;
- loopback, link-local и private IP запрещены без явного opt-in;
- popup/новая вкладка закрываются;
- Service Workers блокируются, чтобы они не обходили request interception;
- WebSocket-соединения блокируются: для них нужен отдельный reviewed allowlist;
- Chromium запрещает non-proxied WebRTC UDP;
- proxy endpoint и credentials удаляются из ошибок и JSON;
- path, query, fragment и userinfo URL не сохраняются;
- page title выключен по умолчанию;
- viewport фиксирован на `1440×900`, full-page screenshot выключен, размер PNG
  ограничен 10 MiB;
- имена артефактов содержат UUID, файлы создаются с mode `0600`, каталог —
  `0700`.

Скриншот всё равно может содержать данные страницы. Используйте тестовый аккаунт,
минимальные данные и закрытое хранилище с ограниченным сроком хранения.

## Установка и запуск

Требуется Node.js 20+.

```bash
npm ci
npx playwright install chromium
cp .env.example .env
npm start
```

Минимальная конфигурация:

```dotenv
PROXY_SERVER=http://proxy.example:3128
PROXY_USERNAME=replace-me
PROXY_PASSWORD=replace-me
REGION_LABEL=de-berlin
CHECK_URL=https://staging.example.com/regional-check
ALLOWED_HOSTS=staging.example.com
RESOURCE_ALLOWED_HOSTS=staging.example.com,cdn.example.com
```

Credentials задаются отдельно. URL вида
`http://user:pass@host:port` отклоняется. Playwright поддерживает
username/password для HTTP proxy; `socks5://` в этом примере принимается только
без credentials, например с IP allowlisting.

## Egress policy

`ALLOWED_HOSTS` разрешает только top-level и frame navigation:

```dotenv
ALLOWED_HOSTS=staging.example.com,preview.example.com
```

`RESOURCE_ALLOWED_HOSTS` перечисляет точные hostname для fetch/XHR, scripts,
styles, images, fonts и других ресурсов. Если переменная не задана, используется
`ALLOWED_HOSTS`. Для реального приложения перечислите необходимые CDN и API:

```dotenv
RESOURCE_ALLOWED_HOSTS=staging.example.com,static.examplecdn.com,api.example.com
```

Internal/private стенд можно включить только осознанно:

```dotenv
ALLOW_PRIVATE_TARGETS=true
```

Не используйте этот opt-in в сервисе, где hostname контролирует внешний
пользователь.

Browser interception не заменяет сетевой firewall. Для строгой гарантии egress
запускайте runner в отдельном container/worker, где direct outbound traffic
запрещён на уровне сети и разрешены только proxy endpoint и необходимые
служебные адреса. Это также снижает риск обхода policy через новые browser
transport mechanisms.

## Evidence report

В `ARTIFACT_DIR` создаются уникальные PNG и JSON. URL выглядит так:

```json
{
  "schemaVersion": 1,
  "timestamp": "2026-07-23T10:20:30.000Z",
  "requestedRegionLabel": "de-berlin",
  "regionVerification": "operator_asserted_not_independently_verified",
  "outcome": "passed",
  "exitCode": 0,
  "check": {
    "requestedUrl": "https://staging.example.com/[PATH_REDACTED]",
    "observedUrl": "https://staging.example.com/[PATH_REDACTED]",
    "status": 200,
    "title": null,
    "elapsedTimeMs": 1842
  },
  "expectedStatus": {"min": 200, "max": 399},
  "artifacts": {
    "screenshot": "regional-qa-de-berlin-20260723T102030Z-a1b2c3d4.png"
  },
  "error": null
}
```

Для сохранения title задайте `INCLUDE_PAGE_TITLE=true` только после оценки
риска PII. По умолчанию принимаются статусы `200–399`.

`FULL_PAGE=true` включайте только для доверенной страницы: большая высота DOM
увеличивает память и размер evidence. `MAX_SCREENSHOT_BYTES` ограничивает
сохраняемый PNG значением 1 KiB–50 MiB (по умолчанию 10 MiB).

`REGION_LABEL` — утверждение оператора о выбранном маршруте, а не независимое
геолокационное доказательство. Для подтверждения страны добавьте согласованный
корпоративный geo/IP endpoint отдельной проверкой и сверяйте результат с
инвентарём маршрутов.

## Exit codes

| Код | Значение |
|---:|---|
| `0` | Проверка прошла |
| `1` | Непредвиденная ошибка |
| `2` | Ошибка конфигурации |
| `3` | Playwright или Chromium недоступен |
| `4` | Ошибка навигации, сети или policy |
| `5` | HTTP-статус вне ожидаемого диапазона |
| `6` | Не удалось сохранить evidence |

## Проверки

Офлайн unit-тесты не запускают браузер и сеть:

```bash
npm test
npm run check
```

Реальный e2e требует настроенного `.env`, доступного прокси и Chromium:

```bash
npm run test:e2e
```

В CI обычно запускают отдельную задачу на каждую согласованную региональную
точку, хранят PNG/JSON как закрытые build artifacts и агрегируют `outcome`,
`status` и `elapsedTimeMs`. Для production-процесса задайте владельца allowlist,
срок хранения и процедуру ротации credentials.

Краткая английская версия: [README.en.md](README.en.md).
