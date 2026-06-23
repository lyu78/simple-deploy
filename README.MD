# simple-deploy

`simple-deploy` автоматизирует release/deploy flow для backend/frontend:
проверяет готовность окружения, синхронизирует исходники, собирает релизные
архивы, формирует SQL-артефакты и раскатывает релиз на контуры.

Корневой README - точка входа в проект. Здесь описана общая картина и ссылки на
документы с деталями запуска.

## Кому читать

- Разработчику - чтобы понять, какие репозитории, архивы и SQL-артефакты
  участвуют в релизе.
- Аналитику или владельцу процесса - чтобы увидеть общий поток от проверки до
  фиксации результата на контурах.
- Оператору релиза - чтобы найти актуальную инструкцию запуска и правила
  фиксации успешного или неуспешного применения.

## Текущий основной путь

Основной поддерживаемый runtime - Windows/Python runner:

```bash
.venv/Scripts/simple-deploy.exe dry-run
.venv/Scripts/simple-deploy.exe build
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest
```

Команда `simple-deploy.exe` создается при первичной настройке из
`tools-ci/README.MD` через editable install проекта.

Web/API v1 запускается отдельно и не заменяет CLI. CLI остается основным и
аварийным путем, а web-панель дает операторский интерфейс поверх того же
локального состояния и API:

В двух отдельных терминалах:

```bash
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host 127.0.0.1 --port 8000
.venv/Scripts/simple-deploy.exe worker --poll-interval 2
```

Панель доступна на `http://127.0.0.1:8000/`, API состояния - на
`http://127.0.0.1:8000/api/state`, статус worker-а - на
`http://127.0.0.1:8000/api/worker`. React UI показывает контуры, релизы,
build/deploy attempts, локальные jobs, состояние worker-а и внешние заявки
TEST/PROD, а также создает локальные jobs через API. Долгие операции выполняет
отдельный `simple-deploy worker`, а не HTTP request. Исходники UI лежат в
`tools-ci/web-ui`; после изменений фронтенда выполните `npm install && npm run
build` из этого каталога, чтобы FastAPI начал отдавать свежую сборку.

Практическая настройка рабочей машины, `tools-ci/.env`,
`tools-ci/local.secrets.env`, `tools-ci/windows_pipeline.local.json`,
service steps, Outlook email и операционный запуск `web + worker` описаны в
`tools-ci/README.MD`.

Legacy-вариант через Ansible/WSL сохранен в `legacy/ansible-ci/PIPELINE.MD`, но не
является основным путем для новых запусков.

## Как устроен релиз

Процесс работает с тремя контурами: `dev`, `test`, `prod`. Для каждого контура
хранится SQL baseline - backend commit, который уже успешно применен на этом
контуре. Следующий build строит schema SQL-диапазон от baseline до текущего
backend commit релиза.

Релизная директория содержит:

- backend runtime archive;
- frontend runtime archive;
- `release_manifest.json` с версиями, commit SHA и SQL metadata;
- schema SQL-архивы `db_schema_dev_*`, `db_schema_test_*`, `db_schema_prod_*`;
- data SQL-архивы `db_insert_*`, `db_update_sequential_*`,
  `db_update_parallel_*`, `db_set_default_sequential_*` и
  `db_set_default_parallel_*`. Build создает их по умолчанию; schema-only режим
  включается через `--skip-data-sql-artifacts`, а старый `--include-data-sql`
  оставлен только для совместимости.

Schema SQL генерируется offline по Git-диапазону backend source repo. Он не
подтверждает состояние реальной БД сам по себе: фактом применения считается
успешный deploy или явная фиксация результата оператором.

## Основной поток

1. Оператор выполняет `dry-run` и устраняет ошибки окружения.
2. Build синхронизирует source/target репозитории, собирает runtime-архивы и SQL
   artifacts, затем пишет `release_manifest.json`.
3. DEV обычно обновляется автоматически через `deploy --contour dev`.
4. TEST и PROD могут продвигаться внешним или ручным процессом. После успешного
   применения оператор фиксирует результат:

```bash
.venv/Scripts/simple-deploy.exe mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/simple-deploy.exe mark-applied --contour prod --build-version <successful_release_version>
```

Если применение завершилось ошибкой, попытка фиксируется без сдвига baseline:

```bash
.venv/Scripts/simple-deploy.exe mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

Локальный реестр `local_state/simple_deploy.sqlite3` ведет историю попыток:
упавшие build фиксируются автоматически в `build_attempts`, а упавшие
`deploy`/`pipeline` - в `deployment_attempts`. Таблица `releases` хранит только
успешно собранные релизы с manifest.

Не сдвигайте baseline вручную на новый commit до успешного применения релиза:
следующий build посчитает этот commit уже примененным и может собрать неполный
SQL-диапазон.

## Где лежат детали

- `PIPELINE.MD` - продуктовая схема release flow без привязки к runtime; подходит
  как основа для BPMN.
- `ARCHITECTURE.MD` - доменный язык, архитектурные границы и статус реализации
  модели.
- `REFACTORING_PLAN.MD` - история завершенного refactoring track перехода к
  release/deploy toolkit, web/API и worker-контуру.
- `PRODUCT_BACKLOG.MD` - отдельный backlog новых продуктовых срезов поверх
  текущего CLI/API/UI.
- `tools-ci/README.MD` - установка и запуск основного Windows/Python runner.
- `tools-ci/PIPELINE.MD` - технический E2E-процесс Windows/Python runner.
- `legacy/ansible-ci/PIPELINE.MD` - legacy E2E-процесс через Ansible/WSL.
- `docs/README.MD` - навигация по runbooks, SQL contracts, tasks и diagrams.
- `docs/runbooks/manual-sql-release-run.md` - ручное применение schema и data
  SQL artifacts на TEST/PROD.
- `docs/sql/data-script-markup.md` - правила разметки data SQL-скриптов backend
  repo.
- `docs/sql/data-validation-rules.md` - read-only правила проверки
  идемпотентности и бизнес-ключей data SQL.
- `CONTEXT.MD` - текущий технический контекст, решения и ограничения для
  сопровождающих проект.
- `DEVELOPMENT_RULES.MD` - правила разработки, документации, безопасности
  истории и Git.
- `AGENTS.md` - правила работы AI-агентов в репозитории.

Диаграммы SQL release flow лежат в `docs/diagrams/sql-release/`:

- `docs/diagrams/sql-release/release-sql-migrations-flow.puml` - общий pipeline
  от dry-run до DEV/TEST/PROD.
- `docs/diagrams/sql-release/release-sql-migrations-build-dev.puml` - сборка и
  DEV-размещение.
- `docs/diagrams/sql-release/release-sql-migrations-test-prod.puml` -
  продвижение релиза на TEST и PROD.

## Структура репозитория

- `tools-ci/` - основной Windows/Python runner, builder, React web UI, настройки
  и вспомогательные tools.
- `legacy/ansible-ci/` - legacy Ansible/WSL flow.
- `docs/` - runbooks, SQL contracts, one-off tasks, diagrams и дополнительные
  описания.
- `tests/` - тесты builder, runner и вспомогательной логики.
- `tools-ci/.env.example` - пример локальной конфигурации без секретов.
- `tools-ci/local.secrets.env.example` - пример локального файла секретов PostgreSQL.
