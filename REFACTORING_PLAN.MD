# План рефакторинга simple-deploy

Дата фиксации плана: 2026-06-09.

## Зачем это делаем

Репозиторий начинался как практический контур для Ansible и локального деплоя, но фактически вырос в release/deploy toolkit:

- собирает продуктовый release artifact;
- хранит baseline по контурам `dev`, `test`, `prod`;
- генерирует schema/data SQL артефакты;
- умеет раскладывать maintenance stub;
- управляет порядком остановки backend/frontend/nginx;
- проверяет и применяет долгие data update скрипты;
- фиксирует успешные и неуспешные build/deploy attempts в SQLite.

Из-за этого основной риск теперь не в отдельных функциях, а в форме проекта. Один файл `tools-ci/tools/windows_pipeline.py` содержит конфиг, валидацию, SSH, SQL, deploy, dry-run, состояние релизов, уведомления и CLI. Такой файл сложно расширять под тестовые пайплайны, стресс-тесты, альтернативные команды, заявки на TEST/PROD и простую web-морду.

Цель рефакторинга - сохранить текущий рабочий CLI, но разложить систему вокруг процессов и контуров.

## Как пришли к решению

1. Текущий основной путь - Windows/Python runner без обязательного WSL/Docker. Ansible остался как legacy-вариант и больше не является центром развития.
2. Ключевой объект системы - релиз как продуктовый артефакт, а не отдельный deploy-скрипт.
3. DEV, TEST и PROD должны быть явными контурами с разными правилами:
   - DEV может выполнять deploy напрямую на VM;
   - TEST/PROD могут требовать пакеты, заявки, ручную фиксацию статусов и другие уведомления;
   - build пока может собирать frontend сразу для всех контуров, но архитектура не должна на это завязываться.
4. Все текущие команды должны остаться доступными из терминала.
5. Web/API нужен как дополнительный интерфейс поверх тех же команд и той же SQLite-базы, без авторизации и ролевой модели на первом этапе.
6. Долгие операции из web-интерфейса нельзя выполнять синхронно внутри HTTP-запроса. Нужна модель локальных jobs.
7. Репозиторий стоит развивать как deploy/release toolkit, а не как набор разрозненных скриптов качества кода.

## Целевая модель

Два интерфейса вызывают одну и ту же прикладную логику:

- CLI: совместимый вход через `tools-ci/tools/windows_pipeline.py`;
- Web/API: простая локальная панель и REST API для просмотра релизов, запусков и статусов.

Общее ядро отвечает за:

- конфигурацию и runtime validation;
- состояние релизов и контуров в SQLite;
- build, deploy, dry-run и mark-applied/mark-failed процессы;
- jobs для долгих операций;
- логи и итоговые статусы.

## Целевая структура

Промежуточная целевая структура внутри `tools-ci`:

```text
tools-ci/
  simple_deploy/
    cli/
      windows_pipeline.py
    config/
      runtime.py
      validation.py
    core/
      commands.py
      logging.py
      paths.py
      ssh.py
    release/
      artifacts.py
      state.py
      manifest.py
    contours/
      model.py
      dev.py
      test.py
      prod.py
    processes/
      dry_run.py
      build.py
      deploy.py
      mark.py
      data_sql.py
    jobs/
      model.py
      runner.py
      repository.py
    web/
      api.py
      app.py
      templates/
      static/
  tools/
    windows_pipeline.py
```

`tools-ci/tools/windows_pipeline.py` остается совместимым wrapper-ом. Он должен импортировать новый CLI entrypoint и не менять публичные команды.

Ansible переносится в legacy-зону:

```text
legacy/
  legacy/ansible-ci/
```

Документация, которая ссылается на Ansible, должна явно называть его legacy-вариантом.

## Контуры и пайплайны

Общая модель:

- `dev` - полный локально управляемый deploy на VM;
- `test` - подготовка пакета, заявка/трек статуса, ручная фиксация результата;
- `prod` - подготовка production-пакета, более строгие проверки, ручная фиксация результата.

Минимальные сущности:

- release;
- contour;
- build attempt;
- deployment attempt;
- external request;
- local job.

CLI-команды остаются первичным контрактом:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run --contour dev
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --latest
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-applied --contour test --build-version <version>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-failed --contour test --build-version <version> --error "<reason>"
```

Новые пайплайны должны добавляться как процессы, а не как новые ветки большого файла:

- test pipeline;
- alternative deploy commands;
- stress tests;
- package for test;
- package for prod;
- request tracking for test/prod.

## Web/API v1

Первый web/API слой должен быть простым:

- FastAPI;
- без авторизации и ролей;
- та же SQLite-база, что у CLI;
- запуск долгих операций через local jobs;
- просмотр релизов, build attempts, deployment attempts и jobs;
- запуск существующих команд CLI-процессов из UI;
- ручная пометка `applied`/`failed` для TEST/PROD.

Web не должен становиться отдельной реализацией деплоя. Он только интерфейс к тому же toolkit.

## Порядок реализации

1. Зафиксировать этот план в корне репозитория.
2. Создать пакет `tools-ci/simple_deploy/`.
3. Оставить `tools-ci/tools/windows_pipeline.py` как совместимый wrapper.
4. Вынести release/state/artifact primitives из builder и pipeline в общие модули.
5. Разложить текущие процессы по модулям `dry_run`, `build`, `deploy`, `mark`, `data_sql`.
6. Перенести `legacy/ansible-ci/` в `legacy/legacy/ansible-ci/` и обновить ссылки в документации.
7. Расширить SQLite-модель под jobs и external requests.
8. Добавить FastAPI API поверх release/job/process слоев.
9. Добавить простую web-страницу для v1 dashboard.
10. Обновить документацию и тесты.

## Инварианты совместимости

Во время рефакторинга нельзя ломать:

- текущие команды `dry-run`, `build`, `deploy`, `pipeline`, `set-baseline`, `mark-applied`, `mark-failed`;
- формат локального `windows_pipeline.local.json`, если нет отдельной миграции;
- хранение state в `local_state/simple_deploy.sqlite3`;
- генерацию build artifacts;
- порядок full deploy для DEV;
- проверку maintenance stub перед DB deploy;
- preflight cleanup долгих data update скриптов;
- поведение `data_sql_enabled` и `--include-set-default-sql`;
- логи в терминал и `logs/<timestamp>-<command>.log`.

## Проверки на каждом этапе

Минимальный набор:

```bash
.venv/Scripts/python.exe -m pytest tests/test_windows_pipeline_permissions.py
.venv/Scripts/python.exe -m pytest
git diff --check
```

Для этапов, которые трогают build/deploy:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run --contour dev
```

Для web/API этапов дополнительно:

```bash
.venv/Scripts/python.exe -m pytest tests
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci
```

## Ближайший безопасный срез

Первый кодовый срез после этого документа:

1. создать пустой пакет `tools-ci/simple_deploy/`;
2. добавить новый CLI entrypoint;
3. сделать `tools-ci/tools/windows_pipeline.py` тонким wrapper-ом без изменения поведения;
4. покрыть wrapper smoke-тестом;
5. только после этого переносить реальные процессы по одному.

Такой порядок позволяет начать рефакторинг без одновременного изменения deploy-логики.

## Статус первого среза

Выполнено в первом безопасном срезе:

- создан этот план;
- создан пакет `tools-ci/simple_deploy/` и начальный каркас подпакетов;
- `tools-ci/tools/windows_pipeline.py` оставлен как compatibility wrapper;
- текущая реализация runner перенесена в `tools-ci/simple_deploy/windows_pipeline.py` без изменения CLI-контракта;
- добавлен facade `simple_deploy.release.state`;
- SQLite state расширен таблицами `local_jobs` и `external_requests`;
- добавлен read-only FastAPI dashboard/API v1;
- `ansible-ci/` перенесен в `legacy/ansible-ci/` с исправлением ссылок и default path вычислений;
- тесты обновлены под новую структуру.

## Статус шага 4

Шаг 4 завершен отдельным срезом:

- SQLite state implementation перенесена в `tools-ci/simple_deploy/release/state.py`;
- `tools-ci/builder/src/release_state.py` оставлен compatibility shim-ом для старых импортов `src.release_state`;
- release artifact primitives вынесены в `tools-ci/simple_deploy/release/artifacts.py`;
- release manifest primitives вынесены в `tools-ci/simple_deploy/release/manifest.py`;
- builder и Windows runner используют общие `simple_deploy.release.*` модули вместо собственной реализации state/artifact/manifest primitives;
- совместимость текущего CLI wrapper-а сохранена.

Следующий шаг рефакторинга - шаг 5: разложить текущие процессы по модулям
`dry_run`, `build`, `deploy`, `mark`, `data_sql`.
