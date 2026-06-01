# Обновление локального контура через Ansible

Этот playbook обновляет локальный DEV-контур из архивов, которые уже собраны
локальным сборочным pipeline.

## Среда запуска

Запускайте Ansible из WSL Ubuntu. Машинно-специфичные значения задаются один раз
в локальном `.env` в корне проекта. Этот файл не хранится в репозитории.

Первичная настройка:

```bash
cp .env.example .env
```

После копирования заполните `.env` путями, хостами, портами и доменами своей
рабочей машины. `ansible-ci/group_vars/dev.yml` читает эти значения и строит на их основе
пути, URL, build environment и параметры раскатки.

`PROJECT_ROOT_WSL`, `RELEASE_ROOT_WSL` и `RELEASE_ROOT_BASH` можно оставить пустыми.
В этом случае Ansible возьмет корень проекта от inventory, релизы будет искать в
`<корень проекта>/releases`, а bash-путь к релизам построит автоматически.

Установите минимальные инструменты в WSL:

```bash
.venv-ansible/bin/python -m pip install -r tools-ci/requirements.dev.txt
.venv-ansible/bin/python -m pip install -r ansible-ci/requirements.ansible.txt
sudo apt-get update
sudo apt-get install -y postgresql-client
```

При запуске из WSL на Windows-диске `/mnt/c` переходите в `ansible-ci` и задавайте `ANSIBLE_CONFIG="$PWD/ansible.cfg"`.
Иначе Ansible может проигнорировать `ansible.cfg` из-за прав drvfs и не найти локальные роли.
SSH настроен на один парольный prompt без повторных retries, чтобы неверный пароль
не запрашивался несколько раз подряд.

Создайте файл секретов, если для подключения к БД нужен пароль:

```bash
cp ansible-ci/group_vars/vault.example.yml ansible-ci/group_vars/vault.yml
ansible-vault encrypt ansible-ci/group_vars/vault.yml
```

## Безопасная проверка

Проверьте поиск архивов и планируемые пути без изменений на app VM:

Dry run сначала проверяет доступность `origin` внешних и внутренних backend/frontend
репозиториев, затем сетевую доступность app VM и DB VM, SSH и остальные условия.

```bash
cd ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml
```

Этот запуск не требует версии билда и не проверяет конкретные архивы.

Либо используйте новейшую директорию релиза:

```bash
cd ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/dry_run_local_contour.yml \
  -e use_latest_release=true
```

## Основной запуск всего пайплайна

```bash
cd ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml
```

Этот запуск сам вызывает `tools-ci/builder/create_release.py`, выбирает собранный релиз и
обновляет локальный контур.

## Обновление уже собранного релиза

```bash
cd ansible-ci
ANSIBLE_CONFIG="$PWD/ansible.cfg" ../.venv-ansible/bin/ansible-playbook \
  -i inventories/dev/hosts.yml playbooks/pipeline.yml \
  -e run_build=false -e build_version=1.0.3.27052026_1200 --ask-vault-pass
```

Отдельного пользовательского playbook для раскатки больше нет. Для штатной сборки,
повторной раскатки и запуска по расписанию используется `ansible-ci/playbooks/pipeline.yml`.
Внутренние этапы лежат в `ansible-ci/playbooks/stages/` и напрямую оператором не запускаются.

## Настройка деплоя

Перед первым реальным запуском отредактируйте `ansible-ci/group_vars/dev.yml`:

- `backend_release_path`
- `frontend_release_path`
- `app_workdir`
- `app_venv_activate_path`
- `app_manage_py_path`
- `service_steps`
- `healthcheck_commands`

`service_steps` - это упорядоченный список shell-команд. Такой подход оставляет
первую версию независимой от того, используется ли на VM systemd, supervisor
или смешанное управление сервисами.

Сервисные шаги поддерживают фазы:

- `before_unpack`: остановить сервисы до замены файлов.
- `after_unpack`: выполнить команды после распаковки архивов.
- `after_migrate`: запустить или перезапустить сервисы после management-команд.

Шаги без `phase` для совместимости выполняются в `after_migrate`.

`sql_scripts` можно позже использовать для SQL-скриптов из репозитория:

```yaml
sql_scripts:
  - path: "{{ project_root_wsl }}/sql/before_migrate.sql"
    phase: before_migrate
  - path: "{{ project_root_wsl }}/sql/after_migrate.sql"
    phase: after_migrate
```
