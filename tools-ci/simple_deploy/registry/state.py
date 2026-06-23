"""
Локальное registry state simple-deploy в SQLite.

Модуль хранит операционную историю toolkit-а: собранные release bundles,
последний успешно примененный backend commit по контурам, build/deploy
attempts, local jobs и external TEST/PROD requests.

Это storage-facing API. Read projections должны собираться в
``simple_deploy.registry.queries``, а application-level write operations - в
``simple_deploy.registry.commands``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable

from simple_deploy.types.contour import (
    CONTOUR_CODES,
    ContourCodeEnum,
    JobContourScope,
)
from simple_deploy.types.fields import (
    CreatedAtString,
    ErrorText,
    ExternalIdString,
    FinishedAtString,
    LogPathString,
    PayloadJsonString,
    StartedAtString,
    UpdatedAtString,
)
from simple_deploy.types.job import JOB_KINDS, JobKindEnum
from simple_deploy.types.release import (
    BuildVersionString,
    OptionalBuildVersionString,
)
from simple_deploy.types.request import (
    EXTERNAL_REQUEST_TYPES,
    ExternalRequestTypeEnum,
)
from simple_deploy.types.source import CommitShaString
from simple_deploy.types.status import (
    EXTERNAL_REQUEST_STATUSES,
    ExternalRequestStatusEnum,
    JOB_STATUSES as JOB_STATUS_CODES,
    JobStatusEnum,
)

CONTOURS = CONTOUR_CODES
JOB_KIND_CODES = JOB_KINDS
JOB_STATUSES = JOB_STATUS_CODES
REQUEST_TYPES = EXTERNAL_REQUEST_TYPES
REQUEST_STATUSES = EXTERNAL_REQUEST_STATUSES
WORKER_STATUSES = frozenset(
    {"starting", "idle", "running", "stopped", "error"}
)
CONTOUR_SCOPED_JOB_KINDS = frozenset(
    {
        JobKindEnum.DEPLOY.value,
        JobKindEnum.SET_BASELINE.value,
        JobKindEnum.MARK_APPLIED.value,
        JobKindEnum.MARK_FAILED.value,
    }
)


@dataclass(frozen=True)
class ContourState:
    """Снимок baseline одного deploy-контура."""

    contour: ContourCodeEnum
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    updated_at: UpdatedAtString


@dataclass(frozen=True)
class JobRecord:
    """Снимок локальной долгой операции."""

    id: int
    kind: JobKindEnum
    contour: JobContourScope
    build_version: OptionalBuildVersionString
    status: JobStatusEnum
    payload_json: PayloadJsonString
    log_path: LogPathString
    error: ErrorText
    created_at: CreatedAtString
    started_at: StartedAtString
    finished_at: FinishedAtString


@dataclass(frozen=True)
class WorkerHeartbeat:
    """Последний heartbeat локального polling worker-а."""

    worker_id: str
    status: str
    current_job_id: int | None
    message: str
    updated_at: UpdatedAtString


@dataclass(frozen=True)
class ExternalRequest:
    """Снимок внешней заявки на продвижение релиза."""

    id: int
    contour: ContourCodeEnum
    build_version: BuildVersionString
    request_type: ExternalRequestTypeEnum
    status: ExternalRequestStatusEnum
    external_id: ExternalIdString
    payload_json: PayloadJsonString
    error: ErrorText
    created_at: CreatedAtString
    updated_at: UpdatedAtString


def default_state_db_path() -> Path:
    """Возвращает путь к локальной SQLite-базе состояния релизов."""
    configured = os.environ.get("SIMPLE_DEPLOY_STATE_DB", "").strip()
    if configured:
        return Path(configured)
    return (
        Path(__file__).resolve().parents[3]
        / "local_state"
        / "simple_deploy.sqlite3"
    )


def utc_now() -> str:
    """Возвращает текущий UTC timestamp для записей локального журнала."""
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def validate_contour(contour: str) -> str:
    """Нормализует и валидирует имя deploy-контура."""
    normalized = contour.strip().lower()
    if normalized not in CONTOURS:
        expected = ", ".join(CONTOURS)
        raise ValueError(
            f"Unknown contour: {contour}. Expected one of: {expected}"
        )
    return normalized


def connect_state_db(path: Path | None = None) -> sqlite3.Connection:
    """Открывает SQLite-соединение и гарантирует наличие схемы."""
    db_path = path or default_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("pragma busy_timeout = 5000")
    connection.row_factory = sqlite3.Row
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Создает или обновляет базовую схему локального журнала."""
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

        create table if not exists worker_heartbeat (
            worker_id text primary key,
            status text not null,
            current_job_id integer,
            message text not null,
            updated_at text not null
        );

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
    """Нормализует и валидирует статус для заданного набора."""
    normalized = status.strip().lower()
    if normalized not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ValueError(
            f"Unknown status: {status}. Expected one of: {expected}"
        )
    return normalized


def validate_job_kind(kind: str) -> str:
    """Нормализует и валидирует вид локальной долгой операции."""
    normalized = kind.strip().lower()
    if normalized not in JOB_KIND_CODES:
        expected = ", ".join(JOB_KIND_CODES)
        raise ValueError(
            f"Unknown job kind: {kind}. Expected one of: {expected}"
        )
    return normalized


def validate_worker_status(status: str) -> str:
    """Нормализует и валидирует статус локального worker heartbeat."""
    normalized = status.strip().lower()
    if normalized not in WORKER_STATUSES:
        expected = ", ".join(sorted(WORKER_STATUSES))
        raise ValueError(
            f"Unknown worker status: {status}. Expected one of: {expected}"
        )
    return normalized


def validate_external_request_type(request_type: str) -> str:
    """Нормализует и валидирует тип внешней TEST/PROD заявки."""
    normalized = request_type.strip().lower()
    if normalized not in REQUEST_TYPES:
        expected = ", ".join(REQUEST_TYPES)
        raise ValueError(
            f"Unknown external request type: {request_type}. "
            f"Expected one of: {expected}"
        )
    return normalized


def get_contour_state(
    connection: sqlite3.Connection, contour: str
) -> ContourState | None:
    """Читает baseline одного контура из SQLite."""
    contour = validate_contour(contour)
    row = connection.execute(
        """
        select
            contour,
            last_success_release,
            last_success_backend_commit,
            updated_at
        from contour_state
        where contour = ?
        """,
        (contour,),
    ).fetchone()
    if not row:
        return None
    return ContourState(
        contour=ContourCodeEnum(row["contour"]),
        last_success_release=row["last_success_release"],
        last_success_backend_commit=row["last_success_backend_commit"],
        updated_at=row["updated_at"],
    )


def all_contour_states(
    connection: sqlite3.Connection,
) -> dict[str, ContourState | None]:
    """Возвращает baseline-состояние всех поддерживаемых контуров."""
    return {
        contour: get_contour_state(connection, contour) for contour in CONTOURS
    }


def upsert_contour_state(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    backend_commit: str,
) -> None:
    """Создает или обновляет baseline успешного применения релиза."""
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
    """Записывает метаданные успешно собранного релиза в SQLite."""
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
            frontend_commit or "",
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
    """Создает запись о начале попытки сборки релиза."""
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
        (
            build_version,
            "started",
            backend_commit,
            frontend_commit,
            "",
            now,
            now,
        ),
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
    """Фиксирует итог ранее начатой попытки сборки."""
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
        (
            status,
            backend_commit,
            frontend_commit,
            error,
            utc_now(),
            attempt_id,
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


def missing_baselines(
    connection: sqlite3.Connection, contours: Iterable[str] = CONTOURS
) -> list[str]:
    """Возвращает список контуров без заданного baseline."""
    missing = []
    for contour in contours:
        if get_contour_state(connection, contour) is None:
            missing.append(contour)
    return missing


def _json_payload(payload: dict | None) -> str:
    """Сериализует payload записи слоя состояния в JSON."""
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    """Преобразует строку ``local_jobs`` в ``JobRecord``."""
    return JobRecord(
        id=int(row["id"]),
        kind=JobKindEnum(row["kind"]),
        contour=row["contour"],
        build_version=row["build_version"],
        status=JobStatusEnum(row["status"]),
        payload_json=row["payload_json"],
        log_path=row["log_path"],
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _worker_heartbeat_from_row(row: sqlite3.Row) -> WorkerHeartbeat:
    """Преобразует строку ``worker_heartbeat`` в read dataclass."""
    current_job_id = row["current_job_id"]
    return WorkerHeartbeat(
        worker_id=row["worker_id"],
        status=row["status"],
        current_job_id=int(current_job_id)
        if current_job_id is not None
        else None,
        message=row["message"],
        updated_at=row["updated_at"],
    )


def _external_request_from_row(row: sqlite3.Row) -> ExternalRequest:
    """Преобразует строку ``external_requests`` в ``ExternalRequest``."""
    return ExternalRequest(
        id=int(row["id"]),
        contour=ContourCodeEnum(row["contour"]),
        build_version=row["build_version"],
        request_type=ExternalRequestTypeEnum(row["request_type"]),
        status=ExternalRequestStatusEnum(row["status"]),
        external_id=row["external_id"],
        payload_json=row["payload_json"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dict_from_row(row: sqlite3.Row) -> dict:
    """Преобразует произвольную SQLite-строку в словарь."""
    return {key: row[key] for key in row.keys()}


def list_releases(
    connection: sqlite3.Connection, limit: int = 50
) -> list[dict]:
    """Возвращает последние успешно собранные релизы."""
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


def list_build_attempts(
    connection: sqlite3.Connection, limit: int = 50
) -> list[dict]:
    """Возвращает последние попытки сборки релиза."""
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
    """Возвращает последние попытки применения релиза."""
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
    kind: JobKindEnum | str,
    contour: str = "",
    build_version: str = "",
    payload: dict | None = None,
    log_path: str = "",
) -> int:
    """Создает запись локальной долгой операции в статусе ``queued``."""
    kind = validate_job_kind(kind)
    normalized_contour = validate_contour(contour) if contour else ""
    if not normalized_contour and kind in CONTOUR_SCOPED_JOB_KINDS:
        raise ValueError(f"Local job kind requires contour: {kind}")
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
        (
            kind,
            normalized_contour,
            build_version,
            "queued",
            _json_payload(payload),
            log_path,
            "",
            now,
            "",
            "",
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def mark_job_started(
    connection: sqlite3.Connection, job_id: int, log_path: str = ""
) -> None:
    """Помечает локальное задание как запущенное."""
    connection.execute(
        """
        update local_jobs
        set
            status = ?,
            log_path = coalesce(nullif(?, ''), log_path),
            started_at = ?
        where id = ?
        """,
        ("running", log_path, utc_now(), job_id),
    )
    connection.commit()


def claim_next_job(connection: sqlite3.Connection) -> JobRecord | None:
    """Atomically claims the oldest queued local job for a worker."""
    try:
        connection.execute("begin immediate")
        row = connection.execute(
            """
            select *
            from local_jobs
            where status = ?
            order by created_at, id
            limit 1
            """,
            ("queued",),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        job_id = int(row["id"])
        cursor = connection.execute(
            """
            update local_jobs
            set status = ?, started_at = ?
            where id = ? and status = ?
            """,
            ("running", utc_now(), job_id, "queued"),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        row = connection.execute(
            """
            select *
            from local_jobs
            where id = ?
            """,
            (job_id,),
        ).fetchone()
        connection.commit()
        return _job_from_row(row) if row else None
    except Exception:
        connection.rollback()
        raise


def set_job_log_path(
    connection: sqlite3.Connection, job_id: int, log_path: str
) -> None:
    """Stores the log file path for a claimed local job."""
    connection.execute(
        """
        update local_jobs
        set log_path = coalesce(nullif(?, ''), log_path)
        where id = ?
        """,
        (log_path, job_id),
    )
    connection.commit()


def mark_job_finished(
    connection: sqlite3.Connection, job_id: int, status: str, error: str = ""
) -> None:
    """Помечает локальное задание терминальным статусом."""
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


def cancel_job(
    connection: sqlite3.Connection,
    job_id: int,
    error: str = "Cancelled by operator",
) -> None:
    """Отменяет queued local job без попытки остановить running process."""
    try:
        connection.execute("begin immediate")
        row = connection.execute(
            """
            select *
            from local_jobs
            where id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise LookupError(f"Local job not found: id={job_id}")
        status = row["status"]
        if status != "queued":
            connection.rollback()
            raise ValueError(
                f"Cannot cancel local job id={job_id} "
                f"with status={status}; expected queued"
            )
        connection.execute(
            """
            update local_jobs
            set status = ?, error = ?, finished_at = ?
            where id = ?
            """,
            ("cancelled", error, utc_now(), job_id),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def requeue_job(connection: sqlite3.Connection, job_id: int) -> None:
    """Возвращает failed/cancelled local job в очередь с тем же id."""
    try:
        connection.execute("begin immediate")
        row = connection.execute(
            """
            select *
            from local_jobs
            where id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            connection.rollback()
            raise LookupError(f"Local job not found: id={job_id}")
        status = row["status"]
        if status not in {"failed", "cancelled"}:
            connection.rollback()
            raise ValueError(
                f"Cannot requeue local job id={job_id} "
                f"with status={status}; expected failed or cancelled"
            )
        connection.execute(
            """
            update local_jobs
            set
                status = ?,
                log_path = ?,
                error = ?,
                started_at = ?,
                finished_at = ?
            where id = ?
            """,
            ("queued", "", "", "", "", job_id),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def get_job(connection: sqlite3.Connection, job_id: int) -> JobRecord | None:
    """Возвращает локальное задание по id."""
    row = connection.execute(
        """
        select *
        from local_jobs
        where id = ?
        """,
        (job_id,),
    ).fetchone()
    return _job_from_row(row) if row else None


def list_jobs(
    connection: sqlite3.Connection, limit: int = 50
) -> list[JobRecord]:
    """Возвращает последние локальные задания."""
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


def count_jobs_by_status(connection: sqlite3.Connection) -> dict[str, int]:
    """Возвращает количество local jobs по lifecycle status."""
    rows = connection.execute(
        """
        select status, count(*) as count
        from local_jobs
        group by status
        """
    ).fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def upsert_worker_heartbeat(
    connection: sqlite3.Connection,
    *,
    worker_id: str = "local",
    status: str = "idle",
    current_job_id: int | None = None,
    message: str = "",
) -> None:
    """Записывает последний heartbeat локального polling worker-а."""
    worker_id = worker_id.strip() or "local"
    status = validate_worker_status(status)
    connection.execute(
        """
        insert into worker_heartbeat (
            worker_id,
            status,
            current_job_id,
            message,
            updated_at
        )
        values (?, ?, ?, ?, ?)
        on conflict(worker_id) do update set
            status = excluded.status,
            current_job_id = excluded.current_job_id,
            message = excluded.message,
            updated_at = excluded.updated_at
        """,
        (worker_id, status, current_job_id, message, utc_now()),
    )
    connection.commit()


def get_worker_heartbeat(
    connection: sqlite3.Connection, worker_id: str = "local"
) -> WorkerHeartbeat | None:
    """Возвращает последний heartbeat локального worker-а."""
    worker_id = worker_id.strip() or "local"
    row = connection.execute(
        """
        select *
        from worker_heartbeat
        where worker_id = ?
        """,
        (worker_id,),
    ).fetchone()
    return _worker_heartbeat_from_row(row) if row else None


def create_external_request(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    request_type: ExternalRequestTypeEnum | str,
    external_id: str = "",
    payload: dict | None = None,
    status: str = "draft",
) -> int:
    """Создает запись внешней заявки для TEST/PROD."""
    contour = validate_contour(contour)
    if contour == "dev":
        raise ValueError(
            "External release requests are only supported for "
            "test/prod contours"
        )
    request_type = validate_external_request_type(request_type)
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
        (
            contour,
            build_version,
            request_type,
            status,
            external_id,
            _json_payload(payload),
            "",
            now,
            now,
        ),
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
    """Обновляет статус внешней заявки TEST/PROD."""
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


def get_external_request(
    connection: sqlite3.Connection, request_id: int
) -> ExternalRequest | None:
    """Возвращает внешнюю заявку по id."""
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
    """Возвращает последние внешние заявки TEST/PROD."""
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


__all__ = [
    "CONTOURS",
    "JOB_KIND_CODES",
    "JOB_STATUSES",
    "REQUEST_TYPES",
    "REQUEST_STATUSES",
    "WORKER_STATUSES",
    "ContourState",
    "ExternalRequest",
    "JobRecord",
    "WorkerHeartbeat",
    "all_contour_states",
    "cancel_job",
    "claim_next_job",
    "connect_state_db",
    "count_jobs_by_status",
    "create_external_request",
    "create_job",
    "default_state_db_path",
    "ensure_schema",
    "get_contour_state",
    "get_external_request",
    "get_job",
    "get_worker_heartbeat",
    "list_build_attempts",
    "list_deployment_attempts",
    "list_external_requests",
    "list_jobs",
    "list_releases",
    "mark_job_finished",
    "mark_job_started",
    "missing_baselines",
    "record_attempt",
    "record_build_attempt_finished",
    "record_build_attempt_started",
    "record_release",
    "requeue_job",
    "set_job_log_path",
    "update_external_request_status",
    "upsert_worker_heartbeat",
    "upsert_contour_state",
    "utc_now",
    "validate_contour",
    "validate_external_request_type",
    "validate_job_kind",
    "validate_status",
    "validate_worker_status",
]
