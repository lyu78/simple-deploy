"""DTO-модели ответов API локального состояния релизов."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from simple_deploy.types.contour import ContourCodeEnum, JobContourScope
from simple_deploy.types.fields import (
    ArtifactsJsonString,
    CreatedAtString,
    ErrorText,
    ExternalIdString,
    FinishedAtString,
    LogPathString,
    PayloadJsonString,
    StartedAtString,
    UpdatedAtString,
)
from simple_deploy.types.job import JobKindEnum
from simple_deploy.types.release import (
    BuildVersionString,
    OptionalBuildVersionString,
)
from simple_deploy.types.request import ExternalRequestTypeEnum
from simple_deploy.types.source import CommitShaString, OptionalCommitShaString
from simple_deploy.types.status import (
    BuildAttemptStatusEnum,
    DeploymentAttemptStatusEnum,
    ExternalRequestStatusEnum,
    JobStatusEnum,
)


class _StateDto(BaseModel):
    """Базовая DTO-модель для строк и объектов состояния."""

    model_config = ConfigDict(from_attributes=True)


class ReleaseReferenceDto(_StateDto):
    """Ссылка на ресурс релиза внутри API-проекции."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatusEnum = BuildAttemptStatusEnum.UNDEFINED
    backend_commit: OptionalCommitShaString = ""
    frontend_commit: OptionalCommitShaString = ""


class ContourStateDto(_StateDto):
    """Текущий успешный baseline одного deploy-контура."""

    contour: ContourCodeEnum
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    last_success_release_ref: ReleaseReferenceDto | None = None
    updated_at: UpdatedAtString


class ReleaseBundleDto(_StateDto):
    """Материализованный результат успешной сборки release bundle для API."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString = ""
    artifacts_json: ArtifactsJsonString
    created_at: CreatedAtString


class BuildAttemptDto(_StateDto):
    """Строка журнала попытки сборки для API."""

    id: int
    build_version: BuildVersionString
    status: BuildAttemptStatusEnum
    backend_commit: OptionalCommitShaString = ""
    frontend_commit: OptionalCommitShaString = ""
    error: ErrorText = ""
    started_at: StartedAtString
    finished_at: FinishedAtString


class DeploymentAttemptDto(_StateDto):
    """Строка журнала попытки деплоя для API."""

    id: int
    contour: ContourCodeEnum
    build_version: BuildVersionString
    backend_commit: OptionalCommitShaString = ""
    status: DeploymentAttemptStatusEnum
    error: ErrorText = ""
    started_at: StartedAtString
    finished_at: FinishedAtString


class JobDto(_StateDto):
    """Запись локальной долгой операции для API."""

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


class WorkerHeartbeatDto(_StateDto):
    """Последний heartbeat локального polling worker-а для API."""

    worker_id: str
    status: str
    current_job_id: int | None = None
    message: str = ""
    updated_at: UpdatedAtString


class WorkerHealthDto(_StateDto):
    """Операторский статус локального worker-а для API."""

    status: str
    heartbeat: WorkerHeartbeatDto | None = None
    queued_jobs: int = 0
    running_jobs: int = 0
    stale_after_seconds: int = 10


class ExternalRequestDto(_StateDto):
    """Запись внешней TEST/PROD заявки на релиз для API."""

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


class ReleaseDto(_StateDto):
    """Ресурс релиза для API."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatusEnum = BuildAttemptStatusEnum.UNDEFINED
    backend_commit: OptionalCommitShaString = ""
    frontend_commit: OptionalCommitShaString = ""
    bundle: ReleaseBundleDto | None = None
    build_attempts: list[BuildAttemptDto]
    deployment_attempts: list[DeploymentAttemptDto]
    external_requests: list[ExternalRequestDto]


class BuildOptionDto(_StateDto):
    """Selectable release build for operator forms."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString = ""
    created_at: CreatedAtString = ""
    build_status: BuildAttemptStatusEnum = BuildAttemptStatusEnum.SUCCESS
    source: str = "registry"


class StateSnapshotDto(_StateDto):
    """Агрегированный снимок состояния для dashboard и API."""

    contours: dict[str, ContourStateDto | None]
    releases: list[ReleaseDto]
    build_attempts: list[BuildAttemptDto]
    deployment_attempts: list[DeploymentAttemptDto]
    jobs: list[JobDto]
    external_requests: list[ExternalRequestDto]


def dto_dump(model: BaseModel) -> dict[str, Any]:
    """Сериализует DTO в текущую JSON-совместимую форму API."""
    return model.model_dump(mode="json")


ReleaseRecordDto = ReleaseBundleDto


__all__ = [
    "BuildAttemptDto",
    "BuildOptionDto",
    "ContourStateDto",
    "DeploymentAttemptDto",
    "ExternalRequestDto",
    "JobDto",
    "WorkerHeartbeatDto",
    "WorkerHealthDto",
    "ReleaseBundleDto",
    "ReleaseDto",
    "ReleaseReferenceDto",
    "ReleaseRecordDto",
    "StateSnapshotDto",
    "dto_dump",
]
