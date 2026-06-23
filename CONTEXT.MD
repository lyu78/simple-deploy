# Контекст проекта

Проект автоматизирует одностороннюю доставку изменений из внешнего контура во
внутренний контур, сборку релизных архивов и обновление локального DEV-стенда.
Рабочая машина является управляющей точкой: на ней лежат рабочие копии внешних и
внутренних репозиториев, запускается сборщик и с нее runtime подключается к VM.

## Текущий Windows-only режим

Актуальный рабочий путь для машины без WSL/Docker - console script
`.venv/Scripts/simple-deploy.exe`, который появляется после editable install
проекта. Runner использует Windows Python, Git, Node/npm, Git Bash и Windows
OpenSSH (`ssh`, `scp`). Ansible остается в репозитории как legacy-вариант для
Linux/WSL control node, но основная отладка в последних изменениях велась
вокруг Windows-only runner.

Команды:

```bash
.venv/Scripts/simple-deploy.exe dry-run
.venv/Scripts/simple-deploy.exe build
.venv/Scripts/simple-deploy.exe deploy --latest
.venv/Scripts/simple-deploy.exe deploy --build-version <version>
.venv/Scripts/simple-deploy.exe pipeline
```

Каждый запуск пишет вывод одновременно в консоль и отдельный файл
`logs/<timestamp>-<command>.log`; `logs/` игнорируется Git.

SSH-доступ к VM не интерактивный: runner работает в batch-режиме и рассчитан на
ключ или ssh-agent. В `tools-ci/.env` поддерживаются:

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

Секреты PostgreSQL лежат в `tools-ci/local.secrets.env`. Для `dry-run`, `deploy` и
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
python "$APP_MANAGE_PY_PATH" migrate --fake
python "$APP_MANAGE_PY_PATH" sync_action_role
```

Если `management_commands` в `tools-ci/windows_pipeline.local.json` пустой, runner строит
команды из `APP_MANAGE_PY_PATH`. Если локальный `tools-ci/windows_pipeline.local.json`
содержит явные `management_commands`, они имеют приоритет. Dry-run проверяет, что
`APP_MANAGE_PY_PATH` существует и читается относительно `APP_WORKDIR`.

## Service steps и права

Команды запуска/проверки сервисов задаются в `tools-ci/windows_pipeline.local.json` в
`service_steps`. Поддерживаемые фазы: `before_unpack`, `after_unpack`,
`after_migrate`, `after_frontend_unpack`; шаги без `phase` считаются `after_migrate`. Порядок выполнения
соответствует порядку в JSON. Если `manage.py` зависит от Redis/KeyDB при
импорте settings/Celery, в `after_unpack` выполняется идемпотентный
`start/status` KeyDB перед management-командами, а явный restart
`stop/start/status` KeyDB задается в `after_migrate`. Nginx в full deploy не
останавливается до раскладки финального frontend, чтобы отдавать
maintenance-заглушку. Штатный сценарий для nginx - `stop` затем `start` только
в `after_frontend_unpack` после раскладки финального frontend и перед
healthcheck; dry-run требует, чтобы `stop nginx` имел последующий `start nginx`
в той же фазе, а `restart`/`reload`/`try-restart` для nginx считает ошибкой
конфига. `systemctl status nginx` можно использовать как проверку.

Пример:

```json
{
  "service_steps": [
    {
      "name": "stop nginx after frontend",
      "phase": "after_frontend_unpack",
      "command": "sudo /bin/systemctl stop nginx",
      "permission_check_command": "sudo /bin/systemctl stop nginx"
    },
    {
      "name": "start nginx after frontend",
      "phase": "after_frontend_unpack",
      "command": "sudo /bin/systemctl start nginx",
      "permission_check_command": "sudo /bin/systemctl start nginx"
    },
    {
      "name": "status nginx",
      "phase": "after_frontend_unpack",
      "command": "systemctl status nginx",
      "permission_check_command": "systemctl status nginx"
    }
  ]
}
```

Service steps, меняющие состояние systemd unit (`start`, `stop`, `restart`,
`reload`), запускаются через `sudo`; `systemctl status ...` можно задавать без
`sudo`. Пользователь не должен быть
в полном sudo/wheel. Для него создается точечное правило
`/etc/sudoers.d/simple-deploy` через `visudo` с `NOPASSWD` только для нужных
`/bin/systemctl start/stop/restart ...` команд. Если `systemctl` лежит не в
`/bin`, путь нужно проверить через `command -v systemctl` и использовать
фактический путь.
`systemctl status ...` на inactive unit возвращает rc=3; dry-run считает такой
ответ успешной проверкой доступа, если stdout/stderr читается. В реальном deploy
status-шаг после start остается обычной проверкой здоровья unit и должен падать,
если service не активен.

Для текущего DEV service order sudoers должен покрывать только state-changing
команды: stop `gunicorn_local.service`, `celery_local.service`,
`celerybeat_local.service`, `keydb_local.service`, `file_proxy_local.service`,
`minio_local.service`; затем start app-сервисов в обратном порядке и stop/start
`nginx` после раскладки финального frontend. Удобный формат:

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

Проверки: `sudo visudo -cf /etc/sudoers.d/simple-deploy`,
`sudo -n -l /bin/systemctl stop celerybeat_local.service`,
`sudo -n -l /bin/systemctl stop keydb_local.service`,
`sudo -n -l /bin/systemctl start keydb_local.service`,
`sudo -n -l /bin/systemctl start celerybeat_local.service`,
`sudo -n -l /bin/systemctl stop nginx`,
`sudo -n -l /bin/systemctl start nginx`.
`systemctl status ...` в sudoers не нужен, если статус доступен без sudo.
Если `sudo -l -U deploy-simple` дополнительно показывает `(ALL) ALL`, это
отдельное общее sudo-правило, чаще всего через группу. Deploy на него не
опирается: для runner достаточно точечного `NOPASSWD` списка выше. С точки
зрения least privilege общее правило лучше убрать, но отсутствие пароля у
`deploy-simple` делает его не блокирующим для текущего deploy.

Dry-run для sudo service steps сначала смотрит общий список доступных команд через
`sudo -n -l`, затем проверяет каждый шаг через `sudo -n -l <команда без sudo>`.
Реальная сервисная команда на dry-run не выполняется, даже если
`permission_check_command` задан как `sudo /bin/systemctl start ...`.
Runtime validation считает `systemctl start/stop/restart/reload ...` без `sudo`
ошибкой config; `systemctl status ...` без `sudo` разрешен. Deploy выполняет
service step дословно и иначе получает `Interactive authentication required`.

## Финальный healthcheck портала

После deploy runner проверяет HTTP-доступность `https://DEV_DOMAIN/`, затем ищет
текущий `build_version`:

1. в HTML главной страницы;
2. если это React и версия не найдена в HTML - в JS assets из `<script src=...>`
   того же origin.

Проверку можно отключить в `tools-ci/windows_pipeline.local.json`:

```json
"portal_version_check_enabled": false
```

Количество JS assets ограничивается `portal_version_asset_limit`.

## Почтовое уведомление Outlook

Письмо об успешном deploy настраивается в `tools-ci/windows_pipeline.local.json`, а не в
`tools-ci/.env`. Для включения нужно выставить `outlook_email_enabled: true`, задать
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

## Документы пайплайна

Пайплайн разделен на продуктовый уровень и две технологические реализации:

- `PIPELINE.MD` - продуктовая схема процесса без привязки к runtime, пригодная
  как основа BPMN.
- `tools-ci/PIPELINE.MD` - основной Windows/Python E2E процесс через
  `.venv/Scripts/simple-deploy.exe`.
- `legacy/ansible-ci/PIPELINE.MD` - legacy Ansible/WSL E2E процесс через
  `legacy/ansible-ci/playbooks/pipeline.yml`.

## Структура

- `tools-ci/builder/` - существующая сборочная подсистема: `create_release.py`, Python-код,
  shell-архиваторы и настройки frontend-сборки.
- `tools-ci/simple_deploy/cli/windows_pipeline.py` - CLI adapter, на который
  указывает console script `simple-deploy`.
- `tools-ci/requirements.dev.txt` - Python-зависимости сборщика из `tools-ci/builder/`.
- `legacy/ansible-ci/requirements.ansible.txt` - Python-зависимости Ansible-слоя.
- `legacy/ansible-ci/playbooks/` - legacy Ansible pipeline, dry run и внутренние этапы.
- `legacy/ansible-ci/roles/` - Ansible-роли доставки артефактов, DB-работ, сервисных команд,
  миграций, healthcheck и отчета.
- `legacy/ansible-ci/group_vars/dev.yml` - схема DEV-контура и производные значения.
- `tools-ci/.env` - локальная конфигурация рабочей машины, не хранится в репозитории.
- `tools-ci/.env.example` - пример `.env` с нереальными, но похожими на боевые значениями.
- `tools-ci/local.secrets.env` - локальные secrets PostgreSQL, не хранятся в репозитории.
- `tools-ci/local.secrets.env.example` - пример файла secrets без реальных значений.
- `legacy/ansible-ci/group_vars/vault.yml` - секреты Ansible Vault, не хранится в репозитории.
- `tools-ci/builder/settings/*/.env.template` - шаблоны frontend `.env`; реальные
  `tools-ci/builder/settings/*/.env` генерируются локально перед сборкой и игнорируются Git.

## Конфигурация

В `tools-ci/.env` обязательно задаются адреса VM, SSH-пользователи, пути к рабочим копиям
репозиториев, домены и пути деплоя на app VM.

`APP_VM_USER` и `DB_VM_USER` обязательны отдельно. Если `DB_VM_USER` не указан,
Ansible должен падать на проверке конфигурации, а не молча брать пользователя app VM.

`PROJECT_ROOT_WSL`, `RELEASE_ROOT_WSL` и `RELEASE_ROOT_BASH` необязательны:

- корень проекта по умолчанию считается от `inventory_dir`;
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

`tools-ci/builder/create_release.py`:

- синхронизирует внешние и внутренние рабочие копии;
- собирает backend/frontend-архивы;
- пушит ветки во внутренние репозитории;
- не знает про VM и раскатку.

Console script `simple-deploy` через `simple_deploy.cli.windows_pipeline`:

- является основной операторской точкой входа для Windows-only режима;
- читает `tools-ci/.env`, `tools-ci/local.secrets.env` и `tools-ci/windows_pipeline.local.json`;
- запускает `tools-ci/builder/create_release.py` для сборки релиза;
- выбирает собранный релиз;
- доставляет schema SQL на DB VM и backend/frontend архивы на app VM;
- выполняет DB-работы, `migrate --fake`, `sync_action_role`, сервисные команды,
  healthcheck и фиксацию baseline.
- поддерживает `deploy --app-only` / `pipeline --app-only` для recovery после
  уже успешного DB schema SQL: режим не подключается к DB VM, не требует DB
  password и повторяет только app VM часть.

Legacy Ansible:

- читает `tools-ci/.env` и vault-секреты;
- вычисляет дефолтные пути проекта и релизов;
- создает `tools-ci/builder/settings/*/.env` из tracked-шаблонов `.env.template` и
  подставляет туда домены;
- запускает `tools-ci/builder/create_release.py`;
- выбирает собранный релиз;
- доставляет архивы на app VM;
- выполняет DB-работы, миграции, сервисные команды и healthcheck.

## Legacy Ansible dry run

Безопасная диагностика:

```bash
cd legacy/ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Dry run ничего не распаковывает, не запускает SQL-работы, миграции и рестарты.
Самые ранние проверки:

- `tools-ci/.env` заполнен обязательными параметрами;
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
cd legacy/ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Проверка архивов включается явно через `-e build_version=<версия>` или
`-e use_latest_release=true`.

## Продуктовая модель Ansible dry run

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
`tools-ci/.env` хранятся Windows-пути вида `C:/...`.

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

- локальный `tools-ci/.env` игнорируется;
- `legacy/ansible-ci/group_vars/vault.yml` и `.vault-pass` игнорируются;
- реальные `tools-ci/builder/settings/*/.env` игнорируются, потому что Ansible записывает
  туда домены из локального `tools-ci/.env`;
- в Git хранятся только `tools-ci/builder/settings/*/.env.template` с плейсхолдерами
  `__ANSIBLE_*`;
- `.venv-ansible/`, `__pycache__/` и локальные runtime-артефакты не коммитятся.
## Поток backend DB-артефактов

- Работа ведется в локальной ветке `dev`.
- Дополнительные генераторы backend-артефактов лежат в `tools-ci/builder/scripts/additional_artifacts/`.
- Backend target repo остается только альтернативной sync-репой. Sync заменяет в target только top-level элементы, которые есть в source repo, и не трогает top-level элементы target, отсутствующие в source.
- Backend application archive собирается из `BACKEND_SOURCE_REPO_PATH/BACKEND_APP_ROOT_DIR`; default `BACKEND_APP_ROOT_DIR` равен `example_backend_app`.
- Во время backend build DB-генераторы копируются в служебную директорию `BACKEND_SOURCE_REPO_PATH/build_scripts/` и запускаются из корня backend source repo. Директория пересоздается на каждый build и удаляется после упаковки SQL-артефактов, чтобы не оставлять временные файлы в source repo. Промежуточные DB-файлы и backend application archive генерируются из состояния source repo; target repo используется только как альтернативная sync-репа.
- Backend build находит venv по `BACKEND_BUILD_VENV_RELATIVE_PATH` относительно `BACKEND_SOURCE_REPO_PATH`; значение по умолчанию - `.venv/Scripts/activate.bat`. Если venv отсутствует, build создает его через Git Bash командой `python -m venv`. Перед каждым запуском генераторов build ставит production-зависимости backend в этот venv через `pip install --disable-pip-version-check --trusted-host ... -r <requirements>` из `BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH` (по умолчанию `requirements.txt`). Dev requirements не ставятся. SQL-генераторы запускаются напрямую через `python.exe -Xutf8` из source venv, без `cmd.exe`, Git Bash и `activate.bat`.
- Сгенерированные SQL-файлы выбираются только если их имена содержат текущий короткий `HEAD` hash backend source repo.
- Генерация schema summary активна: `create_sql_migrations.py` копируется в `build_scripts`, получает baseline для `dev`, `test`, `prod` через `SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON` и пишет `summary_sql_<contour>_*.sql` плюс `schema_migrations_metadata.json`.
- Backend build всегда создает schema-архивы `db_schema_dev_*`, `db_schema_test_*`, `db_schema_prod_*` и по умолчанию всегда создает data SQL-архивы insert/update_sequential/update_parallel/set_default_sequential/set_default_parallel. Явный schema-only/emergency opt-out: `--skip-data-sql-artifacts`.
- `data_sql_enabled` в runtime config отвечает только за применение data SQL на deploy, а не за генерацию артефактов. Команда `pipeline` больше не включает скрыто старый `--include-data-sql`; старый флаг оставлен как совместимый no-op, потому что data SQL build теперь дефолтный.
- `run_all_insert`, `run_all_update_sequential`, `run_all_update_parallel`, `run_all_set_default_sequential` и `run_all_set_default_parallel` генерируются внутри source `build_scripts`, затем упаковываются в корень отдельных архивов. SQL entry points включают `\timing on`, отключают `synchronous_commit` на время выполнения и в конце возвращают `synchronous_commit = ON`; `run_all_insert` использует PostgreSQL session settings для parallel/work memory.
- Обычные data insert-скрипты остаются на последовательном `run_all_insert`: текущий baseline без `insert_new_objects/**` около `26.724 сек`, поэтому отдельный insert-parallel runner не нужен. `run_all_insert` должен оставаться строгим entrypoint с `ON_ERROR_STOP=1` и проверкой идемпотентности insert-скриптов; `insert_new_objects/**` считается отдельной backlog-темой для ручного одноразового применения и не входит в текущую оптимизацию.
- `run_all_update_sequential_<commit>.sql` - аварийный fallback для случая, когда доступно только одно ядро/одна DB-сессия и update нужно выполнить строго последовательно. Он выбирает только размеченные `kind=update`, исключает `kind=insert`, `kind=set_default` и `insert_new_objects/**`, сортирует по metadata `order`, затем `group`, затем path, использует `ON_ERROR_STOP=1` и консервативные session settings без PostgreSQL parallel-параметров. Архив manifest key: `db_update_sequential_archive`, имя архива `db_update_sequential_r_<release>-c_<commit>.tar.gz`.
- `run_all_update_parallel_<commit>.sh` - целевой wave runner для update в нескольких DB-сессиях. Он выбирает тот же metadata-набор `kind=update`, проходит `order` как барьерные волны, запускает `parallel=true` в background с `SIMPLE_DEPLOY_UPDATE_MAX_WORKERS` (default `8`), выполняет `parallel=false` эксклюзивно, использует fail-fast, печатает в терминал `[START]`, периодический `[RUNNING]`, `[OK]`/`[FAIL]`, timing по скриптам/wave/total и top slow scripts. Полный psql output каждого скрипта пишется в `logs/update_parallel/<timestamp>/scripts/*.log`; интервал live-status задается `SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS` (default `30`), полный вывод psql в терминал включается `SIMPLE_DEPLOY_UPDATE_VERBOSE=1`. Архив manifest key: `db_update_parallel_archive`, имя архива `db_update_parallel_r_<release>-c_<commit>.tar.gz`; штатный Windows full deploy запускает его после `run_all_insert`.
- `run_all_set_default_sequential_<commit>.sql` и `run_all_set_default_parallel_<commit>.sh` - отдельные entrypoints только для `kind=set_default`. Архивы имеют manifest keys `db_set_default_sequential_archive` и `db_set_default_parallel_archive`, имена `db_set_default_sequential_r_<release>-c_<commit>.tar.gz` и `db_set_default_parallel_r_<release>-c_<commit>.tar.gz`; штатный deploy запускает set_default runner только при `--include-set-default-sql`, отдельным step после update.
- В будущей разметке data SQL поле `order` трактуется как барьерная волна выполнения, а не как количество DB-сессий и не как номер worker-а. Runner может переходить к следующей волне только после завершения всех скриптов предыдущей волны; лимит одновременных DB-сессий должен быть отдельным параметром вроде `max_workers`. Если update-скрипты зависят только от insert-фазы и не зависят друг от друга, планирование соответствует `P || Cmax`: распределению независимых работ по одинаковым параллельным машинам с минимизацией makespan. Практичная жадная эвристика - LPT (`Longest Processing Time first`, алгоритм наибольшей длительности сначала): запускать более долгие независимые скрипты раньше внутри общего пула, отдавая следующий скрипт на наименее загруженный worker. При runner-е только с барьерными волнами долгий независимый скрипт не нужно ставить в раннюю волну, если он блокирует последующие независимые волны; в ранних волнах должны быть реальные зависимости/prerequisites, а независимую тяжелую работу лучше группировать ближе к финальным update-волнам с учетом `max_workers`. `parallel=true` проверяется на уровне ячейки данных: два параллельных скрипта не должны писать в одну строку и один столбец. Одинаковая таблица или одинаковый `group` не являются автоматическим запретом, если доменные фильтры вроде `partition_item_id` и полный ключ строки разводят записи; при lock waits/deadlock нужно пересмотреть группы или order-волны.
- Так как data SQL генерируется по умолчанию, если INSERT-скрипты не идемпотентны, `create_run_all_sql.py` завершается с ненулевым кодом, и build pipeline должен упасть до продолжения упаковки релиза. Dry-run проверяет эту идемпотентность по умолчанию; пропуск разрешен только явным `--skip-data-sql-artifacts`.
- Windows runner full deploy выбирает schema-архив по `--contour`, а также `db_insert` и `db_update_parallel` при `data_sql_enabled=true`; `db_set_default_parallel` резолвится только при `deploy/pipeline --include-set-default-sql`. В начале full deploy runner выполняет DB data update preflight cleanup, чтобы повторный запуск после `KeyboardInterrupt`/падения не накатывал новый релиз поверх еще работающего update/default step: на DB VM останавливает хвосты `run_all_update_parallel_*.sh`, `run_all_set_default_parallel_*.sh` и их `psql` процессов, затем завершает PostgreSQL backend-и с `application_name=simple-deploy-data-update`; оба parallel runner-а запускаются с этим `PGAPPNAME`. Cleanup пишет в терминал и общий `logs/<timestamp>-deploy.log`: при отсутствии хвостов `No leftover DB data update OS processes`, при наличии - `Found leftover DB data update OS processes` со списком pid/command, затем `Sending TERM...`, при необходимости `Sending KILL...`, `Stopped leftover DB data update OS processes`; PostgreSQL cleanup выводит `terminated_backend_count=N`. До DB-части runner останавливает app-сервисы, но не останавливает nginx, и распаковывает универсальную заглушку `tools-ci/maintenance_stub/maintenance_stub.tar.gz` в `FRONTEND_RELEASE_PATH`; сразу после распаковки full deploy делает HTTP-запрос на `https://DEV_DOMAIN/` с cache-busting query и ищет `maintenance_stub_verify_marker` (default `Плановые технические работы`), чтобы DB scripts не стартовали, если nginx все еще отдает основной frontend. Живой nginx отдает эту статику на время DB/backend работ. Настоящий frontend раскладывается только после DB scripts, backend unpack, management-команд и `after_migrate` service steps; после этого выполняется фаза `after_frontend_unpack`, и только в ней dry-run разрешает nginx `stop`/`start` перед healthcheck. Если используется `stop nginx`, dry-run требует последующий `start nginx` в той же фазе; `restart`/`reload`/`try-restart` для nginx считаются ошибкой конфига. Default stub archive уже лежит в repo, не привязан к release version и содержит верхний каталог `build/`, чтобы текущая распаковка с `--strip-components=1` положила в `FRONTEND_RELEASE_PATH` `index.html` и `assets/`. Schema SQL запускается через `psql --set=ON_ERROR_STOP=1 --single-transaction`; insert запускается через `psql -f run_all_insert_*.sql` тихо: полный output пишется на DB VM в `logs/insert/`, а в терминал выводится только итоговая длительность. Update запускается streaming SSH-командой `bash run_all_update_parallel_*.sh`; set_default запускается отдельной streaming SSH-командой `bash run_all_set_default_parallel_*.sh` только при `--include-set-default-sql`. `[START]`/`[RUNNING]`/wave/total логи видны в терминале во время выполнения.
- Windows runner запускает DB maintenance SQL (`db_maintenance_sql`, например `VACUUM ANALYZE;`) после schema/insert/update под той же заглушкой. Таймаут этого шага настраивается через `db_maintenance_sql_timeout_seconds` в runtime JSON, по умолчанию `900` секунд; data SQL timeout настраивается через `db_data_sql_timeout_seconds`, по умолчанию `21600` секунд. `dry-run` предупреждает о runtime-ключах, отсутствующих в локальном JSON и взятых из defaults, и валидирует итоговый runtime config, включая эти таймауты, типы boolean/list/string/int, допустимые фазы, `sql_scripts`, `service_steps`, healthcheck, maintenance stub и Outlook-поля.
- Информационные SQL-отчеты `tools-ci/sql/reports/public_table_size_report.sql` и `tools-ci/sql/reports/public_table_maintenance_diagnostics.sql` подключаются через `sql_scripts` на фазе `after_migrate` и выполняются в порядке JSON после schema/insert/update: сначала размер таблиц `public`, затем read-only диагностика `ANALYZE`/`VACUUM ANALYZE`/ручной проверки bloat и индексов. Эти файлы принадлежат runner package `tools-ci` и не являются source data SQL backend repo. Обычный Windows full deploy выполняет эти отчеты под maintenance-заглушкой до раскладки backend и финального frontend.
- `public_table_maintenance_diagnostics.sql` оптимизирован по объему логов: таблицы выводят summary, все non-OK строки и top 30 крупнейших OK-таблиц; индексы выводят summary, все non-OK строки и top 50 крупнейших OK-индексов; optional `pgstattuple_approx` по-прежнему проверяет top 20 крупнейших таблиц только при наличии функции. Это сохраняет сигналы для `ANALYZE`/`VACUUM_ANALYZE`/bloat/index review, но не печатает сотни OK-строк в каждом deploy.
- После `69c4820` dry-run на DEV подтвержден: bare `systemctl status ...` без sudo не требует sudoers; inactive unit с rc=3 считается успешной permission-проверкой, если статус читается. Health/status failures в реальном deploy остаются runtime-проверками после start.
- Сгенерированный schema SQL не коммитится обратно в backend source repo и не хранится в `docs/database/summary`: источником для деплоя являются только релизные архивы и manifest.
- Ручное применение schema и data SQL artifacts на TEST/PROD описано в `docs/runbooks/manual-sql-release-run.md`; после успешного ручного применения оператор simple-deploy двигает baseline через `mark-applied`.
- Вспомогательные функции для git output, строгого поиска одного файла и добавления файлов в tar лежат в `tools-ci/builder/src/utils.py`; `build_backend.py` оставляет у себя только backend-specific orchestration.
- Логи backend DB artifacts показывают создание/копирование/запуск и удаление `build_scripts`, точные команды генераторов и директории/паттерны поиска сгенерированных SQL-файлов.
- Шаг копирования генераторов пересоздает `<BACKEND_SOURCE_REPO_PATH>/build_scripts` на каждый build и падает, если такой путь уже существует, но не является директорией.

## Техдолг

- Отрефакторить генерацию schema summary SQL: отделить расчет Django migrations от упаковки артефактов, явно валидировать backend settings/requirements/venv до генерации и убрать зависимость от временной директории `build_scripts`.
- Вернуть управляемое включение/отключение schema summary через конфигурационный флаг вместо неявной логики в коде.
- Общие правила разработки, документации, безопасности истории Git и взаимодействия с AI-агентом зафиксированы в `DEVELOPMENT_RULES.MD`.

## Актуальный контекст SQL-миграций

`create_sql_migrations.py` снова является активной частью backend build, но теперь работает как offline best-effort генератор SQL по Git-диапазону Django migrations. Генератор не требует подключения к PostgreSQL: он загружает migrations из backend source repo, строит план через `MigrationLoader(None, replace_migrations=False)` и собирает SQL через PostgreSQL schema editor в режиме `collect_sql=True`.

Локальное состояние релизов и контуров хранится в `local_state/simple_deploy.sqlite3`. Файл создается автоматически, считается runtime-состоянием рабочей машины и не коммитится. В базе фиксируются baseline commit для `dev`, `test`, `prod`, попытки build, попытки применения, успешные применения и ошибки. Таблица `releases` остается журналом только успешно собранных релизов с manifest; упавшие build фиксируются отдельно в `build_attempts`. Build требует baseline для всех трех контуров, потому что за один релиз генерирует отдельные SQL-диапазоны для `dev`, `test`, `prod`.

Первичная инициализация baseline выполняется по фактическому backend commit, который уже успешно лежит на каждом контуре. Это commit `from`, а не commit нового релиза:

Команды Windows runner:

```bash
.venv/Scripts/simple-deploy.exe set-baseline --contour dev --backend-commit <dev_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour test --backend-commit <test_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour prod --backend-commit <prod_backend_commit>
.venv/Scripts/simple-deploy.exe set-baseline --contour test --build-version <previous_successful_release_version>
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest
.venv/Scripts/simple-deploy.exe deploy --contour dev --latest --app-only
.venv/Scripts/simple-deploy.exe mark-applied --contour test --build-version <successful_release_version>
.venv/Scripts/simple-deploy.exe mark-failed --contour test --build-version <failed_release_version> --error "описание ошибки"
```

DEV обычно идет от предыдущего локально зафиксированного состояния к текущему release commit. После успешного `deploy --contour dev` baseline `dev` двигается автоматически. Если `deploy` или `pipeline` падает после выбора релиза, runner автоматически пишет failed attempt в `deployment_attempts` без сдвига baseline. TEST и PROD собираются как from-to диапазоны от baseline соответствующего контура до commit релиза; после успешного применения на внешнем контуре оператор должен явно выполнить `mark-applied`, иначе следующий релиз снова будет строиться от старого baseline. При ошибке внешнего применения используется `mark-failed`, baseline при этом не меняется.
Если падение произошло после успешного `DB schema summary SQL`, полный повтор
`deploy --latest` может заново выполнить тот же DB SQL. Для восстановления APP
части используйте `--app-only`: он пропускает maintenance-заглушку, DB maintenance/schema/data artifacts/psql
и после успеха двигает baseline обычным `mark-applied`.

Пример диапазонов: если DEV сейчас на `C2`, TEST/PROD на `C1`, а новый backend source repo на `C3`, перед build нужно поставить `dev=C2`, `test=C1`, `prod=C1`. Build создаст `db_schema_dev` для `C2..C3` и `db_schema_test`/`db_schema_prod` для `C1..C3`. Нельзя заранее ставить baseline на `C3` до успешного применения, иначе следующий build посчитает `C3` уже примененным.

Manifest SQL-артефакта перечисляет Django migration-файлы, попавшие в диапазон `from..to`; это список входа в генерацию, а не гарантия идемпотентности или применения на БД.

Документация процесса вынесена в `docs/`:

- `docs/README.MD` - навигация по runbooks, SQL contracts, tasks и diagrams;
- `diagrams/sql-release/release-sql-migrations-flow.puml/pdf` - полный поток от dry-run до DEV/TEST/PROD;
- `diagrams/sql-release/release-sql-migrations-build-dev.puml/pdf` - сборка и размещение на DEV;
- `diagrams/sql-release/release-sql-migrations-test-prod.puml/pdf` - продвижение на TEST и PROD.

## Внутренний контекст ревью data SQL markup

Инструкция для сотрудника по исправлению разметки лежит в `docs/tasks/data-sql-markup-remediation.md`.
Она не должна содержать тестовые команды и критерии приемки: это рабочее задание, а не checklist для исполнителя.

Ожидания для внутренней проверки результата:

- `create_index/**.sql` и legacy `fix_migrations/**.sql` не имеют `simple-deploy`-разметки и не попадают в `script_docs.md`;
- ранее единственный важный неразмеченный non-fix data script `app_ip_subcompany_prw/update/update_app_ip_subcompany_stagecost.sql` теперь включен в разметку;
- после удаления ошибочной разметки с `create_index/gasprojectdata` и добавления этого non-fix data script текущее состояние - около `88` размеченных SQL-файлов;
- `group` должен соответствовать домену и целевой таблице: в частности, LTI stagecomment не должен быть `cc_app_ip_subcompany_stagecomment`, а PNCA stagecomment не должен быть `pnca_app_ip_subcompany_stagecost`;
- `critical=false` допустим только при явном обосновании, для обычных `insert/update/set_default/delete` базовый выбор - `critical=true`;
- `parallel=true` допустим только для реально независимых скриптов: параллельно нельзя писать в одну и ту же ячейку данных; одинаковый `group` допустим, если фильтры разводят строки/колонки;
- baseline по текущим комментариям времени выполнения: `insert` без `insert_new_objects/**` - `26.724 сек`; `update` - `57` файлов, все с распознанным временем, последовательно `4 ч 34 мин 20 сек`; `set_default` - минимум `1 мин 12 сек`, 3 файла имеют `X msec`;
- текущая самая долгая update-задача - `app_ip_subcompany_prw/update/update_app_ip_subcompany_stagecostprw_first_stage.sql`, около `40 мин`; ранее проблемный `app_ip_subcompany_cc/update/update_stagecommissioningcc_for_cc_objects_commissioning.sql` по текущему комментарию около `1 мин 14 сек`.

## Рефакторинг release/deploy toolkit

План рефакторинга зафиксирован в `REFACTORING_PLAN.MD`. Репозиторий развивается как release/deploy toolkit вокруг продуктового release artifact, контуров `dev`/`test`/`prod`, CLI и web/API поверх общей SQLite-базы.

Текущий безопасный срез:

- публичная точка запуска переведена на console script `.venv/Scripts/simple-deploy.exe`;
- старый executable wrapper в `tools-ci/tools/` удален, операторы больше не
  запускают Python-файл напрямую;
- фактическая реализация Windows runner находится в
  `tools-ci/simple_deploy/cli/windows_pipeline.py`;
- package shim `simple_deploy.windows_pipeline` удален: поддерживаемая точка
  входа только console script `simple-deploy` и CLI adapter
  `simple_deploy.cli.windows_pipeline`;
- пакет `tools-ci/simple_deploy/` содержит рабочие области `application`, `cli`, `config`,
  `core`, `registry`, `release`, `contours`, `processes`, `jobs`, `web`;
- SQLite state implementation принадлежит `simple_deploy.registry.state`; старый
  `simple_deploy.release.state` является compatibility re-export-ом;
- registry write/read границы вынесены в `simple_deploy.registry.commands` и
  `simple_deploy.registry.queries`;
- SQLite schema расширена таблицами `local_jobs` и `external_requests`; jobs
  создаются из web/API, а выполняются отдельным `simple-deploy worker`;
- `simple_deploy.core.paths`, `core.commands`, `core.env`, `core.build_env`,
  `core.release_paths`, `core.ssh`, `core.db`, `core.email` и runtime loader теперь вынесены из `windows_pipeline.py`;
- `processes.build`, `processes.mark`, `processes.dry_run`, `processes.data_sql` и
  `processes.deploy` не импортируют CLI compatibility modules;
- dry-run проверки живут в `simple_deploy.processes.dry_run_checks`;
- helper-ы app deploy, HTTP healthcheck и Outlook-уведомлений живут в
  `processes.app_deploy`, `processes.healthcheck` и `processes.notifications`;
- web/API v1 доступен как `python -m uvicorn simple_deploy.web.app:app --app-dir tools-ci --host 127.0.0.1 --port 8000`; `POST /api/jobs` создает queued job, `GET /api/jobs/{id}` читает одну job, `PATCH /api/jobs/{id}` меняет lifecycle status (`cancelled` для отмены queued job, `queued` для повторной постановки failed/cancelled job в очередь с тем же `id`), а `/ws/jobs/{id}` стримит job log file;
- dashboard jobs table показывает `Log`, `Cancel` и `Requeue` actions поверх
  REST `PATCH /api/jobs/{id}`; `GET /jobs/{id}` открывает HTML live log page,
  которая подключается к `/ws/jobs/{id}`;
- Ansible перенесен из корня в `legacy/ansible-ci`, дефолтные пути legacy Ansible поправлены на новую глубину каталога;
- операторские build/deploy команды и аргументы не менялись; добавлена
  сервисная команда `simple-deploy worker`.

Последние срезы рефакторинга закрыли SQL artifact contract, React operator UI
и web + worker operator UX:

- data SQL `update` и `set_default` разделены на отдельные artifacts и deploy
  steps; `--include-set-default-sql` запускает отдельный set_default step после
  update и больше не прокидывает `SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT` в update
  runner;
- React UI читает `/api/state`, создает local jobs через `POST /api/jobs`,
  управляет lifecycle через `PATCH /api/jobs/{id}` и открывает React job detail
  с live log stream;
- worker heartbeat хранится в SQLite, `GET /api/worker` показывает
  `offline`/`stale`/`idle`/`running`/`error`, а UI обновляет state/worker status
  без ручной перезагрузки;
- dashboard и job detail показывают пульсирующие индикаторы polling/stream:
  зеленый для здорового обновления, желтый для активного запроса, красный для
  ошибки;
- `web/API`, React UI, local jobs и worker остаются оболочкой поверх той же
  SQLite-базы и application/process use cases; CLI остается основным и
  аварийным путем.

Новые продуктовые идеи больше не входят в критерии завершения рефакторинга и
вынесены в `PRODUCT_BACKLOG.MD`: TEST/PROD external requests в API/UI, release
contents/change set, bundle validation pipeline и будущие operator UX срезы.

Refactoring track старой release/deploy функциональности закрыт: операционный
запуск пары web + worker описан в `tools-ci/README.MD`, старый Windows Task
Scheduler runbook для запуска `pipeline` удален из поддерживаемого пути, а
будущие scheduled jobs ведутся в `PRODUCT_BACKLOG.MD`.

Последняя проверка закрытия: `git diff --check`, React `npm run build`, полный
`pytest` (`183 passed`) и локальный operator smoke на изолированной SQLite-базе
для web/API, worker heartbeat, создания job и live log. Реальный DEV
`dry-run`/`deploy` остается операторской runtime-проверкой, потому что требует
окруженческих доступов к VM/DB.

Последняя зафиксированная точка ветки `refactor/create-deploy-toolkit`:

- `eb6df57 Add React web UI`.

Проверенный baseline после последних срезов: полный `pytest` - `183 passed`;
React `npm run build` зеленый; `git diff --check` - без whitespace errors,
только стандартные CRLF warnings.
