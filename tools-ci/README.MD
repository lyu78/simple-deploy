# Windows/Python runner

Это практическая инструкция для основного operator flow `simple-deploy` на
Windows-машине без обязательного WSL или Docker. Точка входа:
`.venv/Scripts/simple-deploy.exe`.

Общая продуктовая схема описана в `../PIPELINE.MD`, технический порядок стадий -
в `PIPELINE.MD`.

## Требования

На рабочей Windows-машине нужны:

- Python с `venv` и `pip`;
- Git for Windows и Git Bash;
- Node.js/npm для frontend build;
- Windows OpenSSH (`ssh`, `scp`);
- доступ к backend/frontend source и target репозиториям;
- SSH-доступ к app VM и DB VM;
- PostgreSQL credentials для DB VM.

## Первичная настройка

Откройте Git Bash и выполните:

```bash
git clone https://github.com/lyu78/simple-deploy simple-deploy
cd simple-deploy

python -m venv .venv
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org -r tools-ci/requirements.dev.txt
.venv/Scripts/python.exe -m pip install --disable-pip-version-check -e . --no-deps

cp tools-ci/.env.example tools-ci/.env
cp tools-ci/local.secrets.env.example tools-ci/local.secrets.env
cp tools-ci/windows_pipeline.example.json tools-ci/windows_pipeline.local.json
```

Web/API v1 запускается поверх той же SQLite-базы. CLI остается основным и
аварийным путем, а React UI дает операторскую панель для просмотра состояния и
создания локальных jobs через API:

На Windows запустите web/API и worker одним батником из корня репозитория:

```bat
.\start-simple-deploy.bat
```

Он откроет два отдельных терминала: `simple-deploy web` и
`simple-deploy worker`. Повторный запуск не дублирует уже работающие процессы и
стартует только отсутствующий web или worker.

Эквивалентные команды для ручного запуска:

```bash
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host 127.0.0.1 --port 8000
.venv/Scripts/simple-deploy.exe worker --poll-interval 2
```

UI: `http://127.0.0.1:8000/`.
API: `http://127.0.0.1:8000/api/state`.
Worker status: `http://127.0.0.1:8000/api/worker`.

Web/API только создает queued jobs и управляет их lifecycle через REST. Для
реального выполнения очереди рядом должен работать `simple-deploy worker`; его
удобно запускать во втором терминале или отдельном process supervisor-е.
Разовый режим для проверки очереди:

```bash
.venv/Scripts/simple-deploy.exe worker --once
```

## Операционный запуск web + worker

`web` и `worker` запускаются как два независимых локальных процесса с общей
SQLite-базой `local_state/simple_deploy.sqlite3`.

Основной Windows entrypoint:

```bat
.\start-simple-deploy.bat
```

Батник проверяет `.venv`, запускает web/API на `127.0.0.1:8000` и worker с
`--poll-interval 2` в двух отдельных терминалах. Запуск идемпотентный:
повторное выполнение батника пропускает уже найденный web/worker process и
стартует только отсутствующий. Параметры можно переопределить переменными
окружения:

```bat
set SIMPLE_DEPLOY_WEB_HOST=127.0.0.1
set SIMPLE_DEPLOY_WEB_PORT=8000
set SIMPLE_DEPLOY_WORKER_POLL_INTERVAL=2
.\start-simple-deploy.bat
```

Ручной эквивалент:

Терминал 1 - web/API:

```bash
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host 127.0.0.1 --port 8000
```

Терминал 2 - постоянный worker:

```bash
.venv/Scripts/simple-deploy.exe worker --poll-interval 2
```

Проверки после запуска:

- `http://127.0.0.1:8000/api/health` возвращает `{"status":"ok"}`;
- `http://127.0.0.1:8000/api/worker` показывает `idle`, `running`, `error`,
  `stale` или `offline`;
- dashboard на `http://127.0.0.1:8000/` показывает worker panel и индикатор
  polling;
- создание job через UI или `POST /api/jobs` добавляет запись в `local_jobs`;
- worker забирает due `queued` job, пишет log file и переводит job в terminal
  status;
- live log доступен через `/jobs/{id}` и WebSocket `/ws/jobs/{id}`.

Ожидаемые состояния worker-а:

- `offline` - heartbeat еще не записывался или база пустая;
- `idle` - worker запущен и очередь пуста;
- `running` - worker исполняет job;
- `error` - worker зафиксировал ошибку;
- `stale` - последний heartbeat старше допустимого интервала, процесс нужно
  проверить или перезапустить.

Recovery:

- если worker остановлен, уже созданные `queued` jobs остаются в SQLite и будут
  выполнены после нового запуска worker-а;
- failed/cancelled job можно вернуть в очередь через UI или
  `PATCH /api/jobs/{id}` со статусом `queued`;
- если нужно проверить только одну итерацию без постоянного процесса, используйте
  `.venv/Scripts/simple-deploy.exe worker --once`;
- CLI команды `dry-run`, `build`, `deploy`, `pipeline`, `set-baseline`,
  `mark-applied` и `mark-failed` остаются прямым fallback без web/worker.

Исходники UI лежат в `tools-ci/web-ui`. После изменения фронтенда соберите
статические assets:

```bash
cd tools-ci/web-ui
npm install
npm run build
```

Заполните `tools-ci/.env` путями к backend/frontend репозиториям, VM-хостами,
доменами, директориями деплоя и build settings. Для Windows-only режима можно оставить
`PROJECT_ROOT_WSL` и `RELEASE_ROOT_WSL` пустыми; при необходимости задайте
`RELEASE_ROOT_WINDOWS`.

Если SSH-вход выглядит как `ssh -i ./simple-deploy deploy-user@192.0.2.10`,
укажите:

```properties
APP_SSH_KEY_PATH=./simple-deploy
APP_VM_USER=deploy-user
```

Относительные `APP_SSH_KEY_PATH`, `DB_SSH_KEY_PATH` и общий `SSH_KEY_PATH`
runner ищет сначала от текущей директории, затем от домашней директории
Windows-пользователя. Если один ключ подходит для обеих VM, можно задать только
`SSH_KEY_PATH`.

В `tools-ci/local.secrets.env` укажите доступ к PostgreSQL:

```properties
DB_LOGIN_USER=postgres
DB_LOGIN_PASSWORD=<password>
```

Для `dry-run`, `deploy` и `pipeline` `DB_LOGIN_PASSWORD` обязателен: пустое
значение и placeholder `change-me` считаются ошибкой конфигурации.

## Локальный runner config

`tools-ci/windows_pipeline.local.json` хранит локальные расширения pipeline:

- `service_steps` - сервисные команды на app VM;
- `management_commands` - Django management-команды;
- `db_maintenance_sql` и `sql_scripts` - дополнительные SQL-шаги;
- `maintenance_stub_enabled` и `maintenance_stub_archive_path` - универсальная
  статическая заглушка для full deploy;
- `maintenance_stub_verify_enabled`, `maintenance_stub_verify_marker`,
  `maintenance_stub_verify_retries`, `maintenance_stub_verify_delay` - HTTP-проверка,
  что после распаковки действительно отдается maintenance-заглушка;
- `data_sql_enabled`, `db_data_sql_timeout_seconds`,
  `db_update_parallel_max_workers` и
  `db_update_parallel_status_interval_seconds` - запуск data SQL в full deploy;
- `healthcheck_commands` - дополнительные проверки;
- `outlook_email_*` - уведомление через desktop Outlook;
- `backup_enabled` и связанные настройки backup.

Default maintenance-заглушка лежит в
`tools-ci/maintenance_stub/maintenance_stub.tar.gz`. Это готовый статический
архив, не привязанный к release version. Full deploy загружает его на app VM и
распаковывает в `FRONTEND_RELEASE_PATH` перед DB-частью. Архив должен
раскрываться через `tar -xzf ... --strip-components=1`, поэтому текущий default
имеет верхний каталог `build/`, внутри которого лежат `index.html` и `assets/`.
Если `maintenance_stub_enabled=true`, `dry-run` проверяет наличие этого файла
до остановки сервисов. После распаковки заглушки full deploy делает HTTP-запрос
на `https://DEV_DOMAIN/` с cache-busting query и ищет
`maintenance_stub_verify_marker` в HTML. Для default stub маркер -
`Плановые технические работы`. Если маркер не найден, deploy падает до запуска
schema/data SQL: это защищает от ситуации, когда nginx все еще отдает основной
frontend вместо заглушки.

Пример информационных SQL-отчетов после DB-части deploy:

```json
{
  "sql_scripts": [
    {
      "path": "tools-ci/sql/reports/public_table_size_report.sql",
      "phase": "after_migrate"
    },
    {
      "path": "tools-ci/sql/reports/public_table_maintenance_diagnostics.sql",
      "phase": "after_migrate"
    }
  ]
}
```

Runner выполняет `sql_scripts` последовательно в порядке JSON. Файлы в
`tools-ci/sql/reports/` являются read-only отчетами runner-а, а не source data
SQL backend repo. Поэтому отчет по размеру таблиц должен идти первым, а
диагностика обслуживания - сразу после него. Вывод этих скриптов попадает в
консоль и в
`logs/<timestamp>-<command>.log`.

Минимальный пример `service_steps`:

```json
{
  "service_permission_checks_enabled": true,
  "service_steps": [
    {
      "name": "restart example backend",
      "phase": "after_migrate",
      "command": "sudo /bin/systemctl restart example-backend.service"
    },
    {
      "name": "restart example worker",
      "phase": "after_migrate",
      "command": "sudo /bin/systemctl restart example-worker.service"
    }
  ]
}
```

Поддерживаемые фазы service steps: `before_unpack`, `after_unpack`,
`after_migrate`, `after_frontend_unpack`. Шаги без `phase` выполняются как `after_migrate`. Если
`manage.py` требует поднятый Redis/KeyDB, добавьте идемпотентный `start/status`
KeyDB в `after_unpack`, а явный restart `stop/start/status` KeyDB задавайте в
`after_migrate`. Nginx должен оставаться запущенным до замены заглушки на
финальный frontend. Штатный сценарий для nginx - `stop` затем `start` только в
`after_frontend_unpack`: после раскладки финального frontend и перед
healthcheck. Dry-run требует, чтобы `stop nginx` имел последующий `start nginx`
в той же фазе, а `restart`/`reload`/`try-restart` для nginx считает ошибкой
конфига. `systemctl status nginx` можно использовать как проверку
доступа/состояния.

Во время `dry-run` runner получает список доступных sudo-команд через
`sudo -n -l`, затем проверяет каждую sudo service step без выполнения самой
сервисной команды. Если для шага нужна отдельная команда проверки, задайте
`permission_check_command` тоже через `sudo`.

Команды `systemctl start/stop/restart/reload ...` в `service_steps` должны идти
через `sudo /bin/systemctl ...`. Команды `systemctl status ...` можно задавать
без `sudo`; они выполняются после `start` и уронят deploy, если unit не активен.
На `dry-run` bare `systemctl status ...` считается успешной проверкой доступа
даже при `Active: inactive (dead)` и rc=3: это означает, что статус читается,
а не что unit уже запущен.

Пример `/etc/sudoers.d/simple-deploy` для текущего DEV-порядка stop/start:

```sudoers
Cmnd_Alias SIMPLE_DEPLOY_SYSTEMD = \
    /bin/systemctl stop gunicorn_local.service, \
    /bin/systemctl stop celery_local.service, \
    /bin/systemctl stop celerybeat_local.service, \
    /bin/systemctl stop keydb_local.service, \
    /bin/systemctl stop file_proxy_local.service, \
    /bin/systemctl stop minio_local.service, \
    /bin/systemctl start minio_local.service, \
    /bin/systemctl start file_proxy_local.service, \
    /bin/systemctl start keydb_local.service, \
    /bin/systemctl start celerybeat_local.service, \
    /bin/systemctl start celery_local.service, \
    /bin/systemctl start gunicorn_local.service, \
    /bin/systemctl stop nginx, \
    /bin/systemctl start nginx

deploy-simple ALL=(root) NOPASSWD: SIMPLE_DEPLOY_SYSTEMD
```

Если `command -v systemctl` возвращает не `/bin/systemctl`, используйте этот
фактический путь и в sudoers, и в `tools-ci/windows_pipeline.local.json`. Команды
`systemctl status ...` в sudoers добавлять не нужно, если они доступны без sudo.
После правки проверьте файл и конкретные права:

```bash
sudo visudo -cf /etc/sudoers.d/simple-deploy
sudo -n -l /bin/systemctl stop celerybeat_local.service
sudo -n -l /bin/systemctl stop keydb_local.service
sudo -n -l /bin/systemctl start keydb_local.service
sudo -n -l /bin/systemctl start celerybeat_local.service
sudo -n -l /bin/systemctl stop nginx
sudo -n -l /bin/systemctl start nginx
systemctl status celerybeat_local.service
```

## Команды оператора

Первичная инициализация baseline выполняется один раз перед первой сборкой.
Укажите фактические backend commit, которые уже успешно лежат на контурах:

```bash
.venv/Scripts/simple-deploy.exe set-baseline --contour dev --backend-commit <dev_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour test --backend-commit <test_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour prod --backend-commit <prod_backend_commit>
```

Если есть локальный `release_manifest.json` уже примененного релиза, baseline
можно поставить по версии:

```bash
.venv/Scripts/simple-deploy.exe set-baseline --contour test --build-version <previous_successful_release_version>
```

Обычная диагностика:

```bash
.venv/Scripts/simple-deploy.exe dry-run
.venv/Scripts/simple-deploy.exe dry-run --app-only
```

Сборка релиза:

```bash
.venv/Scripts/simple-deploy.exe build
```

Деплой уже собранного релиза:

```bash
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest
.venv/Scripts/simple-deploy.exe deploy --contour dev --build-version <version>
```

Если DB schema SQL уже успешно применился, а deploy упал позже на app VM,
используйте recovery-режим без подключения к DB VM:

```bash
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest --app-only
```

`--app-only` пропускает maintenance-заглушку, DB maintenance, DB schema/data
artifacts и `psql`, но заново выполняет app service steps, upload/unpack
backend/frontend, Django management, healthcheck и фиксацию baseline.

Полный локальный цикл:

```bash
.venv/Scripts/simple-deploy.exe pipeline --contour dev
```

По умолчанию full deploy применяет data insert и update, но пропускает
`kind=set_default`. Запуск `set_default` требует явного флага:

```bash
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest --include-set-default-sql
.venv/Scripts/simple-deploy.exe pipeline --contour dev --include-set-default-sql
```

`dry-run` проверяет data SQL по умолчанию, а `build` и `pipeline` генерируют
data SQL-артефакты по умолчанию. Явный schema-only режим для аварийных случаев:

```bash
.venv/Scripts/simple-deploy.exe build --skip-data-sql-artifacts
.venv/Scripts/simple-deploy.exe pipeline --contour dev --skip-data-sql-artifacts
```

Старый `--include-data-sql` оставлен только для совместимости и больше ничего
не включает. Runtime config `data_sql_enabled` управляет только применением
готовых data SQL-архивов на deploy.

Фиксация внешнего TEST/PROD результата:

```bash
.venv/Scripts/simple-deploy.exe mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/simple-deploy.exe mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

## Dry-run

`dry-run` ничего не собирает, не меняет VM и не двигает baseline. Он проверяет:

- обязательные значения `tools-ci/.env` и наличие `tools-ci/local.secrets.env`;
- локальные backend/frontend source и target репозитории;
- `BACKEND_APP_ROOT_DIR`, backend requirements и импорт
  `BACKEND_DJANGO_SETTINGS_MODULE`, если backend venv уже есть;
- идемпотентность data INSERT SQL, которые попадут в `run_all_insert`, если
  не передан `--skip-data-sql-artifacts`;
- наличие default maintenance stub archive, если `maintenance_stub_enabled=true`;
- доступность origin URL без интерактивного `git ls-remote`;
- Windows-команды `git`, `node`, `npm`, `ssh`, `scp` и путь к Git Bash;
- SSH-доступ к app VM и DB VM;
- права записи в staging, backend/frontend release paths и backup path;
- наличие `APP_WORKDIR`, venv activate script и `manage.py`;
- доступность `psql` и реальный PostgreSQL login на DB VM;
- sudo-разрешения для service steps без выполнения сервисных команд;
- HTTP endpoint DEV-стенда, если healthcheck включен;
- настройки Outlook email, если уведомление включено.

Каждая проверка печатается как `PASS`, `FAIL`, `WARN` или `SKIP`. Полный вывод
пишется одновременно в консоль и в `logs/<timestamp>-<command>.log`.

## Build artifacts

`build` запускает `tools-ci/builder/create_release.py`, подготавливает frontend
`.env` файлы и создает директорию релиза.

Каждая попытка build автоматически записывается в
`local_state/simple_deploy.sqlite3`: сначала как `started`, затем как `success`
или `failed`. Таблица `releases` обновляется только после успешной сборки и
создания `release_manifest.json`.

Backend DB-генераторы копируются во временную директорию
`BACKEND_SOURCE_REPO_PATH/build_scripts/` из
`tools-ci/builder/scripts/additional_artifacts/` и запускаются из корня backend
source repo через Python backend venv. После упаковки SQL-артефактов временная директория
удаляется. Python-окружение для генераторов ищется внутри
`BACKEND_SOURCE_REPO_PATH` по `BACKEND_BUILD_VENV_RELATIVE_PATH`; если его нет,
build создает venv и устанавливает production requirements из
`BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH`.

Schema SQL генерируется offline через Django schema editor в режиме
`collect_sql=True`. Для каждого контура создается отдельный архив:

- `db_schema_dev_r_<release>-c_<commit>.tar.gz`;
- `db_schema_test_r_<release>-c_<commit>.tar.gz`;
- `db_schema_prod_r_<release>-c_<commit>.tar.gz`.

Внутри schema-архива лежит единственный entrypoint
`summary_sql_<contour>_*.sql`. Build по умолчанию создает data SQL-архивы:

- `db_insert_r_<release>-c_<commit>.tar.gz` с `run_all_insert_<commit>.sql`;
- `db_update_sequential_r_<release>-c_<commit>.tar.gz` с `run_all_update_sequential_<commit>.sql`;
- `db_update_parallel_r_<release>-c_<commit>.tar.gz` с `run_all_update_parallel_<commit>.sh`;
- `db_set_default_sequential_r_<release>-c_<commit>.tar.gz` с `run_all_set_default_sequential_<commit>.sql`;
- `db_set_default_parallel_r_<release>-c_<commit>.tar.gz` с `run_all_set_default_parallel_<commit>.sh`.

В штатном full deploy Windows runner применяет `db_insert` и
`db_update_parallel` после schema SQL. `db_update_parallel` содержит только
`kind=update`; чтобы отдельно применить `kind=set_default`, запускайте `deploy`
или `pipeline` с `--include-set-default-sql`. `db_update_sequential` и
`db_set_default_sequential` остаются аварийными ручными вариантами для
последовательного запуска на одной DB-сессии.

## Deploy

`deploy` выбирает релиз по `--latest` или `--build-version`, выбирает schema
SQL-архив по `--contour`, загружает его на DB VM и применяет
`summary_sql_<contour>_*.sql` через:

```bash
psql --set=ON_ERROR_STOP=1 --single-transaction
```

Full deploy сначала выполняет DB data update preflight cleanup, чтобы повторный
запуск после `KeyboardInterrupt` или падения не накатывал новый релиз поверх
еще работающего update. На DB VM runner останавливает хвосты
`run_all_update_parallel_*.sh`, `run_all_set_default_parallel_*.sh` и их `psql`
процессов, затем завершает PostgreSQL backend-и с
`application_name=simple-deploy-data-update`.
Затем runner загружает app-артефакты, останавливает сервисы, распаковывает
`tools-ci/maintenance_stub/maintenance_stub.tar.gz` в `FRONTEND_RELEASE_PATH`,
проверяет по HTTP, что `https://DEV_DOMAIN/` отдает именно заглушку, а не
основной frontend, и при остановленном backend выполняет schema SQL, `run_all_insert_*.sql`,
`run_all_update_parallel_*.sh`, опционально `run_all_set_default_parallel_*.sh`
при `--include-set-default-sql`, и DB maintenance. Insert выполняется тихо:
полный `psql` output пишется на DB VM в `logs/insert/`, а в терминал выводится
только итоговая длительность. После DB-части runner
распаковывает backend, выполняет `after_unpack`, Django management-команды и
`after_migrate` service steps. Настоящий frontend распаковывается последним,
после успешного старта backend, заменяя заглушку; затем выполняются
`after_frontend_unpack` service steps, например `sudo /bin/systemctl stop nginx`
и затем `sudo /bin/systemctl start nginx`,
и только потом healthcheck.

Если `deploy` или `pipeline` падает после выбора релиза, runner
автоматически пишет failed attempt в `deployment_attempts` без сдвига baseline.
Для TEST/PROD, если применение выполнялось внешним или ручным процессом,
используйте `mark-applied` или `mark-failed`.

Ручное применение schema и data SQL на TEST/PROD описано в
`../docs/runbooks/manual-sql-release-run.md`.

## Outlook email

Уведомление об успешном deploy отправляется через установленный desktop Outlook
на рабочей машине. Включается в `tools-ci/windows_pipeline.local.json`:

```json
{
  "outlook_email_enabled": true,
  "outlook_email_recipients": [
    "dev-team@example.local",
    "owner@example.local"
  ],
  "outlook_email_cc": [],
  "outlook_email_subject": "Деплой успешно завершен: {build_version}",
  "outlook_email_body": "Deploy completed.\n\nBuild: {build_version}\nStand: {stand_url}\nRelease dir: {release_dir}\n\nArtifacts:\n{artifacts_text}\n\nChanges:\n{release_changelog_text}",
  "outlook_email_required": false
}
```

Доступные шаблоны: `{build_version}`, `{stand_url}`, `{dev_domain}`,
`{release_dir}`, `{artifacts_text}`, `{release_changelog_text}`. Если
`outlook_email_required` равен `false`, ошибка Outlook будет записана как
`WARN` и не превратит уже успешный deploy в ошибку.

## Расписание

Старый Windows Task Scheduler runbook для запуска `pipeline` удален из
поддерживаемого пути. Текущий локальный executor - постоянный
`simple-deploy worker`, который исполняет уже созданные queued jobs.

Будущее расписание должно создаваться внутри API/UI как local jobs с временем
`run_after`, а worker должен запускать их после наступления этого времени.
Эта задача ведется в `../PRODUCT_BACKLOG.MD`.
