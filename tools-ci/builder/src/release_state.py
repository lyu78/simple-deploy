"""Локальное состояние релизов и контуров в SQLite.

Модуль хранит операционную историю simple-deploy: какие релизы были собраны,
какой backend commit считается последним успешно примененным на каждом контуре
(``dev``, ``test``, ``prod``), и какие попытки применения завершились успехом
или ошибкой.

SQLite используется как локальный журнал рабочей машины. Он не заменяет
``release_manifest.json``: manifest остается переносимым описанием конкретного
релиза, а SQLite отвечает за текущее локальное представление состояния
контуров. Поэтому база лежит в ``local_state/`` и не коммитится в Git.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable


CONTOURS = ("dev", "test", "prod")


@dataclass(frozen=True)
class ContourState:
    """Снимок последнего успешного состояния одного контура."""

    contour: str
    last_success_release: str
    last_success_backend_commit: str
    updated_at: str


def default_state_db_path() -> Path:
    """Возвращает путь к SQLite-базе состояния simple-deploy."""
    configured = os.environ.get("SIMPLE_DEPLOY_STATE_DB", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "local_state" / "simple_deploy.sqlite3"


def utc_now() -> str:
    """Возвращает текущий UTC timestamp в компактном ISO-формате."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def validate_contour(contour: str) -> str:
    """Нормализует и валидирует имя контура."""
    normalized = contour.strip().lower()
    if normalized not in CONTOURS:
        raise ValueError(f"Unknown contour: {contour}. Expected one of: {', '.join(CONTOURS)}")
    return normalized


def connect_state_db(path: Path | None = None) -> sqlite3.Connection:
    """Открывает SQLite-соединение и гарантирует наличие схемы таблиц."""
    db_path = path or default_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Создает таблицы локального журнала, если их еще нет."""
    connection.executescript(
        """
        create table if not exists contour_state (
            contour text primary key,
            last_success_release text not null,
            last_success_backend_commit text not null,
            updated_at text not null
        );

        create table if not exists releases (
            build_version text primary key,
            backend_commit text not null,
            frontend_commit text,
            artifacts_json text not null,
            created_at text not null
        );

        create table if not exists deployment_attempts (
            id integer primary key autoincrement,
            contour text not null,
            build_version text not null,
            backend_commit text,
            status text not null,
            error text,
            started_at text not null,
            finished_at text not null
        );
        """
    )
    connection.commit()


def get_contour_state(connection: sqlite3.Connection, contour: str) -> ContourState | None:
    """Возвращает последний успешный release/commit для контура или ``None``."""
    contour = validate_contour(contour)
    row = connection.execute(
        """
        select contour, last_success_release, last_success_backend_commit, updated_at
        from contour_state
        where contour = ?
        """,
        (contour,),
    ).fetchone()
    if not row:
        return None
    return ContourState(
        contour=row["contour"],
        last_success_release=row["last_success_release"],
        last_success_backend_commit=row["last_success_backend_commit"],
        updated_at=row["updated_at"],
    )


def all_contour_states(connection: sqlite3.Connection) -> dict[str, ContourState | None]:
    """Возвращает состояние всех поддерживаемых контуров."""
    return {contour: get_contour_state(connection, contour) for contour in CONTOURS}


def upsert_contour_state(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    backend_commit: str,
) -> None:
    """Создает или обновляет последний успешный release/commit контура."""
    contour = validate_contour(contour)
    connection.execute(
        """
        insert into contour_state (
            contour,
            last_success_release,
            last_success_backend_commit,
            updated_at
        )
        values (?, ?, ?, ?)
        on conflict(contour) do update set
            last_success_release = excluded.last_success_release,
            last_success_backend_commit = excluded.last_success_backend_commit,
            updated_at = excluded.updated_at
        """,
        (contour, build_version, backend_commit, utc_now()),
    )
    connection.commit()


def record_release(
    connection: sqlite3.Connection,
    build_version: str,
    backend_commit: str,
    frontend_commit: str | None,
    artifacts: dict,
) -> None:
    """Записывает metadata собранного релиза в локальный журнал."""
    connection.execute(
        """
        insert into releases (
            build_version,
            backend_commit,
            frontend_commit,
            artifacts_json,
            created_at
        )
        values (?, ?, ?, ?, ?)
        on conflict(build_version) do update set
            backend_commit = excluded.backend_commit,
            frontend_commit = excluded.frontend_commit,
            artifacts_json = excluded.artifacts_json,
            created_at = excluded.created_at
        """,
        (
            build_version,
            backend_commit,
            frontend_commit,
            json.dumps(artifacts, ensure_ascii=False, sort_keys=True),
            utc_now(),
        ),
    )
    connection.commit()


def record_attempt(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    backend_commit: str,
    status: str,
    error: str = "",
) -> None:
    """Добавляет запись о попытке применения релиза на контур."""
    contour = validate_contour(contour)
    now = utc_now()
    connection.execute(
        """
        insert into deployment_attempts (
            contour,
            build_version,
            backend_commit,
            status,
            error,
            started_at,
            finished_at
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (contour, build_version, backend_commit, status, error, now, now),
    )
    connection.commit()


def missing_baselines(connection: sqlite3.Connection, contours: Iterable[str] = CONTOURS) -> list[str]:
    """Возвращает список контуров, для которых еще не задан baseline."""
    missing = []
    for contour in contours:
        if get_contour_state(connection, contour) is None:
            missing.append(contour)
    return missing
