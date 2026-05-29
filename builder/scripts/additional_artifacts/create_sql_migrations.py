"""
Скрипт создания миграций в формате sql.

Запускается из корня докер-контейнера основного бэкенда.

После первичного применения sql-скрипта необходимо выполнить
команду python manage.py migrate --fake

Если на чистую БД, до применения db_init применить все скрипты
из /docs/database/summary в хронологическом порядке, структура БД
будет соответствовать структуре после makemigrations.

Затем, для проверки работоспособности, можно использовать db_init
только для накатывания фикстур.

Фактически, скрипты не отличаются для тестового и продуктивного контура
за исключением скрипта назначения владельца, который добавляется вручную #TODO.
"""

import os
from datetime import datetime
import logging
import subprocess

UNUSED = "-- Unused migration"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY_DIR = os.path.join(BASE_DIR, "docs", "database", "summary")

# Получаем хэш коммита
def get_commit_hash():
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"

COMMIT_HASH = get_commit_hash()


def log_step(message):
    print(f"[backend-db-artifacts:create_sql_migrations] {message}", flush=True)


log_step(f"base dir: {BASE_DIR}")
log_step(f"summary dir: {SUMMARY_DIR}")
log_step(f"commit hash: {COMMIT_HASH}")

summary_sql = ""

migrations = {}

migrations_list = []

for file in os.listdir(SUMMARY_DIR):
    is_migration = False
    path = os.path.join(SUMMARY_DIR, file)

    with open(path) as f:
        rows = f.read().splitlines()

    for row in rows:
        if row != UNUSED and not is_migration:
            continue

        if row == UNUSED and not is_migration:
            is_migration = True
            continue

        if row == UNUSED and is_migration:
            break

        migrations_list.append(row.replace("-- ", ""))

migrations_plan = subprocess.run(
    [
        'python',
        'example_backend_app/manage.py',
        'showmigrations',
        '--plan'
    ], capture_output=True, text=True
)

statuses_names = migrations_plan.stdout.split("\n")

print(statuses_names)

for value in statuses_names:
    if not value:
        continue
    v = value.split("  ")
    migrations[v[1]] = (
        v[0],  # [x]
        v[1].split(".")[0],  # app_users
        v[1].split(".")[1]   # 0001_...
    )

datetime_now = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")

summary_sql += f"-- {datetime_now}\n{UNUSED}\n"
for m in migrations:
    if m not in migrations_list:
        summary_sql += f"-- {m}\n"
summary_sql += f"{UNUSED}\n"

result = None
generated_any = False

for m, v in migrations.items():
    if m in migrations_list:
        logging.warning(f"{m} произведена ранее, пропускаем!")
        continue
    logging.info(f"Формирование для {m}.")

    summary_sql += f"-- {m}\n\n"
    result = subprocess.run(
        [
            'python',
            'example_backend_app/manage.py',
            'sqlmigrate',
            v[1],
            v[2]
        ], capture_output=True, text=True)
    summary_sql += result.stdout
    summary_sql += "\n\n"
    generated_any = True

if not generated_any:
    summary_sql += "-- No new migrations detected for this commit.\n"
    logging.info("Новых миграций не обнаружено.")

output_path = os.path.join(SUMMARY_DIR, f"summary_sql_{datetime_now}_{COMMIT_HASH}.sql")
log_step(f"write summary SQL: {output_path}")

with open(output_path, "w", encoding="utf-8") as file:
    file.write(summary_sql)

log_step(f"summary SQL written: {output_path}")

if result and result.stderr:
    logging.error(result.stderr)
