# simple-deploy

`simple-deploy` автоматизирует перенос изменений из внешнего контура разработки
во внутренний контур, сборку релизных архивов и обновление локального DEV-стенда.

Первый рекомендуемый запуск - безопасный Ansible dry run. Он ничего не собирает и
не раскатывает, а показывает, какие части окружения уже готовы и что нужно
исправить.

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
