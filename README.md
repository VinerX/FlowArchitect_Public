# FlowArchitect

**Выпускная квалификационная работа** · НИУ ВШЭ, факультет информатики, математики и компьютерных наук, 2026  
**Автор:** Макаров Дмитрий · **Научный руководитель:** Бабкин Эдуард Александрович

FlowArchitect — desktop-приложение на PyQt6 для генерации ETL-потоков Apache NiFi из описания на естественном языке. Основной сценарий работы проходит через GUI: пользователь формулирует задачу в чате, получает промежуточную YAML-модель, редактирует ее при необходимости и затем конвертирует в NiFi JSON.
---
<img width="1919" height="1041" alt="image" src="https://github.com/user-attachments/assets/cf987187-2831-4685-8205-6806fa0601ad" />
<img width="1920" height="1038" alt="image" src="https://github.com/user-attachments/assets/09ce1b04-adf1-41fd-8004-8dd9bfcf3971" />
<img width="903" height="886" alt="image" src="https://github.com/user-attachments/assets/28a34dd6-d7c5-433b-aece-14fa5ab010da" />



---

Исследовательская гипотеза проекта: двухэтапная схема `NL → YAML → NiFi JSON` снижает число галлюцинаций LLM и повышает структурную корректность по сравнению с прямой генерацией `NL → JSON`.

---

## Что делает приложение

- принимает текстовое описание ETL-задачи в чат-интерфейсе;
- строит PIM-модель в YAML как промежуточное представление;
- конвертирует YAML в NiFi JSON несколькими режимами;
- позволяет просматривать, редактировать, сохранять и импортировать результат в NiFi;
- хранит историю сессий и базовую статистику по генерациям.

## GUI-first workflow

1. Пользователь описывает поток в чате.
2. LLM строит PIM-модель, которая открывается в редакторе YAML.
3. Пользователь при необходимости правит YAML и заполняет плейсхолдеры.
4. Приложение генерирует NiFi JSON через адаптер или LLM-режим.
5. JSON можно сохранить или отправить в NiFi напрямую из интерфейса.

## Режимы генерации

| Режим | Путь | Назначение |
|------|------|------------|
| `0 — Direct` | `NL → LLM → NiFi JSON` | прямой вызов LLM, самый рискованный по галлюцинациям |
| `1 — Adapter` | `NL → LLM → YAML → Adapter → NiFi JSON` | основной режим, детерминированное PIM→PSM-преобразование |
| `2 — LLM×2` | `NL → LLM → YAML → LLM → NiFi JSON` | гибкий двухшаговый режим |
| `3 — Adapter+LLM` | `NL → LLM → YAML → Adapter → LLM corrector` | адаптер с последующей LLM-коррекцией JSON |

**PIM (Platform-Independent Model)** — YAML с абстрактным описанием источников, шагов и приемников.  
**PSM (Platform-Specific Model)** — NiFi JSON с процессорами, связями, UUID и группами процессов.

---

## Интерфейс приложения

- **Chat panel** — основной ввод задач и получение сервисных сообщений.
- **Code editor** — вкладки `PIM — YAML` и `PSM — NiFi JSON` с подсветкой синтаксиса.
- **History panel** — список сессий, переименование, удаление и простая аналитика.
- **Placeholder panel** — контроль `{{PLACEHOLDER}}` перед импортом в NiFi.
- **Settings / Stage Providers** — настройка провайдеров LLM по этапам и параметров подключения.

## Архитектура

```text
Пользовательский запрос в чате
  → ChatController
  → EventBus
  → Orchestrator
  → LLM: NL → PIM
  → YAML в редакторе

Команда генерации NiFi Flow
  → EventBus
  → Orchestrator
  → валидация YAML через Pydantic
  → Adapter или LLM
  → NiFi JSON в редакторе
  → опционально импорт в NiFi
```

Компоненты связаны через потокобезопасный `EventBus`, а не через прямые вызовы контроллеров и сервисов.

---

## Быстрый старт

### Требования

- Python 3.11+
- хотя бы один API-ключ LLM-провайдера;
- Apache NiFi нужен только для импорта и интеграционных тестов.

### Установка

```powershell
git clone <repo-url>
cd FlowArchitect

python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Настройка

Файл `config/api_presets.json` уже находится в репозитории. Если нужен чистый шаблон, можно взять `config/api_presets.json.example` и заполнить свои ключи и модели.

Также проверь `config/settings.json`, если нужно заранее задать тему, активный пресет или параметры NiFi.

### Запуск GUI

```powershell
python -m src.main
```

После запуска основной рабочий сценарий такой:

1. Выбрать провайдера в кнопке `Provider` или через `Settings`.
2. Ввести задачу в чат.
3. Проверить YAML во вкладке `PIM`.
4. Нажать нужный режим генерации JSON.
5. При необходимости сохранить результат или отправить его в NiFi кнопкой `→ NiFi`.

---

## Структура проекта

```text
src/
  main.py                  # точка входа GUI
  controllers/             # обработчики UI-событий
  services/orchestrator.py # основной MDA pipeline
  adapters/nifi_adapter.py # rule-based PIM → NiFi JSON
  domain/                  # Pydantic-модели PIM и NiFi
  handlers/llm_engine.py   # вызовы LLM и маршрутизация провайдеров
  ui/                      # PyQt6-интерфейс

config/
  api_presets.json         # пресеты провайдеров
  settings.json            # runtime-настройки
  prompts/                 # шаблоны prompt'ов
  PIM_structure.yaml       # пример промежуточной модели

tests/
  unit/                    # unit-тесты адаптера
  integration/             # e2e и NiFi-интеграция
  fixtures/                # готовые PIM-сценарии

scripts/
  run_adapter.py
  run_llm_fixture.py
  import_and_report.py
  full_pipeline.py
```

## Куда смотреть в коде

- `src/services/orchestrator.py` — вся цепочка NL → PIM → PSM.
- `src/adapters/nifi_adapter.py` — детерминированная генерация NiFi JSON.
- `src/domain/pim_model.py` — схема промежуточной модели.
- `src/ui/main_window.py` — компоновка основного окна.
- `src/ui/code_editor.py` — режимы генерации, вкладки YAML/JSON и импорт в NiFi.

---

## CLI-скрипты

CLI в этом проекте вспомогательный. Он нужен для отладки адаптера, воспроизведения экспериментов и интеграционных прогонов без GUI.

```powershell
# PIM JSON/YAML → NiFi JSON без LLM
python scripts/run_adapter.py tests/fixtures/kafka_to_postgres.json

# Повторный прогон по сохраненному ответу LLM
python scripts/run_llm_fixture.py --llm-response saved_llm_output.json --out result.json

# Импорт JSON в NiFi и сохранение отчета об ошибках
python scripts/import_and_report.py result.json --report errors.json

# Полный цикл fixture → adapter → import → report
python scripts/full_pipeline.py tests/fixtures/kafka_to_postgres.json --report errors.json
```

Подробный CLI workflow вынесен в `docs/cli_testing.md`.

## Тесты

```powershell
# unit-тесты без токенов и без NiFi
pytest tests/unit/test_adapter_unit.py -v

# весь набор
pytest tests/ -v

# интеграционные тесты
$env:GEMINI_MODEL = "gemini-2.0-flash"
pytest tests/integration/ -v -s
```

Основные сценарии: `currency-http-to-file`, `kafka-to-postgres`, `postgres-to-kafka`, `s3-to-hdfs`.

## Технологии

- Python 3.12
- PyQt6
- Pydantic 2
- PyYAML
- requests / openai SDK
- pytest

Поддерживаются Google Gemini, OpenAI, Groq и OpenAI-совместимые endpoint'ы.

## Исследовательский контекст

Проект оформляет и проверяет MDE-подход к генерации конфигураций Apache NiFi. Ключевая идея — вынести семантическое описание потока в более компактный и редактируемый YAML-слой, а структурную сложность NiFi JSON обрабатывать отдельно.

Оцениваемые метрики:

- `PCT` — импортируется ли JSON в NiFi без ошибок;
- функциональная корректность потока;
- снижение трудозатрат по сравнению с ручной настройкой.

## Лицензия

Академический проект в рамках ВКР НИУ ВШЭ. Коммерческое использование не предполагается.
