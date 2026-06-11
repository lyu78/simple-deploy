"""Типы статусов локального состояния релизов."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class BuildAttemptStatusEnum(DomainStringEnum):
    """Справочник статусов попытки сборки release bundle."""

    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"


class DeploymentAttemptStatusEnum(DomainStringEnum):
    """Справочник статусов попытки размещения релиза."""

    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"


class JobStatusEnum(DomainStringEnum):
    """Справочник статусов локальной долгой операции."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExternalRequestStatusEnum(DomainStringEnum):
    """Справочник статусов внешней TEST/PROD заявки."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


BUILD_ATTEMPT_STATUSES = BuildAttemptStatusEnum.get_values()
DEPLOYMENT_ATTEMPT_STATUSES = DeploymentAttemptStatusEnum.get_values()
JOB_STATUSES = JobStatusEnum.get_values()
EXTERNAL_REQUEST_STATUSES = ExternalRequestStatusEnum.get_values()


def _validate_status(value: str, allowed: tuple[str, ...], label: str) -> str:
    """Проверяет статус по конкретному справочнику."""

    if value not in allowed:
        raise ValueError(f"Unknown {label}: {value}. Expected one of: {', '.join(allowed)}")
    return value


def _validate_build_attempt_status(value: str) -> str:
    """Проверяет статус попытки сборки."""

    return _validate_status(value, BUILD_ATTEMPT_STATUSES, "build attempt status")


def _validate_deployment_attempt_status(value: str) -> str:
    """Проверяет статус попытки деплоя."""

    return _validate_status(value, DEPLOYMENT_ATTEMPT_STATUSES, "deployment attempt status")


def _validate_job_status(value: str) -> str:
    """Проверяет статус локальной долгой операции."""

    return _validate_status(value, JOB_STATUSES, "job status")


def _validate_external_request_status(value: str) -> str:
    """Проверяет статус внешней заявки."""

    return _validate_status(value, EXTERNAL_REQUEST_STATUSES, "external request status")


BuildAttemptStatus = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_build_attempt_status),
]
"""Статус попытки сборки release bundle."""


DeploymentAttemptStatus = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_deployment_attempt_status),
]
"""Статус попытки размещения релиза на контуре."""


JobStatus = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_job_status),
]
"""Статус локальной долгой операции."""


ExternalRequestStatus = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_external_request_status),
]
"""Статус внешней TEST/PROD заявки."""


__all__ = [
    "BUILD_ATTEMPT_STATUSES",
    "DEPLOYMENT_ATTEMPT_STATUSES",
    "EXTERNAL_REQUEST_STATUSES",
    "JOB_STATUSES",
    "BuildAttemptStatus",
    "BuildAttemptStatusEnum",
    "DeploymentAttemptStatus",
    "DeploymentAttemptStatusEnum",
    "ExternalRequestStatus",
    "ExternalRequestStatusEnum",
    "JobStatus",
    "JobStatusEnum",
]
