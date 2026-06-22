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

from simple_deploy.models.state import ExternalRequestReadModel, JobReadModel
from simple_deploy.entities.release import ReleaseBundle
from simple_deploy.registry import state
from simple_deploy.release.manifest import manifest_from_release_bundle
from simple_deploy.types.contour import ContourCodeEnum
from simple_deploy.types.fields import ErrorText
from simple_deploy.types.job import JobKindEnum
from simple_deploy.types.release import (
    BuildVersionString,
    OptionalBuildVersionString,
)
from simple_deploy.types.request import ExternalRequestTypeEnum
from simple_deploy.types.source import CommitShaString, OptionalCommitShaString
from simple_deploy.types.status import BuildAttemptStatusEnum


@dataclass(frozen=True)
class DeploymentMarkResult:
    """Результат registry-команды фиксации deploy state."""

    contour: ContourCodeEnum
    build_version: BuildVersionString
    backend_commit: CommitShaString


@dataclass(frozen=True)
class BuildAttemptResult:
    """Результат registry-команды фиксации build attempt."""

    attempt_id: int
    build_version: OptionalBuildVersionString
    backend_commit: OptionalCommitShaString
    frontend_commit: OptionalCommitShaString
    status: BuildAttemptStatusEnum
    error: ErrorText = ""


@dataclass(frozen=True)
class ReleaseBundleRecordResult:
    """Результат registry-команды записи успешного release bundle."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString


@dataclass(frozen=True)
class LocalJobCommandResult:
    """Результат registry-команды изменения local job."""

    job: JobReadModel


@dataclass(frozen=True)
class ExternalRequestCommandResult:
    """Результат registry-команды изменения external request."""

    request: ExternalRequestReadModel


def _require_job(job: state.JobRecord | None, job_id: int) -> JobReadModel:
    """Возвращает job или поднимает ошибку нарушенного storage-инварианта."""
    if job is None:
        raise RuntimeError(
            f"Local job was not found after registry command: id={job_id}"
        )
    return JobReadModel.model_validate(job)


def _require_external_request(
    request: state.ExternalRequest | None,
    request_id: int,
) -> ExternalRequestReadModel:
    """
    Возвращает external request или поднимает ошибку нарушенного storage-
    инварианта.
    """
    if request is None:
        raise RuntimeError(
            "External request was not found after registry command: "
            f"id={request_id}"
        )
    return ExternalRequestReadModel.model_validate(request)


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
    return ReleaseBundleRecordResult(
        build_version, backend_commit, frontend_commit or ""
    )


def _bundle_commit(bundle: ReleaseBundle, repo_id: str) -> str:
    """Возвращает commit_sha source revision внутри release bundle."""
    for revision in bundle.source_snapshot.revisions:
        if revision.repo_id == repo_id:
            return revision.commit_sha
    return ""


def record_release_bundle_aggregate(
    bundle: ReleaseBundle,
) -> ReleaseBundleRecordResult:
    """Записывает успешный release bundle из доменного агрегата."""
    manifest = manifest_from_release_bundle(bundle)
    return record_release_bundle(
        build_version=bundle.build_version,
        backend_commit=_bundle_commit(bundle, "backend"),
        frontend_commit=_bundle_commit(bundle, "frontend"),
        artifacts=manifest["artifacts"],
    )


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
        status=BuildAttemptStatusEnum.STARTED,
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
    status_enum = BuildAttemptStatusEnum(status)
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
        status=status_enum,
        error=error,
    )


def create_local_job(
    kind: JobKindEnum | str,
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


def mark_local_job_started(
    job_id: int, log_path: str = ""
) -> LocalJobCommandResult:
    """Помечает local job как ``running``."""
    with closing(state.connect_state_db()) as connection:
        state.mark_job_started(connection, job_id, log_path=log_path)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def claim_next_local_job() -> LocalJobCommandResult | None:
    """Atomically claims the oldest queued local job for a worker."""
    with closing(state.connect_state_db()) as connection:
        job = state.claim_next_job(connection)
    if job is None:
        return None
    return LocalJobCommandResult(JobReadModel.model_validate(job))


def set_local_job_log_path(
    job_id: int, log_path: str
) -> LocalJobCommandResult:
    """Stores the log file path for a claimed local job."""
    with closing(state.connect_state_db()) as connection:
        state.set_job_log_path(connection, job_id, log_path)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def finish_local_job(
    job_id: int, status: str, error: str = ""
) -> LocalJobCommandResult:
    """Помечает local job терминальным статусом."""
    with closing(state.connect_state_db()) as connection:
        state.mark_job_finished(connection, job_id, status=status, error=error)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def cancel_local_job(
    job_id: int,
    error: str = "Cancelled by operator",
) -> LocalJobCommandResult:
    """Отменяет queued local job операторским transition-ом."""
    with closing(state.connect_state_db()) as connection:
        state.cancel_job(connection, job_id, error=error)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def requeue_local_job(job_id: int) -> LocalJobCommandResult:
    """Возвращает failed/cancelled local job в queued с тем же id."""
    with closing(state.connect_state_db()) as connection:
        state.requeue_job(connection, job_id)
        job = state.get_job(connection, job_id)
    return LocalJobCommandResult(_require_job(job, job_id))


def create_release_external_request(
    contour: str,
    build_version: str,
    request_type: ExternalRequestTypeEnum | str,
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
    return ExternalRequestCommandResult(
        _require_external_request(request, request_id)
    )


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
    return ExternalRequestCommandResult(
        _require_external_request(request, request_id)
    )


def set_contour_baseline(
    contour: str,
    build_version: str,
    backend_commit: str,
) -> DeploymentMarkResult:
    """Двигает baseline контура без записи deployment attempt."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.upsert_contour_state(
            connection, contour, build_version, backend_commit
        )
    return DeploymentMarkResult(
        ContourCodeEnum(contour), build_version, backend_commit
    )


def record_deployment_applied(
    contour: str,
    build_version: str,
    backend_commit: str,
) -> DeploymentMarkResult:
    """Фиксирует успешное применение релиза и двигает baseline."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.upsert_contour_state(
            connection, contour, build_version, backend_commit
        )
        state.record_attempt(
            connection, contour, build_version, backend_commit, "success"
        )
    return DeploymentMarkResult(
        ContourCodeEnum(contour), build_version, backend_commit
    )


def record_deployment_failed(
    contour: str,
    build_version: str,
    backend_commit: str,
    error_text: str,
) -> DeploymentMarkResult:
    """Фиксирует неуспешную deploy attempt без изменения baseline."""
    contour = state.validate_contour(contour)
    with closing(state.connect_state_db()) as connection:
        state.record_attempt(
            connection,
            contour,
            build_version,
            backend_commit,
            "failed",
            error_text,
        )
    return DeploymentMarkResult(
        ContourCodeEnum(contour), build_version, backend_commit
    )


__all__ = [
    "BuildAttemptResult",
    "DeploymentMarkResult",
    "ExternalRequestCommandResult",
    "LocalJobCommandResult",
    "ReleaseBundleRecordResult",
    "cancel_local_job",
    "claim_next_local_job",
    "create_local_job",
    "create_release_external_request",
    "finish_build_attempt",
    "finish_local_job",
    "mark_local_job_started",
    "record_deployment_applied",
    "record_deployment_failed",
    "record_release_bundle",
    "record_release_bundle_aggregate",
    "requeue_local_job",
    "set_contour_baseline",
    "set_local_job_log_path",
    "start_build_attempt",
    "update_release_external_request_status",
]
