"""Локальное состояние релизов и контуров в SQLite.

Модуль хранит операционную историю simple-deploy: какие релизы были собраны,
какой backend commit считается последним успешно примененным на каждом контуре
(``dev``, ``test``, ``prod``), и какие попытки применения завершились успехом
или ошибкой. Упавшие сборки хранятся отдельно от ``releases``, чтобы таблица
релизов оставалась журналом только успешно собранных manifest.

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
JOB_STATUSES = ("queued", "running", "success", "failed", "cancelled")
REQUEST_STATUSES = ("draft", "submitted", "approved", "applied", "failed", "cancelled")


@dataclass(frozen=True)
class ContourState:
    """Снимок последнего успешного состояния одного контура."""

    contour: str
    last_success_release: str
    last_success_backend_commit: str
    updated_at: str


@dataclass(frozen=True)
class JobRecord:
    """Snapshot of a local long-running operation."""

    id: int
    kind: str
    contour: str
    build_version: str
    status: str
    payload_json: str
    log_path: str
    error: str
    created_at: str
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class ExternalRequest:
    """Snapshot of a TEST/PROD external release request."""

    id: int
    contour: str
    build_version: str
    request_type: str
    status: str
    external_id: str
    payload_json: str
    error: str
    created_at: str
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

        create table if not exists build_attempts (
            id integer primary key autoincrement,
            build_version text not null,
            status text not null,
            backend_commit text,
            frontend_commit text,
            error text,
            started_at text not null,
            finished_at text not null
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

        create table if not exists local_jobs (
            id integer primary key autoincrement,
            kind text not null,
            contour text not null,
            build_version text not null,
            status text not null,
            payload_json text not null,
            log_path text not null,
            error text not null,
            created_at text not null,
            started_at text not null,
            finished_at text not null
        );

        create index if not exists idx_local_jobs_status_created
            on local_jobs(status, created_at);

        create index if not exists idx_local_jobs_contour_build
            on local_jobs(contour, build_version);

        create table if not exists external_requests (
            id integer primary key autoincrement,
            contour text not null,
            build_version text not null,
            request_type text not null,
            status text not null,
            external_id text not null,
            payload_json text not null,
            error text not null,
            created_at text not null,
            updated_at text not null
        );

        create index if not exists idx_external_requests_contour_build
            on external_requests(contour, build_version);

        create index if not exists idx_external_requests_status_updated
            on external_requests(status, updated_at);
        """
    )
    connection.commit()


def validate_status(status: str, allowed: Iterable[str]) -> str:
    """Нормализует и валидирует статус записи локального журнала."""
    normalized = status.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unknown status: {status}. Expected one of: {', '.join(sorted(allowed))}")
    return normalized


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


def record_build_attempt_started(
    connection: sqlite3.Connection,
    build_version: str,
    backend_commit: str = "",
    frontend_commit: str = "",
) -> int:
    """Добавляет запись о начале попытки сборки релиза."""
    now = utc_now()
    cursor = connection.execute(
        """
        insert into build_attempts (
            build_version,
            status,
            backend_commit,
            frontend_commit,
            error,
            started_at,
            finished_at
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (build_version, "started", backend_commit, frontend_commit, "", now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def record_build_attempt_finished(
    connection: sqlite3.Connection,
    attempt_id: int,
    status: str,
    backend_commit: str = "",
    frontend_commit: str = "",
    error: str = "",
) -> None:
    """Обновляет итог попытки сборки релиза."""
    status = validate_status(status, {"success", "failed"})
    connection.execute(
        """
        update build_attempts
        set
            status = ?,
            backend_commit = ?,
            frontend_commit = ?,
            error = ?,
            finished_at = ?
        where id = ?
        """,
        (status, backend_commit, frontend_commit, error, utc_now(), attempt_id),
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


def _json_payload(payload: dict | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=int(row["id"]),
        kind=row["kind"],
        contour=row["contour"],
        build_version=row["build_version"],
        status=row["status"],
        payload_json=row["payload_json"],
        log_path=row["log_path"],
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _external_request_from_row(row: sqlite3.Row) -> ExternalRequest:
    return ExternalRequest(
        id=int(row["id"]),
        contour=row["contour"],
        build_version=row["build_version"],
        request_type=row["request_type"],
        status=row["status"],
        external_id=row["external_id"],
        payload_json=row["payload_json"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dict_from_row(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def list_releases(connection: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Return recent successful release records."""
    rows = connection.execute(
        """
        select *
        from releases
        order by created_at desc, build_version desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [_dict_from_row(row) for row in rows]


def list_build_attempts(connection: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Return recent build attempts."""
    rows = connection.execute(
        """
        select *
        from build_attempts
        order by id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [_dict_from_row(row) for row in rows]


def list_deployment_attempts(
    connection: sqlite3.Connection,
    contour: str = "",
    limit: int = 50,
) -> list[dict]:
    """Return recent deployment attempts."""
    if contour:
        contour = validate_contour(contour)
        rows = connection.execute(
            """
            select *
            from deployment_attempts
            where contour = ?
            order by id desc
            limit ?
            """,
            (contour, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select *
            from deployment_attempts
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [_dict_from_row(row) for row in rows]


def create_job(
    connection: sqlite3.Connection,
    kind: str,
    contour: str = "",
    build_version: str = "",
    payload: dict | None = None,
    log_path: str = "",
) -> int:
    """Create a queued local job for a long-running CLI/web operation."""
    kind = kind.strip()
    if not kind:
        raise ValueError("Job kind must be non-empty")
    normalized_contour = validate_contour(contour) if contour else ""
    now = utc_now()
    cursor = connection.execute(
        """
        insert into local_jobs (
            kind,
            contour,
            build_version,
            status,
            payload_json,
            log_path,
            error,
            created_at,
            started_at,
            finished_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (kind, normalized_contour, build_version, "queued", _json_payload(payload), log_path, "", now, "", ""),
    )
    connection.commit()
    return int(cursor.lastrowid)


def mark_job_started(connection: sqlite3.Connection, job_id: int, log_path: str = "") -> None:
    """Mark a local job as running."""
    connection.execute(
        """
        update local_jobs
        set status = ?, log_path = coalesce(nullif(?, ''), log_path), started_at = ?
        where id = ?
        """,
        ("running", log_path, utc_now(), job_id),
    )
    connection.commit()


def mark_job_finished(connection: sqlite3.Connection, job_id: int, status: str, error: str = "") -> None:
    """Mark a local job as terminal."""
    status = validate_status(status, {"success", "failed", "cancelled"})
    connection.execute(
        """
        update local_jobs
        set status = ?, error = ?, finished_at = ?
        where id = ?
        """,
        (status, error, utc_now(), job_id),
    )
    connection.commit()


def get_job(connection: sqlite3.Connection, job_id: int) -> JobRecord | None:
    """Return a local job by id."""
    row = connection.execute(
        """
        select *
        from local_jobs
        where id = ?
        """,
        (job_id,),
    ).fetchone()
    return _job_from_row(row) if row else None


def list_jobs(connection: sqlite3.Connection, limit: int = 50) -> list[JobRecord]:
    """Return recent local jobs."""
    rows = connection.execute(
        """
        select *
        from local_jobs
        order by id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [_job_from_row(row) for row in rows]


def create_external_request(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    request_type: str,
    external_id: str = "",
    payload: dict | None = None,
    status: str = "draft",
) -> int:
    """Create a TEST/PROD external release request record."""
    contour = validate_contour(contour)
    if contour == "dev":
        raise ValueError("External release requests are only supported for test/prod contours")
    request_type = request_type.strip()
    if not request_type:
        raise ValueError("External request type must be non-empty")
    status = validate_status(status, REQUEST_STATUSES)
    now = utc_now()
    cursor = connection.execute(
        """
        insert into external_requests (
            contour,
            build_version,
            request_type,
            status,
            external_id,
            payload_json,
            error,
            created_at,
            updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (contour, build_version, request_type, status, external_id, _json_payload(payload), "", now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_external_request_status(
    connection: sqlite3.Connection,
    request_id: int,
    status: str,
    error: str = "",
    external_id: str | None = None,
) -> None:
    """Update TEST/PROD external release request status."""
    status = validate_status(status, REQUEST_STATUSES)
    if external_id is None:
        connection.execute(
            """
            update external_requests
            set status = ?, error = ?, updated_at = ?
            where id = ?
            """,
            (status, error, utc_now(), request_id),
        )
    else:
        connection.execute(
            """
            update external_requests
            set status = ?, external_id = ?, error = ?, updated_at = ?
            where id = ?
            """,
            (status, external_id, error, utc_now(), request_id),
        )
    connection.commit()


def get_external_request(connection: sqlite3.Connection, request_id: int) -> ExternalRequest | None:
    """Return a TEST/PROD external request by id."""
    row = connection.execute(
        """
        select *
        from external_requests
        where id = ?
        """,
        (request_id,),
    ).fetchone()
    return _external_request_from_row(row) if row else None


def list_external_requests(
    connection: sqlite3.Connection,
    contour: str = "",
    limit: int = 50,
) -> list[ExternalRequest]:
    """Return recent TEST/PROD external requests."""
    if contour:
        contour = validate_contour(contour)
        rows = connection.execute(
            """
            select *
            from external_requests
            where contour = ?
            order by id desc
            limit ?
            """,
            (contour, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select *
            from external_requests
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [_external_request_from_row(row) for row in rows]
