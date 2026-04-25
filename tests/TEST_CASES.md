# Natural Language Test Cases for FlowArchitect

Набор кейсов для сквозной проверки системы (NL → YAML → NiFi JSON).
Составлен 2026-04-14.

---

## Уровень 1 — Простая транспортировка

**TC-01. HTTP → File**
> "Каждые 5 минут забирай курсы валют с `https://api.exchangerate.host/latest?base=USD`, сохраняй ответ в файл `/data/rates/rates.json`"

**TC-02. File → File с фильтром**
> "Читай CSV-файлы из папки `/input/orders/`, оставляй только строки где поле `status` равно `COMPLETED`, пиши результат в `/output/completed_orders.csv`"

**TC-03. PostgreSQL → File**
> "Каждую ночь в 02:00 выгружай из таблицы `users` базы данных `analytics` всех пользователей зарегистрированных за последние 24 часа, сохраняй как JSON в `/reports/new_users.json`"

---

## Уровень 2 — Трансформация данных

**TC-04. Kafka → PostgreSQL**
> "Слушай топик `orders.created` в Kafka, парси JSON-сообщения, извлекай поля `order_id`, `user_id`, `amount`, `created_at` и вставляй строки в таблицу `orders` в PostgreSQL"

**TC-05. HTTP → Kafka**
> "Опрашивай REST API погоды `https://api.openweathermap.org/data/2.5/weather?q=Moscow` раз в 10 минут, публикуй raw JSON-ответ в Kafka-топик `weather.raw`"

**TC-06. PostgreSQL → Kafka с трансформацией**
> "Читай из таблицы `transactions` записи со статусом `PENDING` старше 1 часа, конвертируй каждую запись в JSON, публикуй в топик `transactions.overdue`, после успешной отправки обновляй статус на `NOTIFIED`"

---

## Уровень 3 — Сложные паттерны

**TC-07. Маршрутизация по содержимому**
> "Читай сообщения из Kafka-топика `events.all`. Если поле `type` равно `purchase` — пиши в PostgreSQL таблицу `purchases`. Если `type` равно `refund` — пиши в таблицу `refunds`. Всё остальное — в топик `events.unknown`"

**TC-08. S3 → PostgreSQL с обогащением**
> "Каждый час забирай JSON-файлы из S3-бакета `raw-logs`, для каждой записи добавляй поле `processed_at` с текущим временем, загружай в таблицу `event_log` в PostgreSQL"

**TC-09. Два источника → один сток**
> "Объединяй данные из двух Kafka-топиков: `users.created` и `users.updated`. Нормализуй оба формата к единой схеме `{user_id, email, timestamp, event_type}` и записывай в HDFS по пути `/warehouse/users/`"

---

## Уровень 4 — Граничные случаи

**TC-10. Минималистичный запрос**
> "Перекачай данные из Kafka в PostgreSQL"

Цель: проверить, какие параметры LLM подставляет по умолчанию (топик, таблица, порты).

**TC-11. Неполные данные источника**
> "Читай файлы из папки, загружай в базу"

Цель: устойчивость к расплывчатым запросам — должен либо уточнить, либо сгенерировать разумные заглушки.

**TC-12. Многошаговый сложный пайплайн**
> "Забирай данные о транзакциях из REST API банка каждые 30 секунд, фильтруй транзакции на сумму более 100 000 рублей, обогащай данные информацией о клиенте из PostgreSQL-таблицы `clients` по полю `client_id`, результат публикуй в Kafka-топик `high_value_transactions` и параллельно сохраняй в S3 бакет `compliance-archive` с партиционированием по дате"

---

## Что проверяем каждым кейсом

| TC  | Источник    | Сток              | Ключевая проверка                             |
|-----|-------------|-------------------|-----------------------------------------------|
| 01  | HTTP        | File              | Простейший happy path                         |
| 02  | File        | File              | Фильтрация в PIM                              |
| 03  | PostgreSQL  | File              | SQL-запрос + расписание                       |
| 04  | Kafka       | PostgreSQL        | Стандартный ETL                               |
| 05  | HTTP        | Kafka             | Polling → streaming                           |
| 06  | PostgreSQL  | Kafka             | Обновление источника после записи             |
| 07  | Kafka       | PostgreSQL×2 + Kafka | Routing/branching                          |
| 08  | S3          | PostgreSQL        | Добавление поля (enrichment)                  |
| 09  | Kafka×2     | HDFS              | Merge нескольких источников                   |
| 10  | Kafka       | PostgreSQL        | Минимальный input — умолчания LLM             |
| 11  | File        | DB                | Устойчивость к расплывчатым запросам          |
| 12  | HTTP        | Kafka + S3        | Сложный multi-sink + join с внешними данными  |

---

## Критерии прохождения

Для каждого кейса фиксируем:

1. **PCT (Platform Conformance Test)** — импортируется ли сгенерированный JSON в NiFi без ошибок
2. **Структурная корректность** — все процессоры соединены, нет висячих входов/выходов
3. **Семантическое соответствие** — пайплайн делает то, что описано в запросе (ручная проверка)
4. **Полнота параметров** — заполнены ли обязательные свойства процессоров (URL, topic, table, etc.)

---

## Связь с существующими fixtures

Кейсы TC-01, TC-04, TC-05 (HTTP, Kafka→PG, PG→Kafka, S3→HDFS) перекрываются с:
- `tests/fixtures/currency_http_to_file.json`
- `tests/fixtures/kafka_to_postgres.json`
- `tests/fixtures/postgres_to_kafka.json`
- `tests/fixtures/s3_to_hdfs.json`

TC-07 – TC-12 — новые сценарии, fixtures под них ещё не созданы.
