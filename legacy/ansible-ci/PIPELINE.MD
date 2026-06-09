# E2E пайплайн через Ansible/WSL

## Статус

Это legacy-вариант для Linux/WSL control node. Он сохраняется в репозитории, но
основной текущий путь - Windows/Python runner из `../tools-ci/PIPELINE.MD`.

Общий продуктовый процесс описан в `../PIPELINE.MD`.

## Общая схема

Ansible запускается из WSL и управляет полным циклом: подготовкой релиза через
существующий Python-сборщик и обновлением локального DEV-контура из созданных
архивов.

Основной запуск:

```bash
cd legacy/ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml
```

Повторная раскатка уже собранного релиза без повторной сборки:

```bash
cd legacy/ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml \
  -e run_build=false -e build_version=<build_version>
```

Безопасная диагностика:

```bash
cd legacy/ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Если нужно проверить архивы конкретного релиза, dry-run получает
`-e build_version=<build_version>` или `-e use_latest_release=true`.

## Этапы Ansible-flow

`legacy/ansible-ci/playbooks/pipeline.yml` подключает два внутренних этапа:

- `legacy/ansible-ci/playbooks/stages/build_release.yml` - подготовка окружения и запуск
  `tools-ci/builder/create_release.py`.
- `legacy/ansible-ci/playbooks/stages/deploy_local_contour.yml` - обновление локального DEV-контура.

Порядок выполнения:

1. Загрузка конфигурации DEV-контура из `legacy/ansible-ci/group_vars/dev.yml`.
2. Загрузка секретов из `legacy/ansible-ci/group_vars/vault.yml`, если файл существует.
3. Генерация `tools-ci/builder/settings/*/.env` из tracked-шаблонов.
4. Запуск `tools-ci/builder/create_release.py` с окружением `build_environment`.
5. Определение директории релиза по `build_version` или по последнему релизу.
6. Поиск backend/frontend архивов по настроенным шаблонам.
7. DB maintenance SQL для текущей фазы.
8. Service steps фазы `before_unpack`.
9. Копирование архивов на app VM.
10. Backup текущих директорий деплоя, если `backup_enabled: true`.
11. Распаковка backend/frontend в настроенные release paths.
12. Service steps фазы `after_unpack`.
13. Django management-команды: `migrate --fake`, затем `sync_action_role`.
14. SQL scripts и service steps фазы `after_migrate`.
15. HTTP healthcheck и дополнительные healthcheck-команды.
16. Итоговая сводка Ansible-запуска.

## Конфигурация

Основной файл настройки - `.env` в корне проекта. Его нужно создать из
`.env.example` и заполнить:

- пути рабочих копий backend/frontend;
- `GIT_BASH_PATH`;
- `APP_VM_HOST`, `APP_VM_USER`;
- `DB_VM_HOST`, `DB_VM_USER`, порт и имя БД;
- пути деплоя на app VM;
- параметры подключения к БД;
- домены dev/test/prod.

`legacy/ansible-ci/group_vars/dev.yml` не должен хранить реальные адреса конкретной машины. Он
читает `.env` и описывает, как эти значения используются в Ansible-flow.

Секреты Ansible лежат в `legacy/ansible-ci/group_vars/vault.yml`; файл не хранится в git и
создается из `legacy/ansible-ci/group_vars/vault.example.yml`.

`PROJECT_ROOT_WSL`, `RELEASE_ROOT_WSL` и `RELEASE_ROOT_BASH` опциональны. Их
нужно задавать только для нестандартной раскладки проекта или директории релизов.

## Требования WSL

Управляющей WSL-машине нужны:

- Python 3 с `venv` и `pip`;
- Git;
- SSH client;
- `netcat-openbsd`;
- зависимости из `legacy/ansible-ci/requirements.ansible.txt` и `tools-ci/requirements.dev.txt`.

При запуске из WSL на Windows-диске `/mnt/c` переходите в `legacy/ansible-ci` и
передавайте `ANSIBLE_CONFIG="$PWD/ansible.cfg"`, иначе Ansible может
проигнорировать `ansible.cfg` из-за прав drvfs и не найти локальные роли.

PostgreSQL client проверяется и используется на DB VM через SSH, поэтому на
управляющей WSL-машине `psql` не нужен.

## Dry-run

Ansible dry-run не требует версии билда и не запускает сборку. Он проверяет:

- локальные backend/frontend Git-репозитории;
- наличие `origin` URL и сетевую доступность origin через `curl`;
- наличие системных команд на управляющей машине;
- TCP-доступность app VM, DB VM и PostgreSQL-порта через `nc`;
- SSH-доступ к app VM и DB VM;
- нужные директории и runtime-команды на app VM;
- PostgreSQL client на DB VM;
- HTTP endpoint DEV-стенда;
- наличие релизных архивов, если передан `build_version`.

Статус Ansible-задачи (`ok`, `skipping`, `failed`, `ignored`) описывает только
выполнение playbook-задачи. Готовность окружения смотрится по строкам
`DRY-RUN PASS`, `DRY-RUN FAIL`, `DRY-RUN SKIP` и итоговому списку
`failed_checks`.

Сетевые ошибки могут отображаться как `failed ...ignoring`: это часть
диагностического режима, который собирает полный список проблем и не падает на
первой недоступной точке.

## Граница ответственности

Ansible-flow:

- управляет порядком сборки и деплоя;
- запускает существующий сборщик, но не заменяет build-скрипты;
- не пушит runtime-архивы во внутренний GitLab;
- обновляет локальный DEV-контур из уже собранного релиза;
- выполняет технические DB-команды, management-команды, service steps и
  healthcheck.
