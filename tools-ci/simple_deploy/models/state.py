"""Модели чтения локального состояния релизов."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from simple_deploy.types.contour import ContourCode, OptionalContourCode
from simple_deploy.types.job import JobKind
from simple_deploy.types.release import BuildVersionString, OptionalBuildVersionString
from simple_deploy.types.request import ExternalRequestType
from simple_deploy.types.source import CommitShaString, OptionalCommitShaString
from simple_deploy.types.status import (
    BuildAttemptStatus,
    DeploymentAttemptStatus,
    ExternalRequestStatus,
    JobStatus,
)


class _StateReadModel(BaseModel):
    """Базовая модель чтения из строк SQLite и объектов состояния."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class ReleaseReferenceReadModel(_StateReadModel):
    """Ссылка на ресурс релиза внутри проекции чтения."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatus | None = None
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None


class ContourStateReadModel(_StateReadModel):
    """Текущий baseline одного deploy-контура."""

    contour: ContourCode
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    last_success_release_ref: ReleaseReferenceReadModel | None = None
    updated_at: str


class ReleaseBundleReadModel(_StateReadModel):
    """Материализованный результат успешной сборки release bundle."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString | None = None
    artifacts_json: str
    created_at: str


class BuildAttemptReadModel(_StateReadModel):
    """Попытка сборки release bundle."""

    id: int
    build_version: BuildVersionString
    status: BuildAttemptStatus
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None
    error: str | None = None
    started_at: str
    finished_at: str


class DeploymentAttemptReadModel(_StateReadModel):
    """Попытка размещения релиза на контуре."""

    id: int
    contour: ContourCode
    build_version: BuildVersionString
    backend_commit: OptionalCommitShaString | None = None
    status: DeploymentAttemptStatus
    error: str | None = None
    started_at: str
    finished_at: str


class JobReadModel(_StateReadModel):
    """Локальная долгая операция."""

    id: int
    kind: JobKind
    contour: OptionalContourCode
    build_version: OptionalBuildVersionString
    status: JobStatus
    payload_json: str
    log_path: str
    error: str
    created_at: str
    started_at: str
    finished_at: str


class ExternalRequestReadModel(_StateReadModel):
    """Внешняя TEST/PROD заявка."""

    id: int
    contour: ContourCode
    build_version: BuildVersionString
    request_type: ExternalRequestType
    status: ExternalRequestStatus
    external_id: str
    payload_json: str
    error: str
    created_at: str
    updated_at: str


class ReleaseReadModel(_StateReadModel):
    """Ресурс релиза с bundle-ом и историей операций."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatus | None = None
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None
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
    "ReleaseBundleReadModel",
    "ReleaseBundleModel",
    "ReleaseReadModel",
    "ReleaseModel",
    "ReleaseRecordReadModel",
    "ReleaseRecordModel",
    "StateSnapshotReadModel",
    "StateSnapshotModel",
]
