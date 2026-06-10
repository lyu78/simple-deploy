# Пакет `simple_deploy`

Этот пакет - новая внутренняя структура инструментария релизов и деплоя. Он
появился, чтобы постепенно вынести код из монолитного Windows runner и дать
CLI, web/API, builder-интеграции и будущим локальным заданиям общий слой
прикладной логики.

Этот README не заменяет операторские инструкции запуска. Для запуска команд,
настройки `.env`, `windows_pipeline.local.json`, Task Scheduler и практического
потока деплоя читайте `../README.MD` и корневой `../../README.MD`.

## Текущее состояние

Публичный CLI-контракт остается прежним:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --latest
```

Исторический путь `tools-ci/tools/windows_pipeline.py` является оберткой
совместимости. Основная реализация процесса пока остается в
`simple_deploy/windows_pipeline.py`; это временный монолит, из которого код
будет выноситься малыми срезами.

Уже вынесены общие примитивы релизов:

- `release/state.py` - SQLite-состояние релизов, контуров, попыток build/deploy,
  локальных заданий и внешних заявок;
- `release/artifacts.py` - dataclass-модели и резолверы файлов релиза;
- `release/manifest.py` - построение, чтение и запись `release_manifest.json`.

## Карта пакета

- `cli/` - тонкие CLI-точки входа. Здесь не должно быть логики build/deploy.
- `config/` - будущий слой чтения и валидации конфигурации времени выполнения.
- `contours/` - модели и правила контуров `dev`, `test`, `prod`.
- `core/` - будущие общие вспомогательные функции для команд, путей,
  логирования, SSH и файлов.
- `jobs/` - модель и будущий runner локальных долгих операций.
- `processes/` - целевое место для процессов `dry_run`, `build`, `deploy`, `mark`,
  `data_sql`.
- `release/` - состояние релизов, manifest и артефакты. Этот слой не должен
  выполнять deploy.
- `web/` - локальная FastAPI-панель/API поверх той же SQLite-базы.
- `windows_pipeline.py` - временный монолит текущего Windows runner.

## Правила дальнейшего выноса

Новый код процесса не добавляется в `simple_deploy/windows_pipeline.py`, если
его можно положить в целевой модуль. Монолит можно менять как адаптер: оставить
публичные команды и делегировать работу в `processes/`, `release/`, `config/`,
`core/` или `jobs/`.

При шаге 5 из `REFACTORING_PLAN.MD` процессы нужно выносить по одному:

1. `mark` - самый узкий срез вокруг `mark-applied` и `mark-failed`;
2. `build` - запуск builder и фиксация попыток сборки;
3. `dry_run` - проверки окружения без изменения VM и baseline;
4. `data_sql` - проверки и применение data SQL;
5. `deploy` - полный процесс деплоя поверх уже вынесенных примитивов.

Каждый срез должен сохранять:

- команды `dry-run`, `build`, `deploy`, `pipeline`, `set-baseline`,
  `mark-applied`, `mark-failed`;
- формат `windows_pipeline.local.json`;
- SQLite-состояние в `local_state/simple_deploy.sqlite3`;
- логи в терминал и `logs/<timestamp>-<command>.log`;
- поведение baseline: он двигается только после подтвержденного успешного
  применения релиза или явной ручной фиксации.

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
