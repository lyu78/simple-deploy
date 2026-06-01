# Windows/Python runner

Это практическая инструкция для основного operator flow `simple-deploy` на
Windows-машине без обязательного WSL или Docker. Точка входа:
`tools-ci/tools/windows_pipeline.py`.

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
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org --upgrade pip
.venv/Scripts/python.exe -m pip install --disable-pip-version-check --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org -r tools-ci/requirements.dev.txt

cp .env.example .env
cp local.secrets.env.example local.secrets.env
cp tools-ci/windows_pipeline.example.json windows_pipeline.local.json
```

Заполните `.env` путями к backend/frontend репозиториям, VM-хостами, доменами,
директориями деплоя и build settings. Для Windows-only режима можно оставить
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

В `local.secrets.env` укажите доступ к PostgreSQL:

```properties
DB_LOGIN_USER=postgres
DB_LOGIN_PASSWORD=<password>
```

Для `dry-run`, `deploy` и `pipeline` `DB_LOGIN_PASSWORD` обязателен: пустое
значение и placeholder `change-me` считаются ошибкой конфигурации.

## Локальный runner config

`windows_pipeline.local.json` хранит локальные расширения pipeline:

- `service_steps` - сервисные команды на app VM;
- `management_commands` - Django management-команды;
- `db_maintenance_sql` и `sql_scripts` - дополнительные SQL-шаги;
- `healthcheck_commands` - дополнительные проверки;
- `outlook_email_*` - уведомление через desktop Outlook;
- `backup_enabled` и связанные настройки backup.

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
`after_migrate`. Шаги без `phase` выполняются как `after_migrate`.

Во время `dry-run` runner получает список доступных sudo-команд через
`sudo -n -l`, затем проверяет каждую sudo service step без выполнения самой
сервисной команды. Если для шага нужна отдельная команда проверки, задайте
`permission_check_command` тоже через `sudo`.

## Команды оператора

Первичная инициализация baseline выполняется один раз перед первой сборкой.
Укажите фактические backend commit, которые уже успешно лежат на контурах:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour dev --backend-commit <dev_backend_commit>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour test --backend-commit <test_backend_commit>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour prod --backend-commit <prod_backend_commit>
```

Если есть локальный `release_manifest.json` уже примененного релиза, baseline
можно поставить по версии:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py set-baseline --contour test --build-version <previous_successful_release_version>
```

Обычная диагностика:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py dry-run
```

Сборка релиза:

```bash
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

Фиксация внешнего TEST/PROD результата:

```bash
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/python.exe tools-ci/tools/windows_pipeline.py mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

## Dry-run

`dry-run` ничего не собирает, не меняет VM и не двигает baseline. Он проверяет:

- обязательные значения `.env` и наличие `local.secrets.env`;
- локальные backend/frontend source и target репозитории;
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

Backend DB-генераторы копируются во временную директорию
`BACKEND_SOURCE_REPO_PATH/build_scripts/` из
`tools-ci/builder/scripts/additional_artifacts/` и запускаются из корня backend
source repo через Git Bash. После упаковки SQL-артефактов временная директория
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
`summary_sql_<contour>_*.sql`. Build также может создать data SQL-архивы:

- `db_insert_r_<release>-c_<commit>.tar.gz` с `run_all_insert_<commit>.sql`;
- `db_update_r_<release>-c_<commit>.tar.gz` с `run_all_update_<commit>.sql`.

Data SQL-архивы остаются артефактами отдельного DB migration flow. Windows
runner deploy применяет только schema SQL-архив выбранного контура.

## Deploy

`deploy` выбирает релиз по `--latest` или `--build-version`, выбирает schema
SQL-архив по `--contour`, загружает его на DB VM и применяет
`summary_sql_<contour>_*.sql` через:

```bash
psql --set=ON_ERROR_STOP=1 --single-transaction
```

После schema SQL runner распаковывает backend/frontend, выполняет service steps,
Django management-команды, healthcheck и при успешном завершении двигает baseline
выбранного контура. Для TEST/PROD, если применение выполнялось внешним или
ручным процессом, используйте `mark-applied` или `mark-failed`.

Ручное применение schema SQL на TEST/PROD описано в
`../instructions/manual-schema-sql-deploy.md`.

## Outlook email

Уведомление об успешном deploy отправляется через установленный desktop Outlook
на рабочей машине. Включается в `windows_pipeline.local.json`:

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

## Запуск по расписанию

Пример Windows Task Scheduler лежит в
`tools-ci/tools/windows_task_scheduler/README.md`. Используйте одну задачу,
которая запускает полный `pipeline`; не ставьте отдельные пересекающиеся задачи
для `build` и `deploy --latest`.
