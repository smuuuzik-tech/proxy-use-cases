# Прокси на практике

[English](README.en.md)

Проверенные кейсы, запускаемые интеграции, диагностика и методики тестирования прокси для реальных задач.

Материалы подготовлены Андреем и рассчитаны на разработчиков, технических руководителей и команды, которым нужен воспроизводимый результат, а не просто список настроек.

## Начните с задачи

| Задача | Материал | Статус |
|---|---|---|
| Проверить подключение и внешний IP | Быстрый старт с cURL | Готовится |
| Подключить прокси к Python | Python Requests | Готовится |
| Подключить прокси к браузерной автоматизации | Playwright | Готовится |
| Выбрать ротацию или фиксированную сессию | Rotation vs sticky sessions | В плане |
| Исправить ошибку авторизации | 407 Proxy Authentication Required | В плане |
| Проверить сайт из другого региона | Regional testing | В плане |

## Что будет в репозитории

```text
quickstarts/
integrations/
  curl/
  python-requests/
  node-fetch/
  playwright/
  selenium/
  scrapy/
use-cases/
  regional-testing/
  seo-monitoring/
  ad-verification/
  public-data-collection/
  price-monitoring/
guides/
  rotation-vs-sticky/
  proxy-types/
  geo-targeting/
  security-and-ethics/
troubleshooting/
  407/
  timeouts/
  tls/
  session-rotation/
benchmarks/
  methodology/
templates/
docs/
```

## Принципы

- Примеры используют стандартные переменные `PROXY_URL`, `PROXY_USER` и `PROXY_PASSWORD`.
- Реальные пароли, токены и адреса клиентов никогда не публикуются.
- У каждого примера есть ожидаемый результат и дата последней проверки.
- Benchmark-материалы раскрывают регион, выборку, число попыток, retry policy и ограничения.
- Кейсы предназначены только для законного использования и учитывают правила целевых ресурсов.
- Если пример тестировался с Proxy.Market, это отмечается явно; код по возможности остаётся совместимым с другими провайдерами.

## Запланированные интеграции

- cURL
- Python Requests и HTTPX
- Node.js Fetch и Axios
- Playwright
- Selenium
- Scrapy
- n8n

## Разобрать задачу

Нужна схема под конкретную географию, объём, стек и требования к качеству?

**[Обсудить задачу и подобрать решение](https://b2b.proxy.market/?utm_source=github&utm_medium=repository&utm_campaign=proxy-use-cases&utm_content=readme-ru)**

## Участие

Предложения новых сценариев и сообщения об ошибках приветствуются. Перед публикацией материалов ознакомьтесь с [правилами участия](CONTRIBUTING.md) и [политикой безопасности](SECURITY.md).
