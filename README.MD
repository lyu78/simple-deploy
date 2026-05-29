# simple-deploy

## Backend DB-артефакты

Во время backend build SQL-генераторы копируются в служебную директорию
`BACKEND_SOURCE_REPO_PATH/build_scripts/`, запускаются из корня source repo и
сейчас временно остаются после упаковки для отладки. Следующий build пересоздает
эту директорию из `builder/scripts/additional_artifacts/`, поэтому сборка не
зависит от файлов из штатной директории `scripts/` backend-проекта.

Python-окружение для генераторов ищется внутри `BACKEND_SOURCE_REPO_PATH` по
`BACKEND_BUILD_VENV_RELATIVE_PATH`; если его нет, build создает venv через Git
Bash командой `python -m venv`. Перед каждым запуском генераторов build
устанавливает production-зависимости backend в этот venv через
`pip install --trusted-host` из `BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH`
(по умолчанию `requirements.txt`). Dev requirements не ставятся. SQL-генераторы
запускаются через Git Bash с `python.exe -Xutf8` из source venv; `cmd.exe` и
`activate.bat` на этом шаге не используются.

Генератор schema summary `create_sql_migrations.py` временно отключен. Сейчас из
состояния source repo генерируются только run_all-артефакты; target repo нужен
только для архива синхронизированного backend-кода.

Build логирует создание, копирование и запуск `build_scripts`, точные команды
генераторов, директории/паттерны поиска сгенерированных SQL-файлов и временный
пропуск очистки `build_scripts`.

Сейчас build создает два самодостаточных DB-архива:

- `db_insert_r_<release>-c_<commit>.tar.gz` содержит `run_all_insert_<commit>.sql` и только SQL-файлы, на которые он ссылается через `\i`.
- `db_update_r_<release>-c_<commit>.tar.gz` содержит `run_all_update_<commit>.sql` и только SQL-файлы, на которые он ссылается через `\i`.

Применение schema summary SQL в Windows runner deploy временно отключено. Сборка
не создает `db_schema_r_<release>-c_<commit>.tar.gz`, а deploy не загружает, не
распаковывает и не выполняет `docs/database/summary/summary_sql_*.sql` на DB VM.

Post-deploy MR в source repo для `docs/database/summary` тоже временно отключен,
пока отключена генерация schema summary.

Сгенерированные `run_all_insert` и `run_all_update` включают `\timing on`,
временно выставляют `synchronous_commit = OFF`, применяют session settings для
parallel/work memory PostgreSQL и в конце возвращают `synchronous_commit = ON`.

`simple-deploy` автоматизирует перенос изменений из внешнего контура разработки
во внутренний контур, сборку релизных архивов и обновление локального DEV-стенда.

Первый рекомендуемый запуск - безопасный dry run. Он ничего не собирает и
не раскатывает, а показывает, какие части окружения уже готовы и что нужно
исправить.

## Windows-only без WSL/Docker

Если на рабочей машине нет WSL и Docker, используйте Python-runner. Ему нужны
только Python-библиотеки, Node.js/npm, Git for Windows/Git Bash и Windows
OpenSSH (`ssh`, `scp`).

Откройте Git Bash и выполните:

```bash
git clone https://github.com/lyu78/simple-deploy simple-deploy
cd simple-deploy

python -m venv .venv
.venv/Scripts/python.exe -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --upgrade pip
.venv/Scripts/python.exe -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.dev.txt

cp .env.example .env
cp local.secrets.env.example local.secrets.env
cp windows_pipeline.example.json windows_pipeline.local.json
```

Заполните `.env` путями, VM-хостами и доменами. Для Windows-only режима можно
оставить `PROJECT_ROOT_WSL` и `RELEASE_ROOT_WSL` пустыми; при необходимости
задайте `RELEASE_ROOT_WINDOWS`.

Если SSH-вход выглядит как `ssh -i ./simple-deploy deploy-user@192.0.2.10`,
укажите:

```properties
APP_SSH_KEY_PATH=./simple-deploy
APP_VM_USER=deploy-user
```

Относительные `APP_SSH_KEY_PATH`, `DB_SSH_KEY_PATH` и общий `SSH_KEY_PATH` runner
ищет сначала от текущей директории, затем от домашней директории пользователя
Windows. Если один ключ подходит для обеих VM, можно задать только
`SSH_KEY_PATH`.

В `local.secrets.env` укажите доступ к PostgreSQL:

```properties
DB_LOGIN_USER=postgres
DB_LOGIN_PASSWORD=<password>
```

Для `dry-run`, `deploy` и `pipeline` `DB_LOGIN_PASSWORD` обязателен: пустое
значение и placeholder `change-me` считаются ошибкой конфигурации.

`windows_pipeline.local.json` нужен для локальных service steps,
healthcheck-команд, SQL-скриптов и включения backup. Если специальных команд нет,
можно оставить пример без изменений.

Команды рестарта EXAMPLE задавайте в `service_steps` в нужном порядке. Поддерживаемые
фазы: `before_unpack`, `after_unpack`, `after_migrate`; шаги без `phase`
выполняются как `after_migrate`. Команды запускаются на app VM по SSH под
`APP_VM_USER`; для сервисных операций используйте `sudo` с ограниченным набором
разрешенных команд в sudoers.

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

Во время `dry-run` runner сначала получает список доступных sudo-команд через
`sudo -n -l`, затем для каждого sudo service step проверяет точную команду через
`sudo -n -l <команда без sudo>`. Реальная сервисная команда на dry-run не
выполняется.

Если для шага нужна отдельная команда проверки, задайте `permission_check_command`
тоже через `sudo`:

```json
{
  "name": "start nginx",
  "phase": "after_migrate",
  "command": "sudo /bin/systemctl start nginx",
  "permission_check_command": "sudo /bin/systemctl start nginx"
}
```

Для этого в `/etc/sudoers.d/simple-deploy` должны быть разрешены точные пути
команд, например `/bin/systemctl start nginx`.

Также `dry-run` проверяет на app VM наличие и права `rwx` для директорий
`REMOTE_TMP_ROOT`, `BACKEND_RELEASE_PATH`, `FRONTEND_RELEASE_PATH` и
`APP_WORKDIR`. Проверка выполняется под `APP_VM_USER` и делает безопасный
`touch`/`rm` внутри каждой директории. Если директории нет или пользователь не
может писать туда без `sudo`, диагностика завершится `FAIL` до build/deploy.

При deploy целевая директория каждого артефакта очищается на первом уровне с
сохранением корневого `.env`, затем архив распаковывается с
`--strip-components=1`. То есть содержимое архивной директории `build/` или
`example_backend_app/` попадает прямо в `FRONTEND_RELEASE_PATH` или
`BACKEND_RELEASE_PATH`, без вложенного `build/build`.

Django management-команды запускаются после распаковки из `APP_WORKDIR`. Если
`management_commands` в `windows_pipeline.local.json` пустой, runner строит
дефолтные команды из `APP_MANAGE_PY_PATH`:

```properties
APP_WORKDIR=/opt/example/backend
APP_MANAGE_PY_PATH=manage.py
```

Если `manage.py` лежит глубже, укажите относительный путь от `APP_WORKDIR`,
например `example_backend_app/manage.py`, или абсолютный путь. Полностью
переопределить команды можно в `windows_pipeline.local.json`.

Диагностика:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py dry-run
```

Каждый запуск runner пишет вывод одновременно в консоль и в отдельный файл
`logs/<timestamp>-<command>.log`. Директория `logs/` не попадает в git.

После deploy healthcheck проверяет не только HTTP-доступность портала, но и
наличие текущей версии релиза на главной странице. Для React-приложения runner
сначала ищет версию в HTML, затем скачивает JS-ассеты из `<script src=...>` и
ищет версию в них. Отключить можно через
`"portal_version_check_enabled": false` в `windows_pipeline.local.json`.

Письмо об успешном deploy отправляется через установленный Outlook на рабочей
машине. Включите его в `windows_pipeline.local.json` и задайте получателей:

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

Локально должен быть установлен и настроен desktop Outlook, а профиль Outlook
должен быть доступен текущему Windows-пользователю. В
`windows_pipeline.local.json` должны быть непустые `outlook_email_recipients`,
`outlook_email_subject` и `outlook_email_body`. `dry-run` проверяет получателей,
шаблоны и создание Outlook COM до deploy. После успешного deploy письмо
прикладывает `release_manifest.json` из директории релиза, если файл существует.

Доступные шаблоны для темы и тела письма: `{build_version}`, `{stand_url}`,
`{dev_domain}`, `{release_dir}`, `{artifacts_text}`, `{release_changelog_text}`.
Changelog строится по двум `release_manifest.json`: текущего и предыдущего
релиза, отдельно для `BACKEND_SOURCE_REPO_PATH` и `FRONTEND_SOURCE_REPO_PATH`.
Если SHA совпадают, для репозитория будет указано `Изменений нет.` Если
`outlook_email_required` равен `false`, ошибка Outlook будет записана как `WARN`
и не превратит уже успешный deploy в ошибку.
`dry-run` проверяет получателей, тему, тело, корректность шаблонов и доступность
Outlook COM на рабочей машине.

Сборка релиза:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py build
```

Деплой уже собранного релиза:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py deploy --latest
```

или конкретной версии:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py deploy --build-version <версия>
```

Полный Windows-only pipeline:

```bash
.venv/Scripts/python.exe tools/windows_pipeline.py pipeline
```

Пример запуска полного pipeline по расписанию через Windows Task Scheduler лежит
в `tools/windows_task_scheduler/`.

Runner повторяет основной порядок Ansible-деплоя: DB maintenance, service steps,
загрузка архивов через `scp`, распаковка, Django management-команды, повторные
service steps и HTTP healthcheck. Ansible остается в репозитории как legacy-вариант
для Linux/WSL control node.

## Быстрый старт из Windows в WSL

Откройте PowerShell и перейдите в WSL:

```powershell
wsl -d Ubuntu
```

Дальше выполняйте команды внутри WSL Ubuntu.

```bash
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip git openssh-client netcat-openbsd

REPO_URL="https://github.com/lyu78/simple-deploy"
mkdir -p ~/simple-deploy-with-ansible
cd ~/simple-deploy-with-ansible
git clone "$REPO_URL" simple-deploy
cd simple-deploy

python3 -m venv .venv-ansible
.venv-ansible/bin/python -m pip install --upgrade pip
.venv-ansible/bin/python -m pip install -r requirements.ansible.txt
.venv-ansible/bin/python -m pip install -r requirements.dev.txt

cp .env.example .env
```

Заполните `.env` под свою машину и стенд: пути к backend/frontend-репозиториям,
адреса VM, SSH-пользователей, домены и пути деплоя. Для первой диагностики
обязательны как минимум значения, которые dry run проверяет через `.env`:

- `GIT_BASH_PATH`;
- `BACKEND_SOURCE_REPO_PATH`;
- `BACKEND_TARGET_REPO_PATH`;
- `BACKEND_TARGET_REPO_PATH_BASH`;
- `FRONTEND_SOURCE_REPO_PATH`;
- `FRONTEND_TARGET_REPO_PATH`;
- `APP_VM_HOST` и `APP_VM_USER`;
- `DB_VM_HOST`, `DB_VM_USER`, `DB_PORT`, `DB_NAME`;
- домены и пути деплоя из `.env.example`.

После этого запустите dry run:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Если нужно запустить dry run одной командой прямо из PowerShell или Git Bash,
вызывайте WSL явно:

```powershell
wsl -e bash -lc 'cd ~/simple-deploy-with-ansible/simple-deploy && ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml'
```

## Как читать dry run

Dry run не требует версии билда и не запускает сборку. Он проверяет:

- локальные backend/frontend Git-репозитории;
- наличие `origin` URL в этих репозиториях;
- доступность origin по сети без интерактивного `git ls-remote`;
- наличие системных команд на управляющей машине;
- TCP-доступность app VM, DB VM и PostgreSQL-порта;
- SSH-доступ к app VM и DB VM;
- наличие нужных директорий и runtime-команд на app VM;
- доступность PostgreSQL client на DB VM;
- HTTP endpoint DEV-стенда;
- при переданном `build_version` - наличие релизных архивов.

В выводе Ansible статус `ok` означает только, что конкретная Ansible-задача
выполнилась. Готовность окружения смотрите по строкам:

- `DRY-RUN PASS` - проверка прошла;
- `DRY-RUN FAIL` - найдена проблема;
- `DRY-RUN SKIP` - проверка осознанно пропущена;
- итоговый блок `DRY RUN RESULT` и список `failed_checks`.

Некоторые сетевые ошибки в процессе отображаются как `failed ...ignoring`. Это
нормально для диагностического режима: playbook не прерывается на первой
проблеме, а собирает полный список ошибок и завершает dry run общим отчетом.

Сетевые проверки ограничены `dry_run_command_timeout_seconds`, чтобы диагностика
не зависала на недоступном Git, VM или DB.

Если нужно проверить архивы конкретного релиза:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml \
  -e build_version=<версия>
```

## Полный запуск pipeline

После того как dry run показывает готовое окружение, можно запускать основной
pipeline:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml
```

`playbooks/pipeline.yml` управляет всем процессом: подготовкой конфигурации,
сборкой релиза и обновлением локального DEV-контура.

## Требования

Управляющая машина:

- WSL Ubuntu;
- Python 3 с `venv` и `pip`;
- Git;
- SSH-клиент;
- `netcat-openbsd`.

Windows-часть окружения:

- Git for Windows и Git Bash;
- Node.js/npm для frontend-сборки;
- Windows Python, если сборщик запускается через текущую команду
  `cmd.exe /C ... python create_release.py`.

Не запускайте `.venv-ansible/bin/ansible-playbook` напрямую из Git Bash: это
WSL-окружение, из Git Bash оно падает с `bad interpreter`.

## Конфигурация

Локальная конфигурация хранится в `.env`. Файл не коммитится. За основу берите:

```bash
cp .env.example .env
```

По умолчанию корень проекта вычисляется от директории playbook. Поэтому
`PROJECT_ROOT_WSL`, `RELEASE_ROOT_WSL` и `RELEASE_ROOT_BASH` можно оставить
пустыми, если репозиторий лежит в обычной структуре после `git clone`.

Если `.env` лежит не в корне проекта, укажите путь явно:

```bash
SIMPLE_DEPLOY_ENV_FILE=/path/to/.env \
ANSIBLE_CONFIG="$PWD/ansible.cfg" .venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Секреты БД храните отдельно:

```bash
cp group_vars/vault.example.yml group_vars/vault.yml
ansible-vault encrypt group_vars/vault.yml
```

## Что делает проект

1. Проверяет доступность внешних и внутренних Git-репозиториев.
2. Забирает изменения из внешних backend/frontend-репозиториев.
3. Переносит их во внутренние рабочие копии.
4. Собирает backend/frontend-архивы для релиза.
5. Публикует синхронизационные ветки во внутренние репозитории.
6. Через Ansible обновляет локальный DEV-стенд из собранных архивов.

## Структура

- `builder/` - существующий сборщик и архиваторы.
- `requirements.dev.txt` - зависимости сборщика.
- `requirements.ansible.txt` - зависимости Ansible.
- `playbooks/pipeline.yml` - единая точка входа для полного запуска.
- `playbooks/dry_run_local_contour.yml` - безопасная диагностика окружения.
- `group_vars/dev.yml` - основная Ansible-конфигурация.
- `group_vars/vault.example.yml` - шаблон секретов.
- `.env.example` - пример локальной конфигурации.
- `PIPELINE.MD` - подробное описание процесса.
- `CONTEXT.MD` - текущий технический контекст проекта.
