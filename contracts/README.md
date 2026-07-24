# Машиночитаемые контракты

В этой папке находятся стабильные форматы обмена между SDK, сервисами,
наблюдаемостью и AI-ассистентами.

- [`proxy-execution.schema.json`](proxy-execution.schema.json) — JSON Schema
  блока `execution`, одинакового для Python и Node.js;
- [`fixtures/execution-success.json`](fixtures/execution-success.json) —
  успешный запрос без настроенной оценки стоимости;
- [`fixtures/execution-timeout.json`](fixtures/execution-timeout.json) —
  исчерпанный timeout budget с оценкой стоимости попыток.

Контракт не содержит proxy endpoint, credentials, полный target URL, тело ответа
или исходный текст сетевой ошибки. Версия схемы меняется только при изменении
машиночитаемой семантики.

Подробное описание полей и правил эскалации:
[Execution Contract](../docs/EXECUTION-CONTRACT.md).
