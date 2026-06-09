# E2E пайплайн через Windows/Python tools

## Статус

Это основной операторский путь для рабочей Windows-машины без обязательного WSL
или Docker. Точка входа - `tools-ci/tools/windows_pipeline.py`; runner использует Windows
Python, Git, Node/npm, Git Bash и Windows OpenSSH.

Общий продуктовый процесс описан в `../PIPELINE.MD`. Legacy-вариант через
Ansible/WSL описан в `../ansible-ci/PIPELINE.MD`.

## Конфигурация

Основные локальные файлы:

- `.env` - пути к репозиториям, VM, домены, директории деплоя и build settings.
- `local.secrets.env` - секреты PostgreSQL для DB VM.
- `windows_pipeline.local.json` - service steps, management commands, healthcheck
  и Outlook email.

Локальное состояние SQL baseline хранится в
`local_state/simple_deploy.sqlite3` и не коммитится. Для каждого контура
`dev`, `test`, `prod` хранится backend commit, от которого следующий build
строит schema SQL-диапазон. В этой же SQLite-базе runner хранит историю build
attempts и deploy attempts: успешные build попадают в `releases`, упавшие build
фиксируются в `build_attempts`, упавшие deploy - в `deployment_attempts` без
сдвига baseline.

## Команды оператора

Первичная инициализация baseline:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour dev --backend-commit <dev_backend_commit>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour test --backend-commit <test_backend_commit>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour prod --backend-commit <prod_backend_commit>
```

Если есть локальный manifest уже примененного релиза:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour test --build-version <previous_successful_release_version>
```

Обычная проверка и сборка:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build
```

Деплой уже собранного релиза:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --latest
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --build-version <version>
```

Полный локальный цикл:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py pipeline --contour dev
```

`dry-run` проверяет data SQL по умолчанию, а `build` и `pipeline` генерируют
data SQL-артефакты по умолчанию. Явный schema-only режим для аварийных случаев:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build --skip-data-sql-artifacts
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py pipeline --contour dev --skip-data-sql-artifacts
```

Фиксация внешнего TEST/PROD результата:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

## Dry-run

`dry-run` не меняет VM и не запускает сборку. Он проверяет:

- обязательные значения `.env` и наличие `local.secrets.env`;
- локальные backend/frontend source и target репозитории;
- `BACKEND_APP_ROOT_DIR`, backend requirements и импорт
  `BACKEND_DJANGO_SETTINGS_MODULE`, если backend venv уже есть;
- идемпотентность data INSERT SQL, которые попадут в `run_all_insert`, если
  не передан `--skip-data-sql-artifacts`;
- доступность origin URL без интерактивного `git ls-remote`;
- Windows-команды `git`, `node`, `npm`, `ssh`, `scp` и путь к Git Bash;
- SSH-доступ к app VM и DB VM;
- права записи в staging, backend/frontend release paths и backup path;
- наличие `APP_WORKDIR`, venv activate script и `manage.py`;
- доступность `psql` и реальный PostgreSQL login на DB VM;
- sudo-разрешения для service steps без выполнения самих сервисных команд;
- HTTP endpoint DEV-стенда, если healthcheck включен;
- настройки Outlook email, если уведомление включено.

Каждая проверка печатается как `PASS`, `FAIL`, `WARN` или `SKIP`.

## Build

`build` подготавливает frontend `.env` файлы, запускает существующий сборщик
`tools-ci/builder/create_release.py` и создает директорию релиза.

Результат build:

- backend runtime archive;
- frontend runtime archive для DEV;
- schema SQL-архивы `db_schema_dev_*`, `db_schema_test_*`, `db_schema_prod_*`;
- `release_manifest.json` с commit SHA и `db_schema_metadata`.

Schema SQL генерируется offline по Git-диапазону `baseline..HEAD` backend source
repo. Если baseline хотя бы одного контура не задан, build должен завершиться
ошибкой до упаковки релиза.

## Deploy

`deploy` выбирает релиз по `--latest` или `--build-version`, выбирает schema
SQL-архив по `--contour` и выполняет порядок:

1. DB data update preflight cleanup на DB VM: остановка хвостов
   `run_all_update_parallel_*.sh`/их `psql` процессов после прерванного deploy
   и завершение PostgreSQL backend-ов с
   `application_name=simple-deploy-data-update`.
2. Создание remote staging-директории на app VM.
3. Загрузка backend/frontend/maintenance-stub архивов через `scp`.
4. Backup текущих директорий, если `backup_enabled: true`.
5. Service steps фазы `before_unpack`: обычно остановка backend/worker-сервисов,
   но не nginx, чтобы он отдавал maintenance-заглушку.
6. Распаковка maintenance-заглушки в `FRONTEND_RELEASE_PATH`.
7. Загрузка и применение `summary_sql_<contour>_*.sql` на DB VM через `psql`
    с `ON_ERROR_STOP` и одной транзакцией.
8. Применение `run_all_insert_*.sql` и `run_all_update_parallel_*.sh`, если
   `data_sql_enabled=true`. `kind=set_default` внутри update runner-а
   пропускается по умолчанию и включается только флагом
   `--include-set-default-sql`.
9. DB maintenance SQL/scripts фаз `before_unpack`, `before_migrate` и
   `after_migrate`, включая информационные SQL-отчеты в порядке `sql_scripts`.
10. Распаковка backend с `--strip-components=1`.
11. Service steps фазы `after_unpack`.
12. Django management-команды из `windows_pipeline.local.json` или дефолт:
    `migrate --fake`, затем `sync_action_role`.
13. Service steps фазы `after_migrate`.
14. Распаковка финального frontend поверх заглушки.
15. Service steps фазы `after_frontend_unpack`, например
    `sudo /bin/systemctl stop nginx`, затем `sudo /bin/systemctl start nginx`.
16. HTTP healthcheck и проверка `build_version` в портале.
17. Фиксация успешного применения контура в локальной SQLite-базе.
18. Outlook email об успешном deploy, если включен.

Если любой обязательный шаг завершается ошибкой, команда падает. Успешный
baseline двигается только после завершенного deploy или явной команды
`mark-applied`.

## Логи и расширения

Каждый запуск пишет вывод одновременно в консоль и в
`logs/<timestamp>-<command>.log`.

Основные точки расширения в `windows_pipeline.local.json`:

- `db_maintenance_sql` и `sql_scripts`;
- `management_commands`;
- `service_steps`;
- `healthcheck_commands`;
- `outlook_email_*`.

Практическая настройка runner описана в `README.MD`. Пример запуска по
расписанию через Windows Task Scheduler лежит в
`tools-ci/tools/windows_task_scheduler/`.
