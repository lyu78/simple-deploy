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

Web/API v1 для просмотра локального состояния запускается отдельно и не заменяет CLI:

```bash
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host 127.0.0.1 --port 8000
```

Панель доступна на `http://127.0.0.1:8000/`, API состояния - на
`http://127.0.0.1:8000/api/state`. В текущем срезе это read-only dashboard:
он показывает контуры, релизы, build/deploy attempts, локальные jobs и внешние
заявки TEST/PROD.

Практическая настройка рабочей машины, `tools-ci/.env`,
`tools-ci/local.secrets.env`, `tools-ci/windows_pipeline.local.json`,
service steps, Outlook email и запуск по
расписанию описаны в `tools-ci/README.MD`.

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
- data SQL-архивы `db_insert_*` и `db_update_*`, если build запущен с
  `--include-data-sql`.

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
- `REFACTORING_PLAN.MD` - зафиксированный план перехода к release/deploy toolkit,
  web/API и масштабированию по контурам.
- `tools-ci/README.MD` - установка и запуск основного Windows/Python runner.
- `tools-ci/PIPELINE.MD` - технический E2E-процесс Windows/Python runner.
- `legacy/ansible-ci/PIPELINE.MD` - legacy E2E-процесс через Ansible/WSL.
- `instructions/manual-schema-sql-deploy.md` - ручное применение schema SQL на
  TEST/PROD.
- `instructions/data-sql-script-markup.md` - правила разметки data SQL-скриптов
  backend repo.
- `instructions/data-sql-validation-rules.md` - read-only правила проверки
  идемпотентности и бизнес-ключей data SQL.
- `tools-ci/tools/windows_task_scheduler/README.md` - пример запуска pipeline по
  расписанию через Windows Task Scheduler.
- `CONTEXT.MD` - текущий технический контекст, решения и ограничения для
  сопровождающих проект.
- `DEVELOPMENT_RULES.MD` - правила разработки, документации, безопасности истории
  и взаимодействия с AI-агентом.

Диаграммы SQL release flow лежат в `docs/`:

- `docs/release-sql-migrations-flow.puml` - общий pipeline от dry-run до
  DEV/TEST/PROD.
- `docs/release-sql-migrations-build-dev.puml` - сборка и DEV-размещение.
- `docs/release-sql-migrations-test-prod.puml` - продвижение релиза на TEST и
  PROD.

## Структура репозитория

- `tools-ci/` - основной Windows/Python runner, builder, настройки и
  вспомогательные tools.
- `legacy/ansible-ci/` - legacy Ansible/WSL flow.
- `instructions/` - ручные операционные процедуры и правила подготовки SQL.
- `docs/` - диаграммы и дополнительные описания.
- `tests/` - тесты builder, runner и вспомогательной логики.
- `tools-ci/.env.example` - пример локальной конфигурации без секретов.
- `tools-ci/local.secrets.env.example` - пример локального файла секретов PostgreSQL.
