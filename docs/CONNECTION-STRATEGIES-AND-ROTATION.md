# Стратегии соединения и проверка ротации

Этот материал нужен, когда прокси успешно отвечает, но поведение exit IP
зависит от того, переиспользуется ли соединение с прокси. Он относится к
[Andrey Proxy Client для Node.js](../integrations/node-production/) и не
зависит от конкретного поставщика.

## Два явных режима

| Режим | Что делает SDK | Когда выбирать |
|---|---|---|
| `pooled` | Переиспользует один `ProxyAgent` и его соединения | API, workers и высокая нагрузка; это безопасный режим по умолчанию |
| `fresh_tunnel` | Создаёт и закрывает отдельный `ProxyAgent` на каждую сетевую попытку | Независимые запросы, когда проверка показала связь ротации с новым proxy tunnel |

`fresh_tunnel` не означает «новый IP гарантирован». Он только создаёт новое
соединение к прокси для каждой попытки. Реальную политику определяет поставщик:
аккаунт, endpoint, параметры сессии, регион и состояние пула.

У нового tunnel есть цена: дополнительные TCP/TLS handshakes, более высокая
задержка и большая нагрузка на прокси. Поэтому SDK не включает этот режим
автоматически.

## Настройка

Через окружение:

```bash
export B2B_CONNECTION_MODE=pooled
```

Или в коде:

```js
import { ProxyClient } from "andrey-proxy-sdk-node";

const proxy = new ProxyClient({
  proxyUrl: process.env.B2B_PROXY_URL,
  proxyUsername: process.env.B2B_PROXY_USERNAME,
  proxyPassword: process.env.B2B_PROXY_PASSWORD,
  connectionMode: "fresh_tunnel",
});
```

`result.connectionMode` и `result.toJSON().connection_mode` фиксируют реально
использованный режим. Credentials, target path и исходный текст transport
ошибки в JSON не попадают.

## Безопасная диагностика ротации

Диагностика выполняет одинаковое число последовательных запросов в `pooled` и
`fresh_tunnel`, извлекает разрешённое поле из JSON и сравнивает только его
короткие SHA-256 fingerprints в памяти. В отчёт попадают количества, latency и
решение — сами IP, значения поля и fingerprints не выводятся.

Используйте только свой или явно разрешённый HTTPS endpoint:

```bash
export B2B_ROTATION_TARGET_URL='https://authorized.example.net/identity'
export B2B_ROTATION_TARGET_LABEL='authorized identity endpoint'
export B2B_ROTATION_JSON_FIELD='ip'
export B2B_ROTATION_SAMPLES_PER_MODE='10'

npm exec -- andrey-proxy-rotation
```

Для вложенного ответа допустим dotted path, например `network.ip`. Диагностика
ограничена 3–50 запросами на режим, отключает retry и никогда не меняет
production-настройку сама.

Пример безопасной части отчёта:

```json
{
  "automatic_mode_change": false,
  "modes": {
    "pooled": {
      "requests": 10,
      "successful": 10,
      "unique_observations": 2
    },
    "fresh_tunnel": {
      "requests": 10,
      "successful": 10,
      "unique_observations": 10
    }
  },
  "comparison": {
    "fresh_tunnel_unique_observation_gain": 8,
    "fresh_tunnel_p50_latency_delta_ms": 818,
    "fresh_tunnel_p50_latency_ratio": 3.2978
  },
  "decision": {
    "connection_sensitivity": "connection_sensitive_rotation",
    "independent_request_mode": "fresh_tunnel",
    "multi_step_session": "provider_sticky_endpoint_required"
  }
}
```

## Как читать решение

| `connection_sensitivity` | Значение |
|---|---|
| `connection_sensitive_rotation` | Новый tunnel дал заметно больше уникальных наблюдений |
| `high_rotation_in_both_modes` | Pooling уже не мешает ротации; оставьте `pooled` |
| `stable_or_provider_sticky` | Оба режима сохранили одно наблюдение |
| `mixed_rotation` | Результат неоднозначен; увеличьте контролируемую выборку |
| `insufficient_evidence` | Есть неуспешные запросы; сначала разберите ошибки |

`independent_request_mode` относится только к независимым идемпотентным
запросам. Для login flow, корзины, многошагового API или другой связанной
сессии нужен отдельный sticky endpoint или session token поставщика. Смена
tunnel внутри такого процесса обычно разрушает continuity.

`comparison` помогает увидеть цену решения: прирост уникальных наблюдений,
абсолютную разницу медианной задержки и отношение p50 `fresh_tunnel` к
`pooled`. Значения описывают только текущую выборку и не являются SLO.

## Что проверять перед production

1. Повторить диагностику в нужном регионе и в то же время суток, что workload.
2. Сравнить success rate и p95 обоих режимов на одинаковом endpoint.
3. Для `fresh_tunnel` отдельно проверить рост latency и стоимость результата.
4. Для многошаговой операции проверить continuity на sticky endpoint.
5. Зафиксировать выбранный режим в конфигурации и наблюдаемости.

Для длительной статистики используйте
[Proxy Healthcheck](../tools/proxy-healthcheck/), а для сравнения пулов —
[Proxybench](../tools/proxybench/).

## English summary

The Node.js client exposes `pooled` and `fresh_tunnel` connection modes. A safe
rotation diagnostic compares both modes using aggregate counts only; raw exit
values and fingerprints are never reported. A fresh tunnel can improve
per-request rotation but adds latency and does not replace a provider-supported
sticky endpoint for multi-step sessions.
