"""Write/use-case boundary поверх registry state.

Команды этого модуля выполняют небольшие атомарные с точки зрения приложения
изменения локального registry: двигают baseline контура и записывают attempts.
Они не читают release artifacts и не знают про CLI/HTTP. Если для команды нужен
backend commit из ``release_manifest.json``, его должен заранее извлечь
process/application слой и передать сюда готовым значением.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass

from simple_deploy.registry import state
from simple_deploy.types.job import JobKind
from simple_deploy.types.request import ExternalRequestType


@dataclass(frozen=True)
class DeploymentMarkResult:
    """Результат registry-команды фиксации deploy state."""

    contour: str
    build_version: str
    backend_commit: str


@dataclass(frozen=True)
class BuildAttemptResult:
    """Результат registry-команды фиксации build attempt."""

    attempt_id: int
    build_version: str
    backend_commit: str
    frontend_commit: str
    status: str
    error: str = ""


@dataclass(frozen=True)
class ReleaseBundleRecordResult:
    """Результат registry-команды записи успешного release bundle."""

    build_version: str
    backend_commit: str
    frontend_commit: str | None


@dataclass(frozen=True)
class LocalJobCommandResult:
    """Результат registry-команды изменения local job."""

    job: state.JobRecord


@dataclass(frozen=True)
class ExternalRequestCommandResult:
    """Результат registry-команды изменения external request."""

    request: state.ExternalRequest


def _require_job(job: state.JobRecord | None, job_id: int) -> state.JobRecord:
    """Возвращает job или поднимает ошибку нарушенного storage-инварианта."""
    if job is None:
        raise RuntimeError(f"Local job was not found after registry command: id={job_id}")
    return job


def _require_external_request(
    request: state.ExternalRequest | None,
    request_id: int,
) -> state.ExternalRequest:
    """Возвращает external request или поднимает ошибку нарушенного storage-инварианта."""
    if request is None:
        raise RuntimeError(
            f"External request was not found after registry command: id={request_id}"
        )
    return request


def record_release_bundle(
    build_version: str,
    backend_commit: str,
    frontend_commit: str | None,
    artifacts: dict,
) -> ReleaseBundleRecordResult:
    """Записывает метаданные успешно собранного release bundle."""
    with closing(state.connect_state_db()) as connection:
        state.record_release(
            connection,
            build_version=build_version,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
            artifacts=artifacts,
        )
    return ReleaseBundleRecordResult(build_version, backend_commit, frontend_commit)


def start_build_attempt(
    build_version: str,
    backend_commit: str = "",
    frontend_commit: str = "",
) -> BuildAttemptResult:
    """Создает запись о начале build attempt."""
    with closing(state.connect_state_db()) as connection:
        attempt_id = state.record_build_attempt_started(
            connection,
            build_version=build_version,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
        )
    return BuildAttemptResult(
        attempt_id=attempt_id,
        build_version=build_version,
        backend_commit=backend_commit,
        frontend_commit=frontend_commit,
        status="started",
    )


def finish_build_attempt(
    attempt_id: int,
    status: str,
    build_version: str = "",
    backend_commit: str = "",
    frontend_commit: str = "",
    error: str = "",
) -> BuildAttemptResult:
    """Фиксирует терминальный статус build attempt."""
    status = state.validate_status(status, {"success", "failed"})
    with closing(state.connect_state_db()) as connection:
        state.record_build_attempt_finished(
            connection,
            attempt_id=attempt_id,
            status=status,
            backend_commit=backend_commit,
            frontend_commit=frontend_commit,
            error=error,
        )
    return BuildAttemptResult(
        attempt_id=attempt_id,
        build_version=build_version,
        backend_commit=backend_commit,
        frontend_commit=frontend_commit,
        status=status,
        error=error,
    )


def create_local_job(
    kind: JobKind,
    contour: str = "",
    build_version: str = "",
    payload: dict | None = None,
    log_path: str = "",
) -> LocalJobCommandResult:
    """Создает local job в статусе ``queued``."""
    with closing(state.connect_state_db()) as connection:
        job_id = state.create_job(
            connection,
            kind=kind,
            contour=contour,
            build_version=build_version,
            payload=payload,
            log_path=log_path,
        )
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def mark_local_job_started(job_id: int, log_path: str = "") -> LocalJobCommandResult:
    """Помечает local job как ``running``."""
    with closing(state.connect_state_db()) as connection:
        state.mark_job_started(connection, job_id, log_path=log_path)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def finish_local_job(job_id: int, status: str, error: str = "") -> LocalJobCommandResult:
    """Помечает local job терминальным статусом."""
    with closing(state.connect_state_db()) as connection:
        state.mark_job_finished(connection, job_id, status=status, error=error)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def create_release_external_request(
    contour: str,
    build_version: str,
    request_type: ExternalRequestType,
    external_id: str = "",
    payload: dict | None = None,
    status: str = "draft",
) -> ExternalRequestCommandResult:
    """Создает external TEST/PROD request."""
    with closing(state.connect_state_db()) as connection:
        request_id = state.create_external_request(
            connection,
            contour=contour,
            build_version=build_version,
            request_type=request_type,
            external_id=external_id,
            payload=payload,
            status=status,
        )
        request = state.get_external_request(connection, request_id)
    return ExternalRequestCommandResult(_require_external_request(request, request_id))


def update_release_external_request_status(
    request_id: int,
    status: str,
    error: str = "",
    external_id: str | None = None,
) -> ExternalRequestCommandResult:
    """Обновляет статус external TEST/PROD request."""
    with closing(state.connect_state_db()) as connection:
        state.update_external_request_status(
            connection,
            request_id=request_id,
            status=status,
            error=error,
            external_id=external_id,
        )
        request = state.get_external_request(connection, request_id)
    return ExternalRequestCommandResult(_require_external_request(request, request_id))


def set_contour_baseline(
    contour: str,
    build_version: str,
    backend_commit: str,
) -> DeploymentMarkResult:
    """Двигает baseline контура без записи deployment attempt."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.upsert_contour_state(connection, contour, build_version, backend_commit)
    return DeploymentMarkResult(contour, build_version, backend_commit)


def record_deployment_applied(
    contour: str,
    build_version: str,
    backend_commit: str,
) -> DeploymentMarkResult:
    """Фиксирует успешное применение релиза и двигает baseline."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.upsert_contour_state(connection, contour, build_version, backend_commit)
        state.record_attempt(connection, contour, build_version, backend_commit, "success")
    return DeploymentMarkResult(contour, build_version, backend_commit)


def record_deployment_failed(
    contour: str,
    build_version: str,
    backend_commit: str,
    error_text: str,
) -> DeploymentMarkResult:
    """Фиксирует неуспешную deploy attempt без изменения baseline."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.record_attempt(connection, contour, build_version, backend_commit, "failed", error_text)
    return DeploymentMarkResult(contour, build_version, backend_commit)


__all__ = [
    "BuildAttemptResult",
    "DeploymentMarkResult",
    "ExternalRequestCommandResult",
    "LocalJobCommandResult",
    "ReleaseBundleRecordResult",
    "create_local_job",
    "create_release_external_request",
    "finish_build_attempt",
    "finish_local_job",
    "mark_local_job_started",
    "record_deployment_applied",
    "record_deployment_failed",
    "record_release_bundle",
    "set_contour_baseline",
    "start_build_attempt",
    "update_release_external_request_status",
]
