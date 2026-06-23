# Product Backlog

Этот файл отделяет новые продуктовые срезы от рефакторинга старой
release/deploy функциональности. Задачи ниже не являются критериями завершения
`REFACTORING_PLAN.MD`: их стоит брать только после того, как старые CLI/process
сценарии подтверждены на новой архитектуре.

## Приоритетные срезы

### TEST/PROD external requests в API/UI

Цель: дать оператору web/API-поверхность для заявок на внешнее продвижение
релиза на TEST/PROD.

Текущая база уже есть: SQLite `external_requests`, registry commands/read
models, DTO и read-only API. Следующий продуктовый срез должен добавить
mutation API/UI только через тонкий application service поверх существующих
registry commands, чтобы `web/app.py` не начал напрямую владеть use case
логикой.

Минимальная приемка:

- создать TEST/PROD заявку из UI/API;
- обновить статус, внешний id и ошибку;
- увидеть заявку в release/detail или dashboard контексте;
- сохранить существующие CLI-команды `mark-applied` и `mark-failed` как
  основной ручной fallback.

### Release contents / change set

Цель: показать оператору, что именно входит в релиз перед применением или
передачей на TEST/PROD.

Первый срез должен быть read-only: commits/source snapshot, manifest artifacts,
SQL/app части и связь с текущими contour baselines. Интеграцию с issue tracker
не добавлять до отдельного решения.

Минимальная приемка:

- read model собирается без изменения release/deploy поведения;
- UI/API показывает содержимое релиза по `build_version`;
- отсутствующий manifest или неполные artifacts отображаются как диагностическое
  состояние, а не как новый deploy failure.

### Bundle validation pipeline

Цель: оформить проверку release bundle как отдельный job/use case до
размещения на контур.

Первый срез должен переиспользовать уже существующие manifest/artifact/runtime
checks и не менять `ContourState`, `ReleasePlacement` или baseline. Глубокие
доменные сущности вводить только когда появится конкретный validation сценарий.

Минимальная приемка:

- validation job запускается через тот же worker контур;
- результат виден в jobs/API/UI;
- проверка не выполняет deploy side effects;
- ошибки bundle-а диагностируются до попытки применения.

### Operator UX

Дополнительные улучшения UI стоит вести как отдельные маленькие срезы:

- страницы release detail и job history;
- фильтры и сохраненные представления;
- подсказки по recovery после failed job;
- операционный экран web + worker health.

## Правила ведения backlog

- Не смешивать новые продуктовые задачи с критериями завершения рефакторинга.
- Не вводить глубокие DDD-сущности без конкретного сценария использования.
- Для mutation API добавлять application service boundary, если операция
  меняет release/job/request состояние.
- CLI должен оставаться основным и аварийным путем, пока отдельным решением не
  принято обратное.
