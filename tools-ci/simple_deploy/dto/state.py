"""DTO-модели ответов API локального состояния релизов."""

from __future__ import annotations

from typing import Any

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


class _StateDto(BaseModel):
    """Базовая DTO-модель для строк и объектов состояния."""

    model_config = ConfigDict(from_attributes=True)


class ReleaseReferenceDto(_StateDto):
    """Ссылка на ресурс релиза внутри API-проекции."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatus | None = None
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None


class ContourStateDto(_StateDto):
    """Текущий успешный baseline одного deploy-контура."""

    contour: ContourCode
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    last_success_release_ref: ReleaseReferenceDto | None = None
    updated_at: str


class ReleaseBundleDto(_StateDto):
    """Материализованный результат успешной сборки release bundle для API."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString | None = None
    artifacts_json: str
    created_at: str


class BuildAttemptDto(_StateDto):
    """Строка журнала попытки сборки для API."""

    id: int
    build_version: BuildVersionString
    status: BuildAttemptStatus
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None
    error: str | None = None
    started_at: str
    finished_at: str


class DeploymentAttemptDto(_StateDto):
    """Строка журнала попытки деплоя для API."""

    id: int
    contour: ContourCode
    build_version: BuildVersionString
    backend_commit: OptionalCommitShaString | None = None
    status: DeploymentAttemptStatus
    error: str | None = None
    started_at: str
    finished_at: str


class JobDto(_StateDto):
    """Запись локальной долгой операции для API."""

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


class ExternalRequestDto(_StateDto):
    """Запись внешней TEST/PROD заявки на релиз для API."""

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


class ReleaseDto(_StateDto):
    """Ресурс релиза для API."""

    build_version: BuildVersionString
    build_status: BuildAttemptStatus | None = None
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None
    bundle: ReleaseBundleDto | None = None
    build_attempts: list[BuildAttemptDto]
    deployment_attempts: list[DeploymentAttemptDto]
    external_requests: list[ExternalRequestDto]


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
    "ContourStateDto",
    "DeploymentAttemptDto",
    "ExternalRequestDto",
    "JobDto",
    "ReleaseBundleDto",
    "ReleaseDto",
    "ReleaseReferenceDto",
    "ReleaseRecordDto",
    "StateSnapshotDto",
    "dto_dump",
]
