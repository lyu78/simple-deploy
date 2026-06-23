# E2E пайплайн через Windows/Python tools

## Статус

Это основной операторский путь для рабочей Windows-машины без обязательного WSL
или Docker. Точка входа - `.venv/Scripts/simple-deploy.exe`; runner использует
Windows Python, Git, Node/npm, Git Bash и Windows OpenSSH.

Общий продуктовый процесс описан в `../PIPELINE.MD`. Legacy-вариант через
Ansible/WSL описан в `../legacy/ansible-ci/PIPELINE.MD`.

## Конфигурация

Основные локальные файлы:

- `tools-ci/.env` - пути к репозиториям, VM, домены, директории деплоя и build settings.
- `tools-ci/local.secrets.env` - секреты PostgreSQL для DB VM.
- `tools-ci/windows_pipeline.local.json` - service steps, management commands, healthcheck
  и Outlook email.

Локальное состояние SQL baseline хранится в
`local_state/simple_deploy.sqlite3` и не коммитится. Для каждого контура
`dev`, `test`, `prod` хранится backend commit, от которого следующий build
строит schema SQL-диапазон. В этой же SQLite-базе runner хранит историю build
attempts и deploy attempts: успешные build попадают в `releases`, упавшие build
фиксируются в `build_attempts`, упавшие deploy - в `deployment_attempts` без
сдвига baseline.

В этой же SQLite-базе есть таблицы `local_jobs`, `external_requests` и
`worker_heartbeat`.
Они используются web/API v1: локальные jobs отражают queued/running/terminal
операции, созданные через API или CLI-совместимый runner, а external requests -
заявки TEST/PROD и ручную фиксацию внешнего процесса. `worker_heartbeat`
показывает operator UI, запущен ли локальный polling worker и какую job он
обрабатывает.

## Команды оператора

Первичная инициализация baseline:

```bash
.venv/Scripts/simple-deploy.exe set-baseline --contour dev --backend-commit <dev_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour test --backend-commit <test_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour prod --backend-commit <prod_backend_commit>
```

Если есть локальный manifest уже примененного релиза:

```bash
.venv/Scripts/simple-deploy.exe set-baseline --contour test --build-version <previous_successful_release_version>
```

Обычная проверка и сборка:

```bash
.venv/Scripts/simple-deploy.exe dry-run
.venv/Scripts/simple-deploy.exe build
```

Деплой уже собранного релиза:

```bash
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest
.venv/Scripts/simple-deploy.exe deploy --contour dev --build-version <version>
```

Полный локальный цикл:

```bash
.venv/Scripts/simple-deploy.exe pipeline --contour dev
```

Web/API и local worker:

```bash
.venv/Scripts/python.exe -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host 127.0.0.1 --port 8000
.venv/Scripts/simple-deploy.exe worker --poll-interval 2
```

`POST /api/jobs` только создает queued job в SQLite. Выполнение делает
отдельный `simple-deploy worker`, который атомарно забирает queued jobs,
пишет job log и обновляет heartbeat для `/api/worker`. Разовый режим
`.venv/Scripts/simple-deploy.exe worker --once` удобен для проверки очереди и
возвращает отдельный idle exit code, если queued jobs нет.

`dry-run` проверяет data SQL по умолчанию, а `build` и `pipeline` генерируют
data SQL-артефакты по умолчанию. Явный schema-only режим для аварийных случаев:

```bash
.venv/Scripts/simple-deploy.exe build --skip-data-sql-artifacts
.venv/Scripts/simple-deploy.exe pipeline --contour dev --skip-data-sql-artifacts
```

Фиксация внешнего TEST/PROD результата:

```bash
.venv/Scripts/simple-deploy.exe mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/simple-deploy.exe mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

## Dry-run

`dry-run` не меняет VM и не запускает сборку. Он проверяет:

- обязательные значения `tools-ci/.env` и наличие `tools-ci/local.secrets.env`;
- локальные backend/frontend source и target репозитории;
- `BACKEND_APP_ROOT_DIR`, backend requirements и импорт
  `BACKEND_DJANGO_SETTINGS_MODULE`, если backend venv уже есть;
- идемпотентность data INSERT SQL, которые попадут в `run_all_insert`, если
  не передан `--skip-data-sql-artifacts`;
- наличие maintenance stub archive, если `maintenance_stub_enabled=true`;
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
- frontend runtime archives для DEV, TEST и PROD;
- schema SQL-архивы `db_schema_dev_*`, `db_schema_test_*`, `db_schema_prod_*`;
- data SQL-архивы `db_insert_*`, `db_update_sequential_*`,
  `db_update_parallel_*`, `db_set_default_sequential_*` и
  `db_set_default_parallel_*`, если не передан `--skip-data-sql-artifacts`;
- `release_manifest.json` с commit SHA и `db_schema_metadata`.

Schema SQL генерируется offline по Git-диапазону `baseline..HEAD` backend source
repo. Если baseline хотя бы одного контура не задан, build должен завершиться
ошибкой до упаковки релиза.

## Deploy

`deploy` выбирает релиз по `--latest` или `--build-version`, выбирает schema
SQL-архив по `--contour` и выполняет порядок:

1. DB data update preflight cleanup на DB VM: остановка хвостов
   `run_all_update_parallel_*.sh`, `run_all_set_default_parallel_*.sh` и их
   `psql` процессов после прерванного deploy, затем завершение PostgreSQL
   backend-ов с `application_name=simple-deploy-data-update`.
2. Создание remote staging-директории на app VM.
3. Загрузка backend/frontend/maintenance-stub архивов через `scp`.
4. Backup текущих директорий, если `backup_enabled: true`.
5. Service steps фазы `before_unpack`: обычно остановка backend/worker-сервисов,
   но не nginx, чтобы он отдавал maintenance-заглушку.
6. Распаковка maintenance-заглушки в `FRONTEND_RELEASE_PATH`.
7. HTTP-проверка `https://DEV_DOMAIN/`: страница должна содержать
   `maintenance_stub_verify_marker`, иначе DB-часть не стартует.
8. Загрузка и применение `summary_sql_<contour>_*.sql` на DB VM через `psql`
    с `ON_ERROR_STOP` и одной транзакцией.
9. Применение `run_all_insert_*.sql` и `run_all_update_parallel_*.sh`, если
   `data_sql_enabled=true`. `kind=set_default` выполняется отдельным
   `run_all_set_default_parallel_*.sh` только при флаге
   `--include-set-default-sql`.
10. DB maintenance SQL/scripts фаз `before_unpack`, `before_migrate` и
   `after_migrate`, включая информационные SQL-отчеты в порядке `sql_scripts`.
11. Распаковка backend с `--strip-components=1`.
12. Service steps фазы `after_unpack`.
13. Django management-команды из `tools-ci/windows_pipeline.local.json` или дефолт:
    `migrate --fake`, затем `sync_action_role`.
14. Service steps фазы `after_migrate`.
15. Распаковка финального frontend поверх заглушки.
16. Service steps фазы `after_frontend_unpack`, например
    `sudo /bin/systemctl stop nginx`, затем `sudo /bin/systemctl start nginx`.
17. HTTP healthcheck и проверка `build_version` в портале.
18. Фиксация успешного применения контура в локальной SQLite-базе.
19. Outlook email об успешном deploy, если включен.

Если любой обязательный шаг завершается ошибкой, команда падает. Успешный
baseline двигается только после завершенного deploy или явной команды
`mark-applied`.

## Логи и расширения

Каждый запуск пишет вывод одновременно в консоль и в
`logs/<timestamp>-<command>.log`.

Основные точки расширения в `tools-ci/windows_pipeline.local.json`:

- `db_maintenance_sql` и `sql_scripts`;
- `management_commands`;
- `service_steps`;
- `healthcheck_commands`;
- `outlook_email_*`.

Практическая настройка runner и операционный запуск пары `web + worker`
описаны в `README.MD`. Внешний Windows Task Scheduler больше не является
поддерживаемым способом запуска `pipeline` по расписанию; будущие scheduled
local jobs ведутся в `../PRODUCT_BACKLOG.MD`.
