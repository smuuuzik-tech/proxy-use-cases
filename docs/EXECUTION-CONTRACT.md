# Execution Contract: единый результат Python и Node.js

`execution` — версионированный provider-neutral блок результата запроса. Он
позволяет приложению, мониторингу и AI-ассистенту одинаково прочитать:

- какой маршрут действительно был выполнен;
- почему он был выбран;
- сколько потребовалось попыток;
- чем завершился запрос;
- что проверить дальше;
- какова оценочная стоимость, если команда явно настроила её.

Каноническая схема:
[`contracts/proxy-execution.schema.json`](../contracts/proxy-execution.schema.json).
Два SDK проверяются на одних и тех же
[fixtures](../contracts/fixtures/).

## Минимальное использование

Python:

```python
result = proxy.get("https://service.example/api/items")
execution = result.execution

if execution.route.next_action != "complete":
    send_to_observability(execution.to_dict())
```

Node.js / TypeScript:

```js
const result = await proxy.get("https://service.example/api/items");

if (result.execution.route.next_action !== "complete") {
  sendToObservability(result.execution);
}
```

`result.to_dict()` в Python и `JSON.stringify(result)` в Node.js включают тот же
блок `execution`. Старые top-level поля результата сохранены для обратной
совместимости.

## Структура

```json
{
  "schema_version": "1.0",
  "route": {
    "selected": "http_proxy",
    "reason": "configured_http_proxy",
    "next_action": "complete",
    "automatic_escalation": false,
    "manual_candidates": [
      "browser",
      "managed_unblocker",
      "ai_extraction"
    ]
  },
  "quality": {
    "outcome": "success",
    "attempts": 1,
    "retries": 0,
    "elapsed_ms": 184,
    "status_code": 200,
    "response_bytes": 17
  },
  "cost": {
    "basis": "not_configured",
    "currency": null,
    "unit_cost": null,
    "estimated_total": null
  }
}
```

### `route`

Текущие SDK выполняют только `http_proxy`. Они не запускают браузер, managed
unblocker или AI автоматически.

`manual_candidates` — лестница возможных классов решения, а не разрешение,
рекомендация поставщика или подтверждение законности target. Перед переходом
приложение должно проверить allowlist, договорные ограничения, бюджет и
политику обработки данных.

`next_action` имеет стабильные значения:

| Значение | Смысл |
|---|---|
| `complete` | Запрос завершён успешно |
| `review_policy_or_credentials` | Проверить доступ, proxy auth или target policy |
| `review_http_response` | Разобрать неуспешный HTTP-ответ |
| `review_retry_or_escalation` | Проверить retry budget и вручную решить вопрос об эскалации |
| `review_response_limit` | Пересмотреть ожидаемый размер ответа и лимит |
| `none` | Запрос остановлен вызывающей стороной |

### `quality`

`outcome` нормализует различия библиотек:

- `success`;
- `http_error`;
- `transport_error`;
- `timeout`;
- `aborted`;
- `response_limit`.

`attempts` включает первую попытку, `retries = max(0, attempts - 1)`.
`response_bytes` равен `null`, если безопасно прочитанное тело отсутствует.

### `cost`

SDK ничего не предполагает о тарифе. Без настройки он возвращает
`basis=not_configured` и `null` вместо выдуманной цены.

Если известна оценка одной попытки, настройте оба значения:

```bash
export B2B_ESTIMATED_COST_PER_ATTEMPT='0.002'
export B2B_COST_CURRENCY='USD'
```

`estimated_total = attempts × unit_cost`, поэтому это оценка стоимости сетевых
попыток, а не счёт поставщика и не стоимость успешного бизнес-результата. Для
сравнения пулов по стоимости успешного результата используйте
[Proxybench](../tools/proxybench/).

## Правила для AI и автоматизации

1. Проверяйте `schema_version` до интерпретации.
2. Не выводите следующий маршрут только из HTTP-кода.
3. Не выполняйте `manual_candidates` автоматически.
4. Не подставляйте отсутствующую стоимость.
5. Для анализа инцидента связывайте результат по `request_id`, но не добавляйте
   в контракт credentials, target path/query или тело ответа.
6. При `review_retry_or_escalation` сначала проверяйте уже исчерпанный retry
   budget, SLO и разрешённые маршруты.

## Совместимость

Добавление новых необязательных top-level полей результата не меняет
`schema_version`. Изменение значений, обязательных полей или их смысла требует
новой версии execution schema и новых cross-language fixtures.

## Проверка

```bash
node scripts/validate_execution_contract.mjs
cd integrations/python-production && python -m pytest
cd ../node-production && npm test
```

## English summary

The versioned `execution` block gives Python, Node.js, observability systems, and
AI assistants the same sanitized view of route, decision, attempts, outcome,
next action, and optional estimated cost. Escalation is always manual; candidate
routes are not authorization to access a target.
