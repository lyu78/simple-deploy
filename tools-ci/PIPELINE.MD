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
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run --include-data-sql
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py build --include-data-sql
```

Деплой уже собранного релиза:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --latest
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py deploy --contour dev --build-version <version>
```

Полный локальный цикл:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py pipeline --contour dev
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py pipeline --contour dev --include-data-sql
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
  передан `--include-data-sql`;
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

1. DB maintenance SQL фазы `before_unpack`.
2. Service steps фазы `before_unpack`.
3. Создание remote staging-директории на app VM.
4. Загрузка backend/frontend архивов через `scp`.
5. Backup текущих директорий, если `backup_enabled: true`.
6. Очистка первого уровня target-директорий с сохранением корневого `.env`.
7. Распаковка backend/frontend с `--strip-components=1`.
8. Service steps фазы `after_unpack`.
9. DB maintenance SQL фазы `before_migrate`.
10. Загрузка и применение `summary_sql_<contour>_*.sql` на DB VM через `psql`
    с `ON_ERROR_STOP` и одной транзакцией.
11. Django management-команды из `windows_pipeline.local.json` или дефолт:
    `migrate --fake`, затем `sync_action_role`.
12. DB maintenance SQL/scripts фазы `after_migrate`, включая информационные
    SQL-отчеты в порядке `sql_scripts`, затем service steps фазы
    `after_migrate`.
13. HTTP healthcheck и проверка `build_version` в портале.
14. Фиксация успешного применения контура в локальной SQLite-базе.
15. Outlook email об успешном deploy, если включен.

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
