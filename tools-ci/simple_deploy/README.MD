# Пакет `simple_deploy`

Этот пакет - новая внутренняя структура инструментария релизов и деплоя. Он
появился, чтобы постепенно вынести код из монолитного Windows runner и дать
CLI, web/API, builder-интеграции и будущим локальным заданиям общий слой
прикладной логики.

Этот README не заменяет операторские инструкции запуска. Для запуска команд,
настройки `tools-ci/.env`, `tools-ci/windows_pipeline.local.json`, Task Scheduler и практического
потока деплоя читайте `../README.MD` и корневой `../../README.MD`.

## Текущее состояние

Публичный CLI-контракт теперь публикуется как console script:

```bash
.venv/Scripts/simple-deploy.exe dry-run
.venv/Scripts/simple-deploy.exe build
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest
```

Реальная CLI-реализация находится в `simple_deploy/cli/windows_pipeline.py`.
Старые package imports через `simple_deploy.windows_pipeline` больше не
поддерживаются.

Уже вынесены общие примитивы release/deploy toolkit:

- `registry/state.py` - SQLite-состояние релизов, контуров, попыток build/deploy,
  локальных заданий и внешних заявок; `release/state.py` оставлен compatibility
  re-export-ом;
- `registry/commands.py` и `registry/queries.py` - write/read boundary поверх SQLite;
- `release/artifacts.py` - dataclass-модели и резолверы файлов релиза;
- `release/manifest.py` - построение, чтение и запись `release_manifest.json`.
- `core/paths.py`, `core/commands.py`, `core/env.py`, `core/build_env.py`,
  `core/release_paths.py` - общие helper-ы, уже используемые build/mark процессами
  без импорта `windows_pipeline`.
- `types/` - первые constrained primitives для release/build version, commit SHA,
  contour, status, component, artifact и deploy entrypoint справочников.
- `models/state.py` - внутренние модели чтения над SQLite state/API.
- `config/runtime.py` - первая Pydantic-модель текущего `tools-ci/windows_pipeline.local.json`
  без изменения старого loader-контракта.
- `config/validation.py` - runtime preflight/policy validation, вынесенная из
  старого runner-а.

## Карта пакета

- `cli/` - тонкие CLI-точки входа. Здесь не должно быть логики build/deploy.
- `application/` - прикладные сервисы над process modules для CLI, web/API и
  будущих local jobs.
- `config/` - слой чтения, структурной валидации и preflight policy checks
  конфигурации времени выполнения.
- `contours/` - модели и правила контуров `dev`, `test`, `prod`.
- `core/` - общие вспомогательные функции для команд, путей, env, build-env,
  release-path resolving и SSH.
- `dto/` - внешние JSON/API контракты, отделенные от SQLite rows и dataclass state.
- `jobs/` - модель и будущий runner локальных долгих операций.
- `models/` - внутренние application/read модели между state/query и DTO.
- `processes/` - целевое место для процессов `dry_run`, `build`, `deploy`, `mark`,
  `data_sql`.
- `release/` - состояние релизов, manifest и артефакты. Этот слой не должен
  выполнять deploy.
- `types/` - enum-ы, справочники и custom primitive types без бизнес-логики.
- `web/` - локальная FastAPI-панель/API поверх той же SQLite-базы.

## Правила дальнейшего выноса

Изменения CLI adapter-а идут в `simple_deploy/cli/windows_pipeline.py`, а
бизнес-логика остается в `application/`, `processes/`, `release/`, `config/`,
`core` или `jobs/`.

При шаге 5 из `REFACTORING_PLAN.MD` процессы нужно выносить по одному:

1. `mark` - самый узкий срез вокруг `mark-applied` и `mark-failed`;
2. `build` - запуск builder и фиксация попыток сборки;
3. `dry_run` - проверки окружения без изменения VM и baseline;
4. `data_sql` - проверки и применение data SQL;
5. `deploy` - полный процесс деплоя поверх уже вынесенных примитивов.

Каждый срез должен сохранять:

- команды `dry-run`, `build`, `deploy`, `pipeline`, `set-baseline`,
  `mark-applied`, `mark-failed`;
- формат `tools-ci/windows_pipeline.local.json`;
- SQLite-состояние в `local_state/simple_deploy.sqlite3`;
- логи в терминал и `logs/<timestamp>-<command>.log`;
- поведение baseline: он двигается только после подтвержденного успешного
  применения релиза или явной ручной фиксации.

Текущий dependency baseline: process modules и внешняя точка запуска используют
`simple_deploy.cli.windows_pipeline` напрямую; package shim
`simple_deploy.windows_pipeline` удален.

## Документация и проверки

Перед изменениями читайте:

- `../../REFACTORING_PLAN.MD` - порядок и статус рефакторинга;
- `../../DEVELOPMENT_RULES.MD` - язык, docstring, безопасность Git и инварианты;
- `../README.MD` - операторский Windows/Python runner;
- `../PIPELINE.MD` - технический сквозной процесс runner-а.

Минимальные проверки после среза:

```bash
.venv/Scripts/python.exe -m pytest
git diff --check
```

Если срез трогает поведение build/deploy во время выполнения, дополнительно
нужен `dry-run` на DEV по инструкции из `REFACTORING_PLAN.MD`.
