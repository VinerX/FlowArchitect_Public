# FlowArchitect

**Выпускная квалификационная работа** · ВШЭ, факультет информатики, математики и компьютерных наук, 2026  
**Автор:** Макаров Дмитрий · **Научный руководитель:** Бабкин Эдуард Александрович

---
<img width="1919" height="1041" alt="image" src="https://github.com/user-attachments/assets/cf987187-2831-4685-8205-6806fa0601ad" />
<img width="1920" height="1038" alt="image" src="https://github.com/user-attachments/assets/09ce1b04-adf1-41fd-8004-8dd9bfcf3971" />
<img width="903" height="886" alt="image" src="https://github.com/user-attachments/assets/28a34dd6-d7c5-433b-aece-14fa5ab010da" />



---

## Обзор

FlowArchitect автоматизирует создание конфигураций ETL-пайплайнов [Apache NiFi](https://nifi.apache.org/) из описаний на естественном языке с помощью LLM и модельно-ориентированной разработки (MDE).

**Исследовательская гипотеза:** Двухэтапный подход (NL → YAML → NiFi JSON) даёт меньше галлюцинаций и лучшую структурную целостность по сравнению с прямой генерацией (NL → JSON), так как промежуточный YAML (платформо-независимая модель) разделяет семантическое рассуждение и структурную сложность.

---

## MDA-пайплайн

Реализовано и оценивается три режима генерации:

| Режим | Путь | Описание |
|-------|------|----------|
| **0 — Прямой** | NL → LLM → NiFi JSON | Один вызов LLM; наибольший риск галлюцинаций |
| **1 — Адаптер** | NL → LLM → YAML → Адаптер → NiFi JSON | Режим по умолчанию; детерминированное преобразование PIM→PSM |
| **2 — LLM-to-LLM** | NL → LLM → YAML → LLM → NiFi JSON | Два вызова LLM; наибольшая гибкость |

**PIM (Platform-Independent Model):** YAML с абстрактным описанием пайплайна — источники, шаги обработки, приёмники, связи.  
**PSM (Platform-Specific Model):** NiFi JSON — процессоры, соединения, UUID, группы процессов.

---

## Архитектура

```
Ввод пользователя (чат)
  → ChatController → EventBus → Orchestrator
      → LLM (этап 1): NL → PIM (структурированный JSON/YAML)
      → Отображение YAML в редакторе

Пользователь нажимает "Сгенерировать NiFi Flow"
  → EventBus → Orchestrator
      → Парсинг и валидация YAML через Pydantic
      → NiFiAdapter.convert(Flow) → NiFi JSON   [Режим 1]
      → (или) вызов LLM → NiFi JSON             [Режим 2]
      → Отображение JSON в редакторе
```

Все компоненты общаются через потокобезопасный `EventBus` (паттерн слабых ссылок на подписчиков). Контроллеры никогда не вызывают сервисы напрямую.

---

## Структура проекта

```
FlowArchitect/
├── src/
│   ├── main.py                     # Точка входа
│   ├── adapters/
│   │   └── nifi_adapter.py         # PIM → NiFi JSON (правила + авторасстановка)
│   ├── controllers/                # MVC: обработчики UI-событий
│   ├── core/
│   │   ├── events.py               # Потокобезопасный EventBus
│   │   └── event_defines.py        # Константы имён событий
│   ├── domain/
│   │   ├── pim_model.py            # Pydantic-схема PIM (Flow, Resource, Step, Link)
│   │   └── nifi_schema.py          # Pydantic-схема NiFi
│   ├── handlers/
│   │   └── llm_engine.py           # Оркестрация LLM + маршрутизация провайдеров
│   ├── services/
│   │   └── orchestrator.py         # Основной MDA-пайплайн
│   └── ui/                         # Desktop GUI на PyQt6
├── config/
│   ├── api_presets.json.example    # Шаблон конфига провайдеров (скопируй и заполни ключи)
│   ├── settings.json               # Настройки среды выполнения (тема, активный пресет)
│   ├── PIM_structure.yaml          # Эталонный пример схемы PIM
│   └── prompts/                    # Шаблоны промптов для LLM
│       ├── system_architect.txt    # Промпт: NL → PIM
│       └── psm_nifi.txt            # Промпт: YAML → NiFi (Режим 2)
├── tests/
│   ├── unit/                       # Юнит-тесты адаптера (без API и NiFi)
│   ├── integration/                # E2E-тесты (нужны Gemini API + NiFi)
│   └── fixtures/                   # PIM JSON-фикстуры для 4 ETL-сценариев
├── scripts/
│   ├── run_adapter.py              # PIM → NiFi JSON (без LLM)
│   ├── run_nl_test.py              # Полный тест NL → NiFi
│   ├── import_and_report.py        # Импорт в NiFi + захват ошибок валидации
│   └── full_pipeline.py            # PIM → адаптер → импорт → отчёт (одна команда)
└── requirements.txt
```

---

## Быстрый старт

### Требования

- Python 3.11+
- Экземпляр Apache NiFi 1.x или 2.x (только для интеграционных тестов)
- Хотя бы один API-ключ LLM (Gemini, OpenAI, Groq или любой OpenAI-совместимый эндпоинт)

### Установка

```bash
git clone <repo-url>
cd FlowArchitect

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

### Настройка

```bash
# Скопируй шаблон конфига и заполни API-ключи
cp config/api_presets.json.example config/api_presets.json
# Отредактируй config/api_presets.json — вставь свои ключи
```

### Запуск приложения

```bash
cd src
python main.py
```

---

## CLI-инструменты (без GUI)

```bash
# PIM YAML/JSON → NiFi JSON  (без LLM и без NiFi)
python scripts/run_adapter.py tests/fixtures/kafka_to_postgres.json

# Полный автоматический тест: NL-описание → импорт в NiFi
python scripts/run_nl_test.py --preset "Google" --case kafka-to-postgres

# Импорт NiFi JSON в работающий NiFi, захват ошибок валидации
python scripts/import_and_report.py result.json --report errors.json

# Полный цикл: PIM-фикстура → адаптер → импорт в NiFi → отчёт об ошибках
python scripts/full_pipeline.py tests/fixtures/kafka_to_postgres.json --report errors.json
```

Учётные данные NiFi читаются только из переменных окружения:

```bash
export NIFI_URL=https://localhost:8443
export NIFI_USER=admin
export NIFI_PASS=password
```

---

## Запуск тестов

```bash
# Юнит-тесты — без токенов и без NiFi
pytest tests/unit/ -v

# Все тесты
pytest tests/ -v

# E2E-интеграция (нужны живой Gemini API + работающий NiFi)
set GEMINI_MODEL=gemini-2.0-flash    # Windows
pytest tests/integration/ -v -s
```

**Тестовые сценарии:**

| Сценарий | Описание |
|----------|----------|
| `currency-http-to-file` | REST API → файл |
| `kafka-to-postgres` | Kafka → PostgreSQL |
| `postgres-to-kafka` | PostgreSQL → Kafka |
| `s3-to-hdfs` | S3 → HDFS |

Интеграционные тесты автоматически пропускаются, если NiFi или LLM API недоступны.

---

## Метрики оценки

| Метрика | Описание |
|---------|----------|
| **PCT** (Platform Conformance Test) | Импортируется ли сгенерированный JSON в NiFi без ошибок? |
| **Функциональная корректность** | Выполняет ли импортированный поток ETL-задачу корректно? |
| **Снижение трудозатрат** | Время развёртывания с генератором vs. ручная настройка |

---

## Стек технологий

- **Python 3**, **PyQt6** — desktop GUI
- **Pydantic** — строгая валидация схем PIM и NiFi
- **PyYAML** — сериализация PIM
- **requests / openai SDK** — вызовы LLM API (без тяжёлых фреймворков — требование прозрачности для ВКР)
- **pytest** — юнит- и интеграционные тесты
- Поддерживаемые LLM-провайдеры: Google Gemini, OpenAI, Groq, Mistral, любой OpenAI-совместимый эндпоинт

---

## Лицензия

Академический проект — ВКР ВШЭ, 2026. Коммерческое использование не предусмотрено.
