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

## Контракт Windows-only deploy

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
верхней директорией `BACKEND_APP_ROOT_DIR` распаковывается содержимым в
`BACKEND_RELEASE_PATH`; дефолтное значение `BACKEND_APP_ROOT_DIR` -
`example_backend_app`.

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

## Почтовое уведомление Outlook

Письмо об успешном deploy настраивается в `windows_pipeline.local.json`, а не в
`.env`. Для включения нужно выставить `outlook_email_enabled: true`, задать
непустые `outlook_email_recipients`, `outlook_email_subject` и
`outlook_email_body`, а также иметь установленный и настроенный desktop Outlook
для текущего Windows-пользователя. Необязательный `outlook_email_cc` добавляет
получателей в копию. Если `outlook_email_required: false`, ошибка отправки
письма после успешного deploy логируется как WARN; если `true`, ошибка отправки
роняет pipeline. `dry-run` проверяет получателей, шаблоны и создание Outlook
COM. Доступные переменные шаблонов: `{build_version}`, `{stand_url}`,
`{dev_domain}`, `{release_dir}`, `{artifacts_text}` и
`{release_changelog_text}`. После успешного deploy письмо прикладывает
`release_manifest.json` из директории релиза, если файл существует; отсутствие
манифеста логируется как WARN и само по себе не блокирует отправку.

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

Backend shell-архиватор получает `BACKEND_REPO_ROOT_BASH` из
`BACKEND_SOURCE_REPO_PATH`: релизный backend-архив собирается из source repo, а
target repo участвует только как альтернативная sync-репа. Верхняя директория
backend application archive задается `BACKEND_APP_ROOT_DIR` с дефолтом
`example_backend_app`; Django settings для schema generator можно переопределить
через `BACKEND_DJANGO_SETTINGS_MODULE`, иначе используется
`<BACKEND_APP_ROOT_DIR>.settings.base`. Для frontend отдельного bash-пути сейчас
нет, потому что frontend-архиватор запускается из рабочей директории
frontend-репозитория и использует только `RELEASE_ROOT_BASH`.

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

## Dry run

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
## Поток backend DB-артефактов

- Работа ведется в локальной ветке `dev`.
- Дополнительные генераторы backend-артефактов лежат в `builder/scripts/additional_artifacts/`.
- Backend target repo остается только альтернативной sync-репой. Sync заменяет в target только top-level элементы, которые есть в source repo, и не трогает top-level элементы target, отсутствующие в source.
- Backend application archive собирается из `BACKEND_SOURCE_REPO_PATH/BACKEND_APP_ROOT_DIR`; default `BACKEND_APP_ROOT_DIR` равен `example_backend_app`.
- Во время backend build DB-генераторы копируются в служебную директорию `BACKEND_SOURCE_REPO_PATH/build_scripts/` и запускаются из корня backend source repo. Сейчас для отладки эта директория остается после упаковки; следующий build пересоздает ее из `builder/scripts/additional_artifacts/`. Промежуточные DB-файлы и backend application archive генерируются из состояния source repo; target repo используется только как альтернативная sync-репа.
- Backend build находит venv по `BACKEND_BUILD_VENV_RELATIVE_PATH` относительно `BACKEND_SOURCE_REPO_PATH`; значение по умолчанию - `.venv/Scripts/activate.bat`. Если venv отсутствует, build создает его через Git Bash командой `python -m venv`. Перед каждым запуском генераторов build ставит production-зависимости backend в этот venv через `pip install --trusted-host ... -r <requirements>` из `BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH` (по умолчанию `requirements.txt`). Dev requirements не ставятся. SQL-генераторы запускаются через Git Bash с `python.exe -Xutf8` из source venv, без `cmd.exe` и без `activate.bat`.
- Сгенерированные SQL-файлы выбираются только если их имена содержат текущий короткий `HEAD` hash backend source repo.
- Генерация schema summary активна: `create_sql_migrations.py` копируется в `build_scripts`, получает baseline для `dev`, `test`, `prod` через `SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON` и пишет `summary_sql_<contour>_*.sql` плюс `schema_migrations_metadata.json`.
- Backend build сейчас создает schema-архивы `db_schema_dev_*`, `db_schema_test_*`, `db_schema_prod_*`, а также data SQL-архивы insert и update. В data-архивах лежит соответствующий `run_all_*` entrypoint и только те файлы из `docs/database/scripts/`, на которые entrypoint ссылается через `\i`.
- `run_all_insert` и `run_all_update` генерируются внутри source `build_scripts`, затем упаковываются в корень архива. Они включают `\timing on`, отключают `synchronous_commit` на время выполнения, применяют PostgreSQL session settings для parallel/work memory и в конце возвращают `synchronous_commit = ON`.
- Если INSERT-скрипты не идемпотентны, `create_run_all_sql.py` завершается с ненулевым кодом, и build pipeline должен упасть до продолжения упаковки релиза.
- Windows runner deploy выбирает schema-архив по `--contour`, загружает его на DB VM, распаковывает и выполняет `summary_sql_<contour>_*.sql` из корня распакованного архива до Django management-команд. Schema SQL запускается через `psql --set=ON_ERROR_STOP=1 --single-transaction`, поэтому при ошибке весь файл откатывается PostgreSQL. Data SQL-архивы (`run_all_insert`, `run_all_update`) остаются упакованными для отдельного DB migration flow и не выполняются Windows runner на этом шаге.
- Сгенерированный schema SQL не коммитится обратно в backend source repo и не хранится в `docs/database/summary`: источником для деплоя являются только релизные архивы и manifest.
- Ручное применение schema archive на TEST/PROD описано в `instructions/manual-schema-sql-deploy.md`; после успешного ручного применения оператор simple-deploy двигает baseline через `mark-applied`.
- Вспомогательные функции для git output, строгого поиска одного файла и добавления файлов в tar лежат в `builder/src/utils.py`; `build_backend.py` оставляет у себя только backend-specific orchestration.
- Логи backend DB artifacts показывают создание/копирование/запуск `build_scripts`, точные команды генераторов, директории/паттерны поиска сгенерированных SQL-файлов и временный пропуск очистки `build_scripts`.
- Шаг копирования генераторов пересоздает `<BACKEND_SOURCE_REPO_PATH>/build_scripts` на каждый build и падает, если такой путь уже существует, но не является директорией.

## Техдолг

- Отрефакторить генерацию schema summary SQL: отделить расчет Django migrations от упаковки артефактов, явно валидировать backend settings/requirements/venv до генерации и убрать зависимость от временной директории `build_scripts`.
- Вернуть управляемое включение/отключение schema summary через конфигурационный флаг вместо неявной логики в коде.
- Все новые записи в README, CONTEXT, комментариях и рабочих сообщениях по проекту вести на русском языке.
## Актуальный контекст SQL-миграций

`create_sql_migrations.py` снова является активной частью backend build, но теперь работает как offline best-effort генератор SQL по Git-диапазону Django migrations. Генератор не требует подключения к PostgreSQL: он загружает migrations из backend source repo, строит план через `MigrationLoader(None, replace_migrations=False)` и собирает SQL через PostgreSQL schema editor в режиме `collect_sql=True`.

Локальное состояние релизов и контуров хранится в `local_state/simple_deploy.sqlite3`. Файл создается автоматически, считается runtime-состоянием рабочей машины и не коммитится. В базе фиксируются baseline commit для `dev`, `test`, `prod`, попытки применения, успешные применения и ошибки. Build требует baseline для всех трех контуров, потому что за один релиз генерирует отдельные SQL-диапазоны для `dev`, `test`, `prod`.

Первичная инициализация baseline выполняется по фактическому backend commit, который уже успешно лежит на каждом контуре. Это commit `from`, а не commit нового релиза:

Команды Windows runner:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py set-baseline --contour dev --backend-commit <dev_backend_commit>
.venv/Scripts/python.exe tools/windows_pipeline.py set-baseline --contour test --backend-commit <test_backend_commit>
.venv/Scripts/python.exe tools/windows_pipeline.py set-baseline --contour prod --backend-commit <prod_backend_commit>
.venv/Scripts/python.exe tools/windows_pipeline.py set-baseline --contour test --build-version <previous_successful_release_version>
.venv/Scripts/python.exe tools/windows_pipeline.py deploy --contour dev --latest
.venv/Scripts/python.exe tools/windows_pipeline.py mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/python.exe tools/windows_pipeline.py mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

DEV обычно идет от предыдущего локально зафиксированного состояния к текущему release commit. После успешного `deploy --contour dev` baseline `dev` двигается автоматически. TEST и PROD собираются как from-to диапазоны от baseline соответствующего контура до commit релиза; после успешного применения на внешнем контуре оператор должен явно выполнить `mark-applied`, иначе следующий релиз снова будет строиться от старого baseline. При ошибке используется `mark-failed`, baseline при этом не меняется.

Пример диапазонов: если DEV сейчас на `C2`, TEST/PROD на `C1`, а новый backend source repo на `C3`, перед build нужно поставить `dev=C2`, `test=C1`, `prod=C1`. Build создаст `db_schema_dev` для `C2..C3` и `db_schema_test`/`db_schema_prod` для `C1..C3`. Нельзя заранее ставить baseline на `C3` до успешного применения, иначе следующий build посчитает `C3` уже примененным.

Manifest SQL-артефакта перечисляет Django migration-файлы, попавшие в диапазон `from..to`; это список входа в генерацию, а не гарантия идемпотентности или применения на БД.

Документация процесса вынесена в `docs/`:

- `release-sql-migrations-flow.puml/pdf` - полный поток от dry-run до DEV/TEST/PROD;
- `release-sql-migrations-build-dev.puml/pdf` - сборка и размещение на DEV;
- `release-sql-migrations-test-prod.puml/pdf` - продвижение на TEST и PROD.
