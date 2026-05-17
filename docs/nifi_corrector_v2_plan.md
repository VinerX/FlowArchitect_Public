# План: NiFiCorrector v2

## Зачем менять текущий подход

Сейчас `NiFiCorrector` работает как constrained full rewrite:
- на вход получает весь adapter-generated NiFi JSON;
- по промпту не должен менять UUID, bundle, типы процессоров и структуру;
- на выходе все равно возвращает весь JSON целиком.

Это создает исследовательский и инженерный риск:
- модель может внести лишние семантические изменения вне реальной ошибки;
- результаты `mode 3` менее воспроизводимы, чем у rule-based adapter;
- сложнее доказать, что LLM действительно делала точечную коррекцию, а не частичную перегенерацию.

## Цель v2

Сделать `NiFiCorrector` patch-based:
- LLM не переписывает весь документ;
- LLM возвращает только список точечных правок;
- применение правок делает код;
- валидность структуры гарантируется приложением, а не только инструкцией в промпте.

## Целевой формат ответа модели

Модель должна возвращать JSON-список правок примерно такого вида:

```json
{
  "edits": [
    {
      "target_type": "processor",
      "target_name": "Write to PostgreSQL",
      "property": "Table Name",
      "old_value": "orders",
      "new_value": "public.orders",
      "reason": "PutDatabaseRecord should target the fully qualified table name from the PIM"
    }
  ]
}
```

Допустимые цели на первом этапе:
- `processors[].properties`
- `controllerServices[].properties`

Недопустимые изменения:
- `identifier`
- `bundle`
- `type`
- добавление/удаление processors
- добавление/удаление connections
- перестройка JSON-иерархии

## Источники контекста для корректора

На вход v2 стоит давать:
- исходный PIM YAML;
- adapter-generated NiFi JSON;
- validation errors от NiFi import;
- allowlist типов исправлений.

Приоритет должен быть таким:
1. исправить конкретные validation errors;
2. исправить явно выводимые семантические дефекты;
3. не трогать ничего вне области ошибки.

## Этапы внедрения

1. Добавить новый prompt и новый response schema для patch-based исправлений.
2. Реализовать application layer, который ищет target processor/controller service и меняет только нужное property.
3. Добавить dry-run report: какие патчи предложены, какие применены, какие отклонены.
4. Ввести allowlist безопасных правок:
   - placeholder для обязательного свойства;
   - SQL/Calcite expression fix;
   - path normalization;
   - HTTP method normalization;
   - fully-qualified table/topic/path names.
5. Добавить регрессионные тесты на случаи, где текущий `mode 3` вносит лишние изменения.
6. Запустить отдельное сравнение:
   - `mode 3 current`
   - `mode 3 patch-based`

## Когда внедрять

Не менять текущую большую серию экспериментов посередине.

Рекомендуемый порядок:
- сначала завершить текущую pilot/global серию на существующем `NiFiCorrector`;
- затем внедрить `NiFiCorrector v2`;
- после этого провести отдельный мини-эксперимент и описать улучшение в ВКР как post-pilot refinement.

## Что писать в ВКР уже сейчас

Даже до внедрения v2 можно честно зафиксировать ограничение:
- текущий `mode 3` использует constrained full-document correction;
- это улучшает часть semantic errors, но уступает более строгому patch-based подходу по воспроизводимости;
- patch-based correction выделен как следующий этап инженерного развития метода.
