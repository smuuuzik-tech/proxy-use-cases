# Andrey Proxy Client для Node.js

Провайдер-независимый production-клиент Андрея Малышева для B2B-сервисов на
Node.js 20+. Решение использует программно настроенный `undici.ProxyAgent` и не
зависит от proxy-переменных операционной системы.

## Что уже учтено

- HTTP(S)-прокси с credentials отдельно от URL;
- HTTPS target по умолчанию;
- запрет loopback, private и link-local literal IP без opt-in;
- connect, headers, body timeouts и общий deadline;
- ограничение ответа до 10 MiB и ноль redirects;
- повторы только для идемпотентных методов;
- ограниченный `Retry-After`, backoff и correlation ID;
- тело ответа доступно коду, но не попадает в JSON-отчёт;
- путь, query, credentials и исходный текст transport error очищаются;
- `Proxy-Authorization` нельзя отправить целевому серверу;
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

## Использование в коде

```js
import { ProxyClient } from "./src/client.js";

const proxy = ProxyClient.fromEnv();

try {
  const result = await proxy.get(
    "https://service.example/api/items?page=1",
    { requestId: "inventory-sync-0001" },
  );
  if (!result.ok) throw new Error(JSON.stringify(result));
  const payload = result.json();
  console.log(payload.items.length);
} finally {
  await proxy.close();
}
```

`POST` автоматически не повторяется. Потоковое тело также не повторяется. Если
target URL поступает от недоверенного пользователя, добавьте доменный allowlist
и сетевой egress control: клиент проверяет literal IP, но не выполняет DNS
resolution до передачи запроса прокси.

## Проверка

```bash
npm test
npm run check
npm run pack:check
```

## English summary

Provider-neutral Node.js client for authorized B2B proxy workloads. It uses an
explicit Undici `ProxyAgent`, bounded idempotent retries, granular timeouts, an
overall deadline, response-size limits, correlation IDs, and redacted results.
