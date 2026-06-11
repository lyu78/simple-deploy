"""Типы статусов локального состояния релизов."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints


BUILD_ATTEMPT_STATUSES = ("started", "success", "failed")
DEPLOYMENT_ATTEMPT_STATUSES = ("started", "success", "failed")
JOB_STATUSES = ("queued", "running", "success", "failed", "cancelled")
EXTERNAL_REQUEST_STATUSES = (
    "draft",
    "submitted",
    "approved",
    "applied",
    "failed",
    "cancelled",
)


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
    "DeploymentAttemptStatus",
    "ExternalRequestStatus",
    "JobStatus",
]
