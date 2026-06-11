"""DTO-модели только для чтения для ответов API локального состояния релизов."""

from __future__ import annotations

from typing import Any

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


class _StateDto(BaseModel):
    """Базовая DTO-модель для строк состояния и dataclass-записей."""

    model_config = ConfigDict(from_attributes=True)


class ContourStateDto(_StateDto):
    """Текущий успешный baseline одного deploy-контура."""

    contour: ContourCode
    last_success_release: BuildVersionString
    last_success_backend_commit: CommitShaString
    updated_at: str


class ReleaseRecordDto(_StateDto):
    """Запись успешно собранного релиза для read-only API."""

    build_version: BuildVersionString
    backend_commit: CommitShaString
    frontend_commit: OptionalCommitShaString | None = None
    artifacts_json: str
    created_at: str


class BuildAttemptDto(_StateDto):
    """Строка журнала попытки сборки для read-only API."""

    id: int
    build_version: BuildVersionString
    status: BuildAttemptStatus
    backend_commit: OptionalCommitShaString | None = None
    frontend_commit: OptionalCommitShaString | None = None
    error: str | None = None
    started_at: str
    finished_at: str


class DeploymentAttemptDto(_StateDto):
    """Строка журнала попытки деплоя для read-only API."""

    id: int
    contour: ContourCode
    build_version: BuildVersionString
    backend_commit: OptionalCommitShaString | None = None
    status: DeploymentAttemptStatus
    error: str | None = None
    started_at: str
    finished_at: str


class JobDto(_StateDto):
    """Запись локальной долгой операции для read-only API."""

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


class ExternalRequestDto(_StateDto):
    """Запись внешней TEST/PROD заявки на релиз для read-only API."""

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


class StateSnapshotDto(_StateDto):
    """Агрегированный снимок состояния только для чтения для dashboard и API."""

    contours: dict[str, ContourStateDto | None]
    releases: list[ReleaseRecordDto]
    build_attempts: list[BuildAttemptDto]
    deployment_attempts: list[DeploymentAttemptDto]
    jobs: list[JobDto]
    external_requests: list[ExternalRequestDto]


def dto_dump(model: BaseModel) -> dict[str, Any]:
    """Сериализует DTO в текущую JSON-совместимую форму API."""

    return model.model_dump(mode="json")


__all__ = [
    "BuildAttemptDto",
    "ContourStateDto",
    "DeploymentAttemptDto",
    "ExternalRequestDto",
    "JobDto",
    "ReleaseRecordDto",
    "StateSnapshotDto",
    "dto_dump",
]
