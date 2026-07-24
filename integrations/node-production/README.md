# Andrey Proxy Client для Node.js

Провайдер-независимый production-клиент Андрея Малышева для B2B-сервисов на
Node.js 20+. Решение использует программно настроенный `undici.ProxyAgent` и не
зависит от proxy-переменных операционной системы.

## Что уже учтено

- HTTP(S)-прокси с credentials отдельно от URL;
- явные `pooled` и `fresh_tunnel` стратегии соединения;
- безопасная диагностика зависимости ротации от нового proxy tunnel;
- HTTPS target по умолчанию;
- запрет loopback, private и link-local literal IP без opt-in;
- connect, headers, body timeouts и общий deadline;
- ограничение ответа до 10 MiB и ноль redirects;
- повторы только для идемпотентных методов;
- ограниченный `Retry-After`, backoff и correlation ID;
- тело ответа доступно коду, но не попадает в JSON-отчёт;
- путь, query, credentials и исходный текст transport error очищаются;
- `Proxy-Authorization` нельзя отправить целевому серверу;
- typed-блок `result.execution` одинаков с Python SDK и содержит route,
  quality, next action и опциональную оценку cost;
- опциональный Browser Route с exact allowlist, ручным approval, durable jobs
  и integrity-verified replay;
- офлайн-тесты не требуют настоящего прокси.

> Используйте решение только для систем и данных, на работу с которыми у вашей
> организации есть право.

## Запуск

Требуется Node.js `>=20.18.1`.

```bash
git clone https://github.com/smuuuzik-tech/proxy-use-cases.git
cd proxy-use-cases/integrations/node-production
npm ci
```

Передайте секреты через secret manager, CI/CD variables или окружение:

```bash
export B2B_PROXY_URL='http://proxy.example.net:8080'
export B2B_PROXY_USERNAME='account-name'
export B2B_PROXY_PASSWORD='secret-from-secret-manager'
export B2B_TARGET_URL='https://service.example/health'

npm exec -- andrey-proxy-node --pretty
```

`B2B_CONNECTION_MODE=pooled` переиспользует соединения и является значением по
умолчанию. `fresh_tunnel` создаёт новое соединение к прокси на каждую сетевую
попытку. Как измерить разницу и не публиковать exit IP:
[Стратегии соединения и ротация](../../docs/CONNECTION-STRATEGIES-AND-ROTATION.md).

Опциональная оценка стоимости одной сетевой попытки:

```bash
export B2B_ESTIMATED_COST_PER_ATTEMPT='0.002'
export B2B_COST_CURRENCY='USD'
```

Значения задаются только вместе. Без них SDK возвращает
`cost.basis=not_configured`.

## Использование в коде

```js
import { ProxyClient } from "./src/client.js";

const proxy = ProxyClient.fromEnv();

try {
  const result = await proxy.get(
    "https://service.example/api/items?page=1",
    { requestId: "inventory-sync-0001" },
  );
  console.log(result.execution.quality.outcome);
  if (!result.ok) throw new Error(JSON.stringify(result));
  const payload = result.json();
  console.log(payload.items.length);
} finally {
  await proxy.close();
}
```

Для независимых запросов режим можно задать явно:

```js
const proxy = new ProxyClient({
  proxyUrl: process.env.B2B_PROXY_URL,
  proxyUsername: process.env.B2B_PROXY_USERNAME,
  proxyPassword: process.env.B2B_PROXY_PASSWORD,
  connectionMode: "fresh_tunnel",
});
```

Не используйте `fresh_tunnel` как замену sticky-сессии в многошаговом процессе:
для него нужен session-aware endpoint поставщика.

`result.execution` типизирован в `client.d.ts`; тот же блок входит в
`JSON.stringify(result)`. Поля и правила ручной эскалации:
[Execution Contract](../../docs/EXECUTION-CONTRACT.md).

`POST` автоматически не повторяется. Потоковое тело также не повторяется. Если
target URL поступает от недоверенного пользователя, добавьте доменный allowlist
и сетевой egress control: клиент проверяет literal IP, но не выполняет DNS
resolution до передачи запроса прокси.

## Browser Route

Browser Route нужен только тогда, когда HTTP-клиента недостаточно для
разрешённой проверки. Он доступен через отдельный export:

```js
import { BrowserRouteClient } from "andrey-proxy-sdk-node/browser";
```

Playwright остаётся опциональной зависимостью:

```bash
npm install --no-save --package-lock=false playwright@1.61.0
npx playwright install chromium
```

Маршрут требует `routeApproved: true`, точного allowlist и отдельной приватной
artifact directory. Он не выполняет login, формы, POST/PUT/PATCH/DELETE или
автоматический переход к managed/AI.

Полная архитектура:
[Browser Route and Replay](../../docs/BROWSER-ROUTE-AND-REPLAY.md).

## Проверка настоящего прокси локально

Credentials не нужно отправлять в чат или передавать через argv:

```bash
cp acceptance.example.json acceptance.private.json
chmod 600 acceptance.private.json
# заполните файл локально
npm run acceptance:local
```

Runner проверяет HTTP и browser routes, optional exit-IP assertion, durable
manifest/events/report/receipt, replay и отсутствие secrets в текстовых
artifacts. Пошаговый план:
[Local Real Proxy Acceptance](../../docs/LOCAL-REAL-PROXY-ACCEPTANCE.md).

Чтобы сравнить `pooled` и `fresh_tunnel` на разрешённом JSON endpoint:

```bash
export B2B_ROTATION_TARGET_URL='https://authorized.example.net/identity'
export B2B_ROTATION_TARGET_LABEL='authorized identity endpoint'
export B2B_ROTATION_JSON_FIELD='ip'
npm exec -- andrey-proxy-rotation
```

Отчёт содержит только агрегаты и решение, без наблюдаемых IP и fingerprints.

## Проверка

```bash
npm test
npm run check
npm run pack:check
```

## English summary

Provider-neutral Node.js client for authorized B2B proxy workloads. It uses an
explicit Undici `ProxyAgent`, bounded idempotent retries, granular timeouts, an
overall deadline, response-size limits, correlation IDs, explicit pooled or
fresh-tunnel strategies, safe rotation diagnostics, and redacted results. An
optional manually approved Playwright route adds durable jobs and
integrity-verified offline replay.
