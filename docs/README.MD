# Documentation

Единая точка входа в человеческую документацию `simple-deploy`.

## Runbooks

- `runbooks/manual-sql-release-run.md` - ручное применение schema и data SQL
  artifacts из release bundle на DB VM.
- `runbooks/legacy-ansible-local-contour.md` - legacy обновление локального
  контура через Ansible.

## SQL

- `sql/data-script-markup.md` - контракт разметки data SQL-скриптов backend
  repo.
- `sql/data-validation-rules.md` - read-only правила проверки идемпотентности и
  бизнес-ключей data SQL.

## Tasks

- `tasks/data-sql-markup-remediation.md` - разовое рабочее задание по
  исправлению разметки SQL-скриптов data migration.

## Diagrams

Диаграммы SQL release flow лежат в `diagrams/sql-release/`:

- `release-sql-migrations-flow.puml` - общий pipeline от dry-run до
  DEV/TEST/PROD.
- `release-sql-migrations-build-dev.puml` - сборка и DEV-размещение.
- `release-sql-migrations-test-prod.puml` - продвижение релиза на TEST и PROD.
