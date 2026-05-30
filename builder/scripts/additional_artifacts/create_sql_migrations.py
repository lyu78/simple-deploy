#!/usr/bin/env python3
"""Генератор SQL-артефактов Django schema migrations по контурам.

Модуль запускается из временной директории ``build_scripts`` внутри рабочей
копии backend source repo. Его задача - собрать SQL для DEV/TEST/PROD без
подключения к реальной PostgreSQL БД и без Docker-контейнера. Состояние
контуров передается сборщиком через переменную окружения
``SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON``:

    {"dev": "<commit>", "test": "<commit>", "prod": "<commit>"}

Для каждого контура скрипт сравнивает свой baseline commit с текущим ``HEAD``,
находит измененные Django migration-файлы, строит SQL через Django migration
API и записывает отдельный entrypoint вида ``summary_sql_<contour>_*.sql``.
Дополнительно создается ``schema_migrations_metadata.json``: переносимый
манифест с диапазонами ``from_commit -> to_commit`` и списком migration id,
которые попали в каждый SQL-файл.

Важное ограничение: это генерация schema DDL, а не проверка состояния БД.
Скрипт не читает таблицу ``django_migrations`` и не знает, какие миграции уже
фактически применены на контуре. Источником истины для диапазона является
локальная история релизов/контуров в simple-deploy.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types


CONTOURS = ("dev", "test", "prod")
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
BASELINES_ENV = "SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON"
METADATA_FILE = "schema_migrations_metadata.json"
MIGRATION_PATH_RE = re.compile(r"(^|/)(?P<app>[^/]+)/migrations/(?P<name>[0-9][^/]+)\.py$")
DEFAULT_BACKEND_APP_ROOT_DIR = "example_backend_app"
DJANGO_READY = False


def log(message: str) -> None:
    """Печатает сообщение генератора с единым префиксом для build-логов."""
    print(f"[backend-db-artifacts:create_sql_migrations] {message}", flush=True)


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Запускает команду из корня backend source repo и возвращает результат."""
    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def git_output(*args: str) -> str:
    """Выполняет ``git`` в backend source repo и возвращает очищенный stdout."""
    return run(["git", *args]).stdout.strip()


def load_baselines() -> dict[str, str]:
    """Читает baseline commit для каждого контура из переменной окружения."""
    raw = os.environ.get(BASELINES_ENV, "").strip()
    if not raw:
        raise RuntimeError(f"{BASELINES_ENV} is required")
    data = json.loads(raw)
    missing = [contour for contour in CONTOURS if not str(data.get(contour, "")).strip()]
    if missing:
        raise RuntimeError(f"Missing schema baselines for contours: {', '.join(missing)}")
    return {contour: str(data[contour]).strip() for contour in CONTOURS}


def changed_migration_ids(from_commit: str, to_commit: str) -> list[tuple[str, str, str]]:
    """Возвращает migration-файлы, измененные между двумя Git-коммитами."""
    if from_commit == to_commit:
        return []
    result = run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=AMR",
            f"{from_commit}..{to_commit}",
            "--",
            "*/migrations/*.py",
        ]
    )
    migrations = []
    seen = set()
    for raw_path in result.stdout.splitlines():
        path = raw_path.strip().replace("\\", "/")
        if not path or path.endswith("/__init__.py"):
            continue
        match = MIGRATION_PATH_RE.search(path)
        if not match:
            continue
        app = match.group("app")
        name = match.group("name")
        key = f"{app}.{name}"
        if key in seen:
            continue
        seen.add(key)
        migrations.append((key, app, name))
    return sorted(migrations, key=lambda item: item[0])


def ensure_django_ready() -> None:
    """Инициализирует Django один раз для offline-генерации SQL."""
    global DJANGO_READY
    if DJANGO_READY:
        return
    app_root_dir = os.environ.get("BACKEND_APP_ROOT_DIR", "").strip() or DEFAULT_BACKEND_APP_ROOT_DIR
    settings_module = (
        os.environ.get("BACKEND_DJANGO_SETTINGS_MODULE", "").strip()
        or f"{app_root_dir}.settings.base"
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    sys.path.insert(0, str(BASE_DIR / app_root_dir))
    import django

    django.setup()
    DJANGO_READY = True


def sqlmigrate(app_label: str, migration_name: str) -> str:
    """Генерирует SQL для одной Django migration без чтения реальной БД."""
    ensure_django_ready()
    from django.apps import apps
    from django.db import DEFAULT_DB_ALIAS, connections
    from django.db.migrations.loader import MigrationLoader

    connection = connections[DEFAULT_DB_ALIAS]
    install_offline_postgres_compose(connection)
    loader = MigrationLoader(None, replace_migrations=False)
    try:
        apps.get_app_config(app_label)
    except LookupError as exc:
        raise RuntimeError(str(exc)) from exc
    if app_label not in loader.migrated_apps:
        raise RuntimeError(f"App '{app_label}' does not have migrations")
    migration = loader.get_migration_by_prefix(app_label, migration_name)
    target = (app_label, migration.name)

    loader.connection = connection
    state = loader.project_state(target, at_end=False)
    with connection.schema_editor(collect_sql=True, atomic=False) as schema_editor:
        install_offline_schema_editor_helpers(schema_editor)
        migration.apply(state, schema_editor, collect_sql=True)
    return "\n".join(schema_editor.collected_sql)


def install_offline_postgres_compose(connection) -> None:
    """Подменяет PostgreSQL ``compose_sql`` на вариант без cursor/mogrify."""
    if getattr(connection.ops, "_simple_deploy_offline_compose", False):
        return
    try:
        from psycopg2.extensions import adapt
    except Exception:
        return

    def offline_compose_sql(sql: str, params) -> str:
        if not params:
            return sql
        parts = str(sql).split("%s")
        if len(parts) - 1 != len(params):
            return str(sql)
        output = [parts[0]]
        for value, tail in zip(params, parts[1:]):
            quoted = adapt(value).getquoted()
            if isinstance(quoted, bytes):
                quoted = quoted.decode("utf-8")
            output.append(str(quoted))
            output.append(tail)
        return "".join(output)

    connection.ops.compose_sql = offline_compose_sql
    connection.ops._simple_deploy_offline_compose = True


def install_offline_schema_editor_helpers(schema_editor) -> None:
    """Добавляет best-effort helpers для операций, которым нужны имена constraints."""
    def offline_constraint_names(
        self,
        model,
        column_names=None,
        unique=None,
        primary_key=None,
        index=None,
        foreign_key=None,
        check=None,
        type_=None,
        exclude=None,
    ):
        columns = list(column_names or [])
        table = model._meta.db_table
        if primary_key:
            return [f"{table}_pkey"]
        if unique and columns:
            return [self._create_index_name(table, columns, suffix="_uniq")]
        if index and columns:
            return [self._create_index_name(table, columns, suffix="_idx")]
        if foreign_key and columns:
            return [self._create_index_name(table, columns, suffix="_fk")]
        return []

    schema_editor._constraint_names = types.MethodType(offline_constraint_names, schema_editor)


def write_contour_sql(
    contour: str,
    from_commit: str,
    to_commit: str,
    to_short_commit: str,
    timestamp: str,
) -> dict:
    """Создает SQL-файл для одного контура и возвращает metadata блока."""
    migrations = changed_migration_ids(from_commit, to_commit)
    output_name = f"summary_sql_{contour}_{timestamp}_{from_commit[:12]}..{to_short_commit}.sql"
    output_path = SCRIPT_DIR / output_name
    log(f"write {contour} schema SQL: {output_path}")

    with output_path.open("w", encoding="utf-8") as file:
        file.write(f"-- Contour: {contour}\n")
        file.write(f"-- From backend commit: {from_commit}\n")
        file.write(f"-- To backend commit: {to_commit}\n")
        file.write(f"-- Generated at: {timestamp}\n\n")
        if not migrations:
            file.write("-- No Django migrations changed in this range.\n")
        for migration_id, app, migration_name in migrations:
            file.write(f"-- Migration: {migration_id}\n\n")
            file.write(sqlmigrate(app, migration_name))
            file.write("\n\n")

    return {
        "contour": contour,
        "from_commit": from_commit,
        "to_commit": to_commit,
        "entrypoint": output_name,
        "migrations": [migration_id for migration_id, _, _ in migrations],
    }


def main() -> None:
    """Точка входа генератора: читает baselines, пишет SQL и metadata."""
    baselines = load_baselines()
    to_commit = git_output("rev-parse", "HEAD")
    to_short_commit = git_output("rev-parse", "--short", "HEAD")
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")

    log(f"base dir: {BASE_DIR}")
    log(f"script dir: {SCRIPT_DIR}")
    log(f"to commit: {to_commit}")

    metadata = {
        "to_commit": to_commit,
        "to_short_commit": to_short_commit,
        "generated_at": timestamp,
        "contours": {},
    }
    for contour in CONTOURS:
        from_commit = baselines[contour]
        run(["git", "rev-parse", "--verify", f"{from_commit}^{{commit}}"])
        metadata["contours"][contour] = write_contour_sql(
            contour,
            from_commit,
            to_commit,
            to_short_commit,
            timestamp,
        )

    metadata_path = SCRIPT_DIR / METADATA_FILE
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"metadata written: {metadata_path}")


if __name__ == "__main__":
    main()
