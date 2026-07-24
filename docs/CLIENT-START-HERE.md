# Настройка прокси для клиента: начните здесь

Эту страницу можно отправить разработчику, DevOps/SRE или техническому
руководителю. Все основные компоненты provider-neutral и работают со стандартным
HTTP(S)- или SOCKS-прокси независимо от поставщика.

Автор и сопровождающий решений — Андрей Малышев.

## Самый быстрый путь для Python

Установите Andrey Proxy SDK:

```bash
python -m pip install \
  "git+https://github.com/smuuuzik-tech/proxy-use-cases.git#subdirectory=integrations/python-production"
```

Передайте доступы через secret manager или переменные окружения:

```bash
export B2B_PROXY_URL='http://proxy.example.net:8080'
export B2B_PROXY_USERNAME='client-account'
export B2B_PROXY_PASSWORD='secret-from-secret-manager'
```

Добавьте запрос:

```python
from proxy_b2b_client import ProxyClient

with ProxyClient.from_env() as proxy:
    result = proxy.get(
        "https://service.example/api/health",
        request_id="client-smoke-test",
    )

if not result.ok:
    raise RuntimeError(result.to_dict())
```

SDK уже ограничивает таймауты и повторы, не следует системному `NO_PROXY`,
маскирует путь, query и credentials в результате и не повторяет опасные
неидемпотентные запросы.

`result.execution` показывает единым форматом выполненный маршрут, число
попыток, качество, безопасное следующее действие и оценку стоимости, если она
настроена. Описание:
[Execution Contract](EXECUTION-CONTRACT.md).

## Самый быстрый путь для Node.js

```bash
git clone https://github.com/smuuuzik-tech/proxy-use-cases.git
cd proxy-use-cases/integrations/node-production
npm ci
```

```js
import { ProxyClient } from "./src/client.js";

const proxy = ProxyClient.fromEnv();
try {
  const result = await proxy.get("https://service.example/api/health", {
    requestId: "client-smoke-test",
  });
  if (!result.ok) throw new Error(JSON.stringify(result));
} finally {
  await proxy.close();
}
```

Node.js-клиент использует явный Undici `ProxyAgent`, отключает redirects,
ограничивает timeout, размер ответа и повторы, а также не выводит target path,
query или исходный transport error. Формат `result.execution` совпадает с
Python SDK.

## Если первый запрос не работает

1. Проверьте формат подключения через [cURL quickstart](../quickstarts/curl/).
2. Получите безопасный классифицированный отчёт через
   [Proxy Diagnostics](../tools/proxy-diagnostics/).
3. Для постоянной эксплуатации подключите
   [Proxy Healthcheck](../tools/proxy-healthcheck/).
4. Если нужно выбрать между несколькими пулами, сравните одинаковые отчёты через
   [Proxybench](../tools/proxybench/).

## Если нужно выбрать схему

- Sticky или rotating: [Session Strategy Analyzer](../labs/session-strategy/).
- Сравнение качества и стоимости пулов:
  [Proxybench](../tools/proxybench/).
- Production Python: [Andrey Proxy SDK](../integrations/python-production/).
- Production Node.js:
  [Andrey Proxy Client](../integrations/node-production/).
- Региональная проверка сайта:
  [Regional Web QA](../use-cases/regional-web-qa/).
- Архитектура и SLO:
  [B2B reference architecture](B2B-REFERENCE-ARCHITECTURE.md) и
  [SLO/runbook](B2B-SLO-AND-RUNBOOK.md).

## Что прислать для совместной настройки

Не присылайте пароли и токены. Достаточно:

- язык и среда выполнения;
- целевой публичный сервис;
- объём и параллельность;
- страны и требования к сессиям;
- коды ошибок без секретов;
- желаемые success rate, p95 и стоимость успешного результата.

Если вы ещё не знаете, какой раздел нужен, откройте
[карту выбора решения](CHOOSE-A-SOLUTION.md).

[Передать контекст Андрею](https://andrey-proxy-advisor-private.vercel.app/?case=scale&utm_source=github&utm_medium=client_guide&utm_campaign=b2b_proxy_sdk#contact)
или [выбрать подходящий кейс](https://andrey-proxy-advisor-private.vercel.app/github?utm_source=github&utm_medium=client_guide&utm_campaign=b2b_proxy_sdk).
