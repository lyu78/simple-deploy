"""Типы статусов локального состояния релизов."""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class BuildAttemptStatusEnum(DomainStringEnum):
    """Справочник статусов попытки сборки release bundle."""

    UNDEFINED = "undefined"
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


__all__ = [
    "BUILD_ATTEMPT_STATUSES",
    "DEPLOYMENT_ATTEMPT_STATUSES",
    "EXTERNAL_REQUEST_STATUSES",
    "JOB_STATUSES",
    "BuildAttemptStatusEnum",
    "DeploymentAttemptStatusEnum",
    "ExternalRequestStatusEnum",
    "JobStatusEnum",
]
