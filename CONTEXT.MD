# Контекст проекта

Проект автоматизирует одностороннюю доставку изменений из внешнего контура во
внутренний контур, сборку релизных архивов и обновление локального DEV-стенда.
Рабочая машина является управляющей точкой: на ней лежат рабочие копии внешних и
внутренних репозиториев, запускается сборщик и с нее Ansible подключается к VM.

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
