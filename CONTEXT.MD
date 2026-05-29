# Контекст проекта

Проект автоматизирует одностороннюю доставку изменений из внешнего контура во
внутренний контур, сборку релизных архивов и обновление локального DEV-стенда.
Рабочая машина является управляющей точкой: на ней лежат рабочие копии внешних и
внутренних репозиториев, запускается сборщик и с нее Ansible подключается к VM.

## Текущий Windows-only режим

Актуальный рабочий путь для машины без WSL/Docker - `tools/windows_pipeline.py`.
Runner использует Windows Python, Git, Node/npm, Git Bash и Windows OpenSSH
(`ssh`, `scp`). Ansible остается в репозитории как legacy-вариант для Linux/WSL
control node, но основная отладка в последних изменениях велась вокруг
Windows-only runner.

Команды:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py dry-run
.venv/Scripts/python.exe tools/windows_pipeline.py build
.venv/Scripts/python.exe tools/windows_pipeline.py deploy --latest
.venv/Scripts/python.exe tools/windows_pipeline.py deploy --build-version <version>
.venv/Scripts/python.exe tools/windows_pipeline.py pipeline
```

Каждый запуск пишет вывод одновременно в консоль и отдельный файл
`logs/<timestamp>-<command>.log`; `logs/` игнорируется Git.

SSH-доступ к VM не интерактивный: runner работает в batch-режиме и рассчитан на
ключ или ssh-agent. В `.env` поддерживаются:

- `SSH_KEY_PATH` - общий ключ для app/DB VM;
- `APP_SSH_KEY_PATH` - ключ только для app VM;
- `DB_SSH_KEY_PATH` - ключ только для DB VM.

Относительные пути к ключам ищутся сначала от текущей директории запуска, затем
от домашней директории Windows-пользователя. Пример для входа
`ssh -i ./simple-deploy deploy-user@192.0.2.10`:

```properties
APP_SSH_KEY_PATH=./simple-deploy
APP_VM_USER=deploy-user
```

Секреты PostgreSQL лежат в `local.secrets.env`. Для `dry-run`, `deploy` и
`pipeline` `DB_LOGIN_USER` и `DB_LOGIN_PASSWORD` обязательны; пустой пароль и
placeholder `change-me` считаются ошибкой конфигурации. Dry-run проверяет не
только SSH до DB VM и наличие `psql`, но и реальный PostgreSQL login через
`SELECT 1`.

## Windows-only deploy contract

`REMOTE_TMP_ROOT` - staging-директория на app VM. В нее через `scp` загружаются
архивы релиза, после чего они распаковываются в финальные директории:

- `BACKEND_RELEASE_PATH`;
- `FRONTEND_RELEASE_PATH`.

Dry-run под `APP_VM_USER` проверяет наличие и права `rwx` для `REMOTE_TMP_ROOT`,
`BACKEND_RELEASE_PATH`, `FRONTEND_RELEASE_PATH`, `APP_WORKDIR` и, если включен
backup, `BACKUP_ROOT_BASE`. Проверка выводит effective `id`, `stat`, `namei -l`,
`getfacl` при наличии, затем реально создает и удаляет тестовый файл
`.simple-deploy-write-check-$$`.

Распаковка устроена так:

1. target-директория должна существовать заранее;
2. перед распаковкой удаляется содержимое первого уровня, кроме корневого `.env`;
3. архив распаковывается с `--strip-components=1`.

Это важно для React/frontend архива: если внутри архива лежит директория `build`,
а `FRONTEND_RELEASE_PATH` уже указывает на финальный `build`, содержимое архива
попадает прямо в target, без вложенного `build/build`. Аналогично backend архив с
верхней директорией `example_backend_app` распаковывается содержимым в
`BACKEND_RELEASE_PATH`.

Django management-команды выполняются после распаковки так:

```bash
cd "$APP_WORKDIR"
. "$APP_VENV_ACTIVATE_PATH"
python "$APP_MANAGE_PY_PATH" migrate
python "$APP_MANAGE_PY_PATH" sync_action_role
```

Если `management_commands` в `windows_pipeline.local.json` пустой, runner строит
команды из `APP_MANAGE_PY_PATH`. Если локальный `windows_pipeline.local.json`
содержит явные `management_commands`, они имеют приоритет. Dry-run проверяет, что
`APP_MANAGE_PY_PATH` существует и читается относительно `APP_WORKDIR`.

## Service steps и права

Команды запуска/проверки сервисов задаются в `windows_pipeline.local.json` в
`service_steps`. Поддерживаемые фазы: `before_unpack`, `after_unpack`,
`after_migrate`; шаги без `phase` считаются `after_migrate`. Порядок выполнения
соответствует порядку в JSON.

Пример:

```json
{
  "service_steps": [
    {
      "name": "start nginx",
      "phase": "after_migrate",
      "command": "sudo /bin/systemctl start nginx",
      "permission_check_command": "sudo /bin/systemctl start nginx"
    },
    {
      "name": "status nginx",
      "phase": "after_migrate",
      "command": "sudo /bin/systemctl status nginx",
      "permission_check_command": "sudo /bin/systemctl status nginx"
    }
  ]
}
```

Сервисные команды запускаются только через `sudo`, но пользователь не должен быть
в полном sudo/wheel. Для него создается точечное правило
`/etc/sudoers.d/simple-deploy` через `visudo` с `NOPASSWD` только для нужных
`/bin/systemctl start/status/restart ...` команд. Если `systemctl` лежит не в
`/bin`, путь нужно проверить через `command -v systemctl` и использовать
фактический путь.

Dry-run для sudo service steps сначала смотрит общий список доступных команд через
`sudo -n -l`, затем проверяет каждый шаг через `sudo -n -l <команда без sudo>`.
Реальная сервисная команда на dry-run не выполняется, даже если
`permission_check_command` задан как `sudo /bin/systemctl start ...`.

## Финальный healthcheck портала

После deploy runner проверяет HTTP-доступность `https://DEV_DOMAIN/`, затем ищет
текущий `build_version`:

1. в HTML главной страницы;
2. если это React и версия не найдена в HTML - в JS assets из `<script src=...>`
   того же origin.

Проверку можно отключить в `windows_pipeline.local.json`:

```json
"portal_version_check_enabled": false
```

Количество JS assets ограничивается `portal_version_asset_limit`.

## Outlook email

Success email is configured in `windows_pipeline.local.json`, not `.env`. To
enable it set `outlook_email_enabled: true`, provide non-empty
`outlook_email_recipients`, `outlook_email_subject`, and `outlook_email_body`,
and keep desktop Outlook installed/configured for the current Windows user.
Optional `outlook_email_cc` adds copy recipients. `outlook_email_required:
false` logs Outlook send failures as WARN after an otherwise successful deploy;
`true` makes them fail the pipeline. `dry-run` validates recipients, templates
and Outlook COM creation. Available template variables are `{build_version}`,
`{stand_url}`, `{dev_domain}`, `{release_dir}`, `{artifacts_text}`, and
`{release_changelog_text}`. After successful deploy the email attaches
`release_manifest.json` from the release directory when the file exists; a
missing manifest is logged as WARN and does not block the email by itself.

## Главная точка входа

Штатный запуск один:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml
```

`playbooks/pipeline.yml` только управляет порядком и подключает внутренние этапы:

- `playbooks/stages/build_release.yml` - подготовка окружения и запуск сборщика;
- `playbooks/stages/deploy_local_contour.yml` - обновление локального DEV-контура.

Повторная раскатка уже собранного релиза идет через тот же вход:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml \
  -e run_build=false -e build_version=<версия>
```

## Структура

- `builder/` - существующая сборочная подсистема: `create_release.py`, Python-код,
  shell-архиваторы и настройки frontend-сборки.
- `requirements.dev.txt` - Python-зависимости сборщика из `builder/`.
- `requirements.ansible.txt` - Python-зависимости Ansible-слоя.
- `playbooks/` - единый pipeline, dry run и внутренние этапы.
- `roles/` - Ansible-роли доставки артефактов, DB-работ, сервисных команд,
  миграций, healthcheck и отчета.
- `group_vars/dev.yml` - схема DEV-контура и производные значения.
- `.env` - локальная конфигурация рабочей машины, не хранится в репозитории.
- `.env.example` - пример `.env` с нереальными, но похожими на боевые значениями.
- `group_vars/vault.yml` - секреты Ansible Vault, не хранится в репозитории.
- `builder/settings/*/.env.template` - шаблоны frontend `.env`; реальные
  `builder/settings/*/.env` генерируются локально перед сборкой и игнорируются Git.

## Конфигурация

В `.env` обязательно задаются адреса VM, SSH-пользователи, пути к рабочим копиям
репозиториев, домены и пути деплоя на app VM.

`APP_VM_USER` и `DB_VM_USER` обязательны отдельно. Если `DB_VM_USER` не указан,
Ansible должен падать на проверке конфигурации, а не молча брать пользователя app VM.

`PROJECT_ROOT_WSL`, `RELEASE_ROOT_WSL` и `RELEASE_ROOT_BASH` необязательны:

- корень проекта по умолчанию считается от `playbook_dir`;
- директория релизов по умолчанию равна `<корень проекта>/releases`;
- Git Bash-путь к релизам строится автоматически из WSL-пути.

`BACKEND_TARGET_REPO_PATH_BASH` существует осознанно: backend shell-архиватору нужен
bash-путь к backend-репозиторию. Для frontend аналога сейчас нет, потому что
frontend-архиватор запускается из рабочей директории frontend-репозитория и
использует только `RELEASE_ROOT_BASH`.

## Граница ответственности

`builder/create_release.py`:

- синхронизирует внешние и внутренние рабочие копии;
- собирает backend/frontend-архивы;
- пушит ветки во внутренние репозитории;
- не знает про VM и раскатку.

Ansible:

- читает `.env` и vault-секреты;
- вычисляет дефолтные пути проекта и релизов;
- создает `builder/settings/*/.env` из tracked-шаблонов `.env.template` и
  подставляет туда домены;
- запускает `builder/create_release.py`;
- выбирает собранный релиз;
- доставляет архивы на app VM;
- выполняет DB-работы, миграции, сервисные команды и healthcheck.

## Dry Run

Безопасная диагностика:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Dry run ничего не распаковывает, не запускает SQL-работы, миграции и рестарты.
Самые ранние проверки:

- `.env` заполнен обязательными параметрами;
- в локальных backend/frontend-репозиториях настроен `origin`;
- доступны app VM и DB VM по сети;
- SSH-аутентификация проходит с одним парольным prompt, без повторного долбления
  неправильным паролем.

Дальше проверяются локальные директории, артефакты, директории на VM, права,
runtime-команды, PostgreSQL через `psql` на DB VM и HTTP endpoint стенда.

Практические детали dry run:

- статус Ansible-задачи (`ok`, `skipping`) описывает только выполнение самого playbook;
- готовность контура печатается явно как `DRY-RUN PASS`, `DRY-RUN FAIL` или `DRY-RUN SKIP`;
- итоговая готовность определяется по списку `issues` в сводке и финальному `fail`, если проблемы есть;
- локальные Windows-пути к репозиториям проверяются через Windows Git (`cmd.exe /C git`);
- сетевая проверка origin выполняется через `curl --head --location` по полной ссылке
  из `git remote get-url origin`; `git ls-remote` не используется, чтобы не запускать
  интерактивную Git-аутентификацию;
- Node.js/npm проверяются в Windows-контексте через `cmd.exe /C`, потому что сборщик
  работает с Windows-путями и Git Bash;
- `psql` проверяется и используется на DB VM через SSH; управляющей WSL-машине
  PostgreSQL client не нужен;
- интерактивные Git/psql prompts отключены;
- системные, Git, TCP и PostgreSQL-проверки ограничены `dry_run_command_timeout_seconds`;
- TCP-доступность app VM, DB VM и PostgreSQL проверяется через `nc -z -w`;
- удаленные проверки app VM пропускаются, если SSH-аутентификация уже не прошла.

По умолчанию dry run не требует `build_version` и не проверяет конкретные архивы:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Проверка архивов включается явно через `-e build_version=<версия>` или
`-e use_latest_release=true`.

## Продуктовая модель dry run

Dry run является проверкой готовности контура к работе, а не проверкой того, что
Ansible умеет выполнить отдельную техническую задачу. Поэтому вывод разделен на
два уровня:

- Ansible-статус задачи (`ok`, `failed`, `skipping`, `ignored`) показывает только
  состояние выполнения диагностической задачи;
- продуктовый статус проверки печатается явно как `DRY-RUN PASS`, `DRY-RUN FAIL`
  или `DRY-RUN SKIP`;
- единственный итоговый источник правды - финальная сводка `DRY RUN RESULT` и
  список `failed_checks`.

Для корневых сетевых проверок используется намеренно видимый `failed ...ignoring`:

- `app VM` по TCP 22;
- `DB VM` по TCP 22;
- PostgreSQL на `DB_VM_HOST:DB_PORT`;
- полный `origin URL` каждого backend/frontend-репозитория.

Так оператор сразу видит, что проверка реально не прошла, но playbook не
останавливается на первой проблеме и доходит до общего отчета. Зависимые проверки
не дублируют корневую ошибку:

- SSH-аутентификация пропускается, если TCP 22 уже недоступен;
- remote-директории, runtime-команды и runtime-файлы app VM пропускаются, если SSH
  на app VM не прошел;
- `psql` на DB VM и подключение к PostgreSQL пропускаются, если SSH на DB VM не
  прошел.

## Решения по проверкам окружения

Сборочный стек исторически работает с Windows-путями и Git Bash. Поэтому dry run
проверяет Node.js и npm не в WSL, а в Windows-контексте:

```bash
cmd.exe /C node --version
cmd.exe /C npm --version
```

Локальные backend/frontend-репозитории тоже проверяются Windows Git, потому что в
`.env` хранятся Windows-пути вида `C:/...`.

Проверка `origin` должна обращаться не к голому домену и не через `git ls-remote`,
а к полной ссылке `origin`:

1. dry run читает URL через `git remote get-url origin`;
2. выполняет `curl --head --location` по полной ссылке;
3. HTTP `401` считается успешной сетевой доступностью: сервер найден и отвечает,
   а авторизация не является задачей dry run;
4. `git ls-remote` не используется, потому что HTTPS Git может открыть
   интерактивный prompt логина и зависнуть/упасть без TTY.

DB-операции выполняются через SSH на DB VM. Управляющей WSL-машине не нужен
`postgresql-client`; `psql` должен быть на DB VM. Роль `db_maintenance` запускает
remote `psql` через SSH, а SQL подает в stdin. Это соответствует продуктовой
топологии: если есть SSH на DB VM, технические SQL-команды выполняются там, где
есть доступ к PostgreSQL.

## Правила против утечек

В репозитории не должны храниться локальные значения рабочей машины:

- корневой `.env` игнорируется;
- `group_vars/vault.yml` и `.vault-pass` игнорируются;
- реальные `builder/settings/*/.env` игнорируются, потому что Ansible записывает
  туда домены из локального `.env`;
- в Git хранятся только `builder/settings/*/.env.template` с плейсхолдерами
  `__ANSIBLE_*`;
- `.venv-ansible/`, `__pycache__/` и локальные runtime-артефакты не коммитятся.
## Planned backend DB artifact flow

- Work is done on local branch `dev`.
- Additional backend artifact generators live in `builder/scripts/additional_artifacts/`.
- During backend build the DB artifact generators are copied into build-only `BACKEND_SOURCE_REPO_PATH/build_scripts/` and run from the backend source repo root. For current debugging this directory is kept after packaging; the next build recreates it from `builder/scripts/additional_artifacts/`. DB summary/run_all intermediate files are generated from source repo state; target repo is only used for the synced backend code archive.
- Backend build resolves the backend venv via `BACKEND_BUILD_VENV_RELATIVE_PATH` relative to `BACKEND_SOURCE_REPO_PATH`; default is `.venv/Scripts/activate.bat`. If the venv is missing, build creates it through Git Bash with `python -m venv` and does not install dev requirements. SQL generators then run through Git Bash with the source venv `python.exe -Xutf8`, not through `cmd.exe` or `activate.bat`. `create_sql_migrations.py` also calls Django management commands through `sys.executable -Xutf8` with tolerant UTF-8 decoding for captured output.
- Generated SQL files are selected only when their names contain the current short `HEAD` hash of the backend source repo.
- `create_sql_migrations.py` always writes a matching `summary_sql_*_<commit>.sql`; if no new Django migrations are detected, the file is a no-op summary entrypoint so the schema artifact still exists.
- Backend build creates three DB artifact archives: schema, insert, and update. The insert/update archives include their matching `run_all_*` entrypoint and only the `docs/database/scripts/` files referenced by that entrypoint's `\i` includes.
- `run_all_insert` and `run_all_update` are generated inside source `build_scripts`, then packaged at archive root. They include `\timing on`, disable `synchronous_commit` during execution, apply PostgreSQL parallel/work memory session settings, and restore `synchronous_commit` at the end.
- If INSERT scripts are not idempotent, `create_run_all_sql.py` exits non-zero and the build pipeline must fail before release archiving continues.
- Deploy applies schema SQL on the DB VM, then data SQL (`run_all_insert`, then `run_all_update`), then app VM runs `manage.py migrate --fake` and `sync_action_role`.
- Utility helpers for git output, strict single-file matching, and tar additions live in `builder/src/utils.py`; backend build keeps only backend-specific orchestration.
- Backend DB artifact logging prints build_scripts create/copy/run steps, exact generator commands, summary SQL output path, lookup directories/patterns for generated SQL, and the debug skip of build_scripts cleanup.
- The generator copy step recreates `<BACKEND_SOURCE_REPO_PATH>/build_scripts` for each build and fails if that path exists but is not a directory.
