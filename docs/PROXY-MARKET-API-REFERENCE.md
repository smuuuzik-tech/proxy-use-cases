# Proxy.Market API 1.1: технический аудит

Этот документ разбирает публичную OpenAPI-схему, а не поведение закрытой
реализации. Формулировка «не описано» означает отсутствие контракта в схеме,
а не утверждение, что возможность отсутствует на сервере.

Источники:

- [API Documentation](https://api.dashboard.proxy.market/docs);
- [OpenAPI 3.0 / API 1.1](https://api.dashboard.proxy.market/openapi/openapi.yaml).

Дата сверки: 23 июля 2026 года.

## Модель API

Базовый URL: `https://api.dashboard.proxy.market`.

Все 14 операций относятся к control-plane:

- каталог продуктов и цен;
- покупка и продление;
- выдача реквизитов прокси;
- управление traffic packages;
- выбор географии;
- статистика потребления.

Фактический трафик к целевым сайтам идёт не через этот API, а через
HTTP/SOCKS-реквизиты, полученные методом списка прокси.

## Авторизация

Схема использует path parameter:

```text
/dev-api/.../{api_key}
```

В `components.securitySchemes` и на верхнем уровне `security` механизм
авторизации не объявлен. Это ухудшает генерацию клиентов и делает полную
маскировку URL обязательной.

Минимальный production-контроль:

1. ключ хранится только в secret manager;
2. сервис управления ресурсами получает его на runtime;
3. access-логи редактируют секретный path segment до записи;
4. URL запроса не попадает в exception, trace span и audit event;
5. HTTP body списка прокси не логируется;
6. ключ регулярно ротируется и имеет минимальный круг потребителей.

## Карта endpoint-ов

### Аккаунт и список прокси

| Метод | Endpoint | Назначение | Важные поля |
|---|---|---|---|
| `GET` | `/dev-api/balance/{api_key}` | Текущий баланс | ответ `balance: number` |
| `POST` | `/dev-api/list/{api_key}` | Полученные прокси | `type`, `proxy_type`, pagination, `package_id`, `order_id` |

`list` использует `POST`, хотя операция является чтением. Фильтры:

- `type`: `ipv4`, `ipv4-shared`, `ipv6`, `all`;
- `proxy_type`: `mobile`, `server`, `resident`; по описанию не нужен при
  наличии `package_id`;
- `page`, `page_size`;
- `sort`: `0` — сначала новые, `1` — сначала старые;
- `package_id`, `order_id`.

Ответ может содержать:

- `ip`, `ip_out`, HTTP/SOCKS ports;
- `login`, `password`;
- `attached_ip`;
- даты покупки и окончания;
- параметры ротации;
- `change_ip_link`.

Это секретный ответ. Даже полезная для эксплуатации ссылка `change_ip_link`
может предоставлять действие без повторной авторизации и должна обрабатываться
как credential.

### Каталог

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/dev-api/v2/products/{api_key}` | Поиск продуктов и ценовых ступеней |
| `GET` | `/dev-api/v2/purposes/{api_key}` | Список назначений |

Фильтры продуктов:

- `country`;
- `productType`;
- `proxyType`;
- `duration`;
- `page`, `perPage`.

Продукт содержит `id`, страну, параметры ротации, скорость, типы и массив
`prices`. У цены есть `productId`, минимальное количество `count`, `price` и
`duration`.

Перед покупкой нельзя жёстко прописывать цену в коде. Нужно получить каталог,
найти точную комбинацию продукта/срока/количества, сохранить снимок решения и
только затем запускать approval.

### Покупка и продление

| Метод | Endpoint | Состояние | Основные поля |
|---|---|---|---|
| `POST` | `/dev-api/v2/buy-proxies/{api_key}` | Актуальный V2-путь покупки | `productId`, `duration`, `count`, `promoCode` |
| `POST` | `/dev-api/buy-proxy/{api_key}` | Legacy-покупка | вложенный `PurchaseBilling` |
| `POST` | `/dev-api/prolong/{api_key}` | Продление | вложенный `ProlongationForm` |

V2 допускает `duration`: `1`, `3`, `5`, `7`, `10`, `14`, `20`, `30`, `60`,
`90`, `180`, `360`.

Legacy-покупка:

- `count`;
- `duration`: `30`, `60`, `90`, `180`, `360`;
- `type`: `100` для IPv4, `101` для IPv6;
- `country`: в enum схемы указано только `ru`;
- `promocode`;
- `speed`: `1`, `2`, `3`, по описанию только для IPv6.

Продление принимает `duration`, `promocode` и строку proxy IDs через запятую.

Ответы покупки могут содержать `success`, `balance`, `code: LOW_BALANCE` и
`order_id`. Клиент должен проверять JSON, а не только HTTP `200`.

### Трафик и пакеты

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/dev-api/v2/traffic-prices/{api_key}` | Ступени цены за объём |
| `POST` | `/dev-api/v2/buy-traffic/{api_key}` | Покупка трафика |
| `GET` | `/dev-api/v2/packages/{api_key}` | Список пакетов |
| `GET` | `/dev-api/v2/traffic-statistics/{api_key}` | Расход за период |

Цена трафика содержит `traffic` в GB и `price`. Покупка принимает объём в GB и
опциональный `promoCode`.

Пакет содержит:

- `id`, `name`;
- `expires_at` как Unix timestamp;
- `used` в байтах;
- `total` в байтах, но поле может отсутствовать при `prepaid: false`;
- `proxies_count`, `is_active`, `prepaid`.

Для PayAsYouGo нельзя рассчитывать utilization как `used / total`, не проверив
наличие `total`.

Статистика требует:

- `proxy_type`: `resident`, `mobile`, `server`;
- `from`, `to`;
- опциональный `package_id`.

Каждый bucket содержит Unix timestamp `t` и `traffic` в байтах; `total` также
задан в байтах.

### География и создание прокси в пакете

| Метод | Endpoint | Назначение |
|---|---|---|
| `GET` | `/dev-api/v2/package/countries/{api_key}` | Доступные страны |
| `GET` | `/dev-api/v2/package/regions-and-cities/{api_key}` | Регионы и города страны |
| `POST` | `/dev-api/v2/package/create-proxy/{api_key}` | Создание прокси в пакете |

Создание принимает:

- `packageId`;
- `country`;
- `rotation`;
- опциональные `regionId`, `cityId`;
- `ipAuth` — IP/подсети через запятую.

По описанию create-endpoint:

- `-1` — sticky session;
- `0` — ротация на каждый запрос;
- `1..60` — каждые N минут.

При этом в ответе `list.rotation_settings.rotate` значение `0` описано как
«ротация отключена». Это контрактная неоднозначность. Нельзя переносить
семантику `rotation` из create-запроса на поле `rotate` в list-ответе без
отдельной нормализации и подтверждения фактического поведения.

Ответ `200` для create-proxy не имеет документированной JSON-схемы. После
создания нужно повторно запросить ресурсы пакета, а не ожидать обязательный ID
в теле ответа.

## Ошибки и семантика результата

Схема повторяет три основных класса:

- `400` с объектом `message`;
- `403` с `name`, `message`, `code`, `status`;
- `200` с business-полями `success`, `code`, `balance`, иногда `order_id`.

Практическая классификация:

| Класс | Поведение клиента |
|---|---|
| Локальная валидация | Не отправлять запрос |
| `400` | Исправить данные, не повторять без изменения |
| `403` | Остановить поток, проверить/ротировать ключ |
| Timeout на чтении | Допустим ограниченный повтор по политике |
| Timeout на покупке/продлении | Не повторять автоматически |
| `200` + `success: false` | Обработать как business error |
| Не-JSON ответ | Считать protocol/upstream error |

В опубликованной схеме не описаны `429`, `5xx` и единая модель ошибок. Поэтому
retry policy следует считать внутренней и консервативной, пока провайдер не
даст отдельный контракт.

## Идемпотентность и финансовый контроль

В схеме не описан заголовок или поле idempotency key. Это особенно важно для:

- покупки прокси;
- покупки трафика;
- продления;
- создания прокси в пакете.

Безопасный паттерн:

1. внутренний оркестратор создаёт immutable intent;
2. policy engine проверяет лимит суммы, количества и срока;
3. человек или отдельный approval-сервис подтверждает intent;
4. worker выполняет один запрос без transport retry;
5. результат и `order_id` связываются с intent;
6. при неоднозначном исходе запускается reconciliation, а не повторная покупка.

Для B2B полезны внутренние лимиты:

- максимум единиц за одну операцию;
- дневной денежный бюджет;
- разрешённые типы и страны;
- отдельный доступ к promo codes;
- запрет legacy-покупки для новых систем;
- обязательный dual control выше установленного порога.

## Несогласованности OpenAPI-схемы

При генерации SDK нужно учитывать:

1. `api_key` описан как обычный path parameter, а не security scheme.
2. У request body почти нет массивов `required`, хотя примеры `400` говорят об
   обязательных полях.
3. `hasRotation` имеет тип boolean, но строковый пример `'false'`.
4. `traffic-prices.price` имеет тип number/float, но строковый пример `'300'`.
5. `packages.expires_at` имеет integer type, но строковый example.
6. Денежные поля не указывают валюту и правила decimal precision.
7. Форматы дат и timezone заданы описаниями/примерами, а не `format`.
8. `products.speed`, `rotationPeriod`, `totalOver` не имеют достаточной
   семантики и единиц.
9. В V2 остаётся смешение camelCase, snake_case и legacy-вложенных форм.
10. Для create-proxy отсутствует response schema.
11. Не описаны rate limit, request ID, pagination maxima, SLA и version
    deprecation policy.
12. Значение `0` для rotation имеет разную семантику в create и list.

Из-за этого полностью сгенерированный SDK без ручной валидации будет слишком
оптимистичным. Клиент в репозитории задаёт обязательность и диапазоны на своей
стороне, но не пытается угадывать неописанные единицы или валюту.

## B2B-архитектура

Разделите полномочия:

| Компонент | Доступ |
|---|---|
| Catalog reader | products, purposes, prices |
| Finance/Procurement worker | buy/prolong по approval |
| Provisioning worker | packages, geo, create |
| Runtime workload | только выданные HTTP/SOCKS credentials |
| Observability | агрегированные метрики без URL и credentials |

Не отдавайте приложению, которому нужен только proxy route, ключ от
control-plane. Оно не должно иметь возможность покупать трафик или создавать
ресурсы.

## Наблюдаемость

Безопасные поля события:

- внутренний operation ID;
- тип операции;
- HTTP status;
- business code;
- duration;
- число элементов;
- результат reconciliation.

Условно допустимые после оценки:

- `order_id`, `package_id`, `product_id`;
- страна и тип продукта;
- агрегированный traffic.

Запрещённые в обычных логах:

- API key и полный URL;
- `login`, `password`;
- `change_ip_link`;
- `attached_ip`, `ipAuth`;
- необработанный ответ `list`.

## Production checklist

- [ ] Ключ хранится в secret manager и не попадает в URL-логи.
- [ ] Control-plane отделён от runtime workloads.
- [ ] Покупки проходят approval и budget policy.
- [ ] Для mutation отключён автоматический retry.
- [ ] Реализован reconciliation неоднозначных результатов.
- [ ] `success` и `code` проверяются вместе с HTTP status.
- [ ] Сырые proxy credentials не логируются.
- [ ] Пагинация ограничена внутренними лимитами.
- [ ] Денежные значения нормализуются после уточнения валюты и precision.
- [ ] Контрактные тесты выполняются на отдельном тестовом аккаунте.
- [ ] OpenAPI-схема регулярно сравнивается с зафиксированной версией.
