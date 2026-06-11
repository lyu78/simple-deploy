"""Модели чтения локального состояния релизов."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from simple_deploy.types.contour import ContourCode, OptionalContourCode
from simple_deploy.types.release import BuildVersionString, OptionalBuildVersionString
from simple_deploy.types.source import CommitShaString, OptionalCommitShaString
from simple_deploy.types.status import (
    BuildAttemptStatus,
    DeploymentAttemptStatus,
    ExternalRequestStatus,
    JobStatus,
)


class _StateModel(BaseModel):
    """Базовая модель чтения из строк SQLite и dataclass-записей состояния."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


class ContourStateModel(_StateModel):
    """Модель чтения текущего baseline одного deploy-контура."""

    contour: ContourCode
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    updated_at: str


class ReleaseRecordModel(_StateModel):
    """Модель чтения успешно собранной записи релиза из SQLite."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString | None = None
    artifacts_json: str
    created_at: str


class BuildAttemptModel(_StateModel):
    """Модель чтения попытки сборки release bundle."""

    id: int
    build_version: BuildVersionString
    status: BuildAttemptStatus
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None
    error: str | None = None
    started_at: str
    finished_at: str


class DeploymentAttemptModel(_StateModel):
    """Модель чтения попытки размещения релиза на контуре."""

    id: int
    contour: ContourCode
    build_version: BuildVersionString
    backend_commit: OptionalCommitShaString | None = None
    status: DeploymentAttemptStatus
    error: str | None = None
    started_at: str
    finished_at: str


class JobModel(_StateModel):
    """Модель чтения локальной долгой операции."""

    id: int
    kind: str
    contour: OptionalContourCode
    build_version: OptionalBuildVersionString
    status: JobStatus
    payload_json: str
    log_path: str
    error: str
    created_at: str
    started_at: str
    finished_at: str


class ExternalRequestModel(_StateModel):
    """Модель чтения внешней TEST/PROD заявки."""

    id: int
    contour: ContourCode
    build_version: BuildVersionString
    request_type: str
    status: ExternalRequestStatus
    external_id: str
    payload_json: str
    error: str
    created_at: str
    updated_at: str


class StateSnapshotModel(_StateModel):
    """Агрегированный снимок локального состояния релизов только для чтения."""

    contours: dict[str, ContourStateModel | None]
    releases: list[ReleaseRecordModel]
    build_attempts: list[BuildAttemptModel]
    deployment_attempts: list[DeploymentAttemptModel]
    jobs: list[JobModel]
    external_requests: list[ExternalRequestModel]


__all__ = [
    "BuildAttemptModel",
    "ContourStateModel",
    "DeploymentAttemptModel",
    "ExternalRequestModel",
    "JobModel",
    "ReleaseRecordModel",
    "StateSnapshotModel",
]
