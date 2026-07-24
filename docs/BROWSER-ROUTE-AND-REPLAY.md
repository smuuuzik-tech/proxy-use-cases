# Browser Route: policy gate, durable job и replay

Browser Route — опциональный слой Node.js SDK для разрешённых B2B-проверок,
когда обычного HTTP-запроса недостаточно. Он не включается автоматически и не
является скрытым обходом ограничений target.

## Гарантии текущей версии

- обязательное `routeApproved=true`;
- точный allowlist HTTPS-hosts без wildcard;
- отдельный allowlist для subresources;
- только `GET`, `HEAD` и `OPTIONS`;
- private, loopback и link-local targets запрещены по умолчанию;
- proxy endpoint и credentials передаются раздельно;
- изолированный browser context без общей cookie/cache state;
- downloads, WebSocket и service workers ограничены;
- число сетевых запросов, navigation timeout и общий deadline ограничены;
- browser popups закрываются;
- screenshot и trace выключены по умолчанию;
- в публичном результате нет proxy, target URL, credentials и raw error;
- следующий маршрут никогда не запускается автоматически.

Маршрут использует общий
[`execution` contract 1.1](EXECUTION-CONTRACT.md):

```json
{
  "schema_version": "1.1",
  "route": {
    "selected": "browser",
    "reason": "manual_browser_approval",
    "next_action": "complete",
    "automatic_escalation": false,
    "manual_candidates": [
      "managed_unblocker",
      "ai_extraction"
    ]
  }
}
```

## Установка

```bash
cd integrations/node-production
npm ci
npm install --no-save --package-lock=false playwright@1.61.0
npx playwright install chromium
```

Основной HTTP SDK не требует Playwright. Browser dependency остаётся
опциональной и устанавливается только для этого маршрута.

## Использование в коде

```js
import { BrowserRouteClient } from "andrey-proxy-sdk-node/browser";

const browser = new BrowserRouteClient({
  routeApproved: true,
  proxyUrl: "http://proxy.example.net:8080",
  proxyUsername: process.env.B2B_PROXY_USERNAME,
  proxyPassword: process.env.B2B_PROXY_PASSWORD,
  targetUrl: "https://service.example/approved-check",
  targetLabel: "approved customer check",
  allowedHosts: ["service.example"],
  resourceAllowedHosts: ["service.example", "static.example"],
  artifactDir: ".browser-jobs",
  maxRequests: 200,
  captureScreenshot: false,
  captureTrace: false,
});

const report = await browser.run();
```

Не помещайте настоящий endpoint или password в исходный код. Пример показывает
только структуру.

## Durable job

Каждый запуск получает отдельную приватную директорию:

```text
<artifact-dir>/<job-id>/
├── manifest.json
├── events.jsonl
├── report.json
├── receipt.json
├── screenshot.png      # только при явном включении
└── trace.zip           # только при явном включении
```

- `manifest.json` фиксирует состояние `running`, затем `completed` или `failed`;
- `events.jsonl` сохраняет последовательность переходов;
- `report.json` содержит санитизированный результат;
- `receipt.json` содержит SHA-256 отчёта;
- файлы создаются с mode `0600`, job directory — `0700`;
- совпадающий `job-id`, symlink и публичные permissions отклоняются.

Если процесс аварийно остановлен до finalize, остаётся `running` manifest:
оператор видит незавершённую работу, а не ложный success.

## Replay и audit

```bash
andrey-proxy-browser --replay .browser-jobs/<job-id>/report.json
andrey-proxy-browser --audit .browser-jobs/<job-id>
```

Replay не выполняет target повторно. Он проверяет schema, route и SHA-256 receipt,
после чего возвращает тот же безопасный decision block.

Audit проверяет текстовые job artifacts на proxy URL, username, password и
target URL, переданные через окружение. Он не анализирует бинарные screenshot и
trace.

## Важное ограничение evidence

Screenshot и trace могут содержать контент страницы, URLs, cookies или другие
чувствительные данные целевой системы. Они:

- выключены по умолчанию;
- предназначены только для локального расследования;
- не должны коммититься или пересылаться без отдельной проверки;
- должны удаляться по принятой в компании retention policy.

Trace запускается без source capture, но всё равно считается чувствительным.

## Что Browser Route пока не делает

- не заполняет формы и не выполняет login;
- не отправляет state-changing requests;
- не запускает extraction или LLM;
- не выбирает managed unblocker;
- не доказывает географию только по заявлению оператора;
- не заменяет сетевой egress control и договорный allowlist.

Для проверки настоящего прокси используйте
[локальный acceptance-план](LOCAL-REAL-PROXY-ACCEPTANCE.md).

## English summary

The optional Browser Route is a manually approved, exact-allowlist Playwright
adapter. It records a private durable job, emits execution contract 1.1, blocks
automatic escalation, and supports integrity-verified offline replay.
