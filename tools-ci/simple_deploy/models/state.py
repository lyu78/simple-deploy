"""Модели чтения локального состояния релизов."""

from __future__ import annotations

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


class _StateReadModel(BaseModel):
    """Базовая модель чтения из строк SQLite и объектов состояния."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class ReleaseReferenceReadModel(_StateReadModel):
    """Ссылка на ресурс релиза внутри проекции чтения."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatusEnum = BuildAttemptStatusEnum.UNDEFINED
    backend_commit: OptionalCommitShaString = ""
    frontend_commit: OptionalCommitShaString = ""


class ContourStateReadModel(_StateReadModel):
    """Текущий baseline одного deploy-контура."""

    contour: ContourCodeEnum
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    last_success_release_ref: ReleaseReferenceReadModel | None = None
    updated_at: UpdatedAtString


class ReleaseBundleReadModel(_StateReadModel):
    """Материализованный результат успешной сборки release bundle."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString = ""
    artifacts_json: ArtifactsJsonString
    created_at: CreatedAtString


class BuildAttemptReadModel(_StateReadModel):
    """Попытка сборки release bundle."""

    id: int
    build_version: BuildVersionString
    status: BuildAttemptStatusEnum
    backend_commit: OptionalCommitShaString = ""
    frontend_commit: OptionalCommitShaString = ""
    error: ErrorText = ""
    started_at: StartedAtString
    finished_at: FinishedAtString


class DeploymentAttemptReadModel(_StateReadModel):
    """Попытка размещения релиза на контуре."""

    id: int
    contour: ContourCodeEnum
    build_version: BuildVersionString
    backend_commit: OptionalCommitShaString = ""
    status: DeploymentAttemptStatusEnum
    error: ErrorText = ""
    started_at: StartedAtString
    finished_at: FinishedAtString


class JobReadModel(_StateReadModel):
    """Локальная долгая операция."""

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


class WorkerHeartbeatReadModel(_StateReadModel):
    """Последний heartbeat локального polling worker-а."""

    worker_id: str
    status: str
    current_job_id: int | None = None
    message: str = ""
    updated_at: UpdatedAtString


class WorkerHealthReadModel(_StateReadModel):
    """Операторский снимок доступности локального worker-а."""

    status: str
    heartbeat: WorkerHeartbeatReadModel | None = None
    queued_jobs: int = 0
    running_jobs: int = 0
    stale_after_seconds: int = 10


class ExternalRequestReadModel(_StateReadModel):
    """Внешняя TEST/PROD заявка."""

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


class ReleaseReadModel(_StateReadModel):
    """Ресурс релиза с bundle-ом и историей операций."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatusEnum = BuildAttemptStatusEnum.UNDEFINED
    backend_commit: OptionalCommitShaString = ""
    frontend_commit: OptionalCommitShaString = ""
    bundle: ReleaseBundleReadModel | None = None
    build_attempts: list[BuildAttemptReadModel]
    deployment_attempts: list[DeploymentAttemptReadModel]
    external_requests: list[ExternalRequestReadModel]


class StateSnapshotReadModel(_StateReadModel):
    """Агрегированный снимок локального состояния релизов."""

    contours: dict[str, ContourStateReadModel | None]
    releases: list[ReleaseReadModel]
    build_attempts: list[BuildAttemptReadModel]
    deployment_attempts: list[DeploymentAttemptReadModel]
    jobs: list[JobReadModel]
    external_requests: list[ExternalRequestReadModel]


BuildAttemptModel = BuildAttemptReadModel
ContourStateModel = ContourStateReadModel
DeploymentAttemptModel = DeploymentAttemptReadModel
ExternalRequestModel = ExternalRequestReadModel
JobModel = JobReadModel
WorkerHeartbeatModel = WorkerHeartbeatReadModel
WorkerHealthModel = WorkerHealthReadModel
ReleaseBundleModel = ReleaseBundleReadModel
ReleaseModel = ReleaseReadModel
ReleaseReferenceModel = ReleaseReferenceReadModel
ReleaseRecordReadModel = ReleaseBundleReadModel
ReleaseRecordModel = ReleaseBundleReadModel
StateSnapshotModel = StateSnapshotReadModel


__all__ = [
    "BuildAttemptReadModel",
    "BuildAttemptModel",
    "ReleaseReferenceReadModel",
    "ReleaseReferenceModel",
    "ContourStateReadModel",
    "ContourStateModel",
    "DeploymentAttemptReadModel",
    "DeploymentAttemptModel",
    "ExternalRequestReadModel",
    "ExternalRequestModel",
    "JobReadModel",
    "JobModel",
    "WorkerHeartbeatReadModel",
    "WorkerHeartbeatModel",
    "WorkerHealthReadModel",
    "WorkerHealthModel",
    "ReleaseBundleReadModel",
    "ReleaseBundleModel",
    "ReleaseReadModel",
    "ReleaseModel",
    "ReleaseRecordReadModel",
    "ReleaseRecordModel",
    "StateSnapshotReadModel",
    "StateSnapshotModel",
]
