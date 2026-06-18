"""Типы deploy entrypoints на VM/серверах."""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class DeploymentTargetRoleEnum(DomainStringEnum):
    """
    Справочник ролей deploy entrypoint-ов внутри landscape.

    Deploy entrypoint здесь - это серверный target для размещения релиза:
    роль на VM/сервере или внешнем ресурсе, например backend slot на app VM,
    database slot на DB VM или S3 target.
    """

    BACKEND = "backend"
    FRONTEND = "frontend"
    DATABASE = "database"
    CACHE = "cache"
    REPORTING = "reporting"
    S3 = "s3"


DEPLOYMENT_TARGET_ROLES = DeploymentTargetRoleEnum.get_values()


__all__ = [
    "DEPLOYMENT_TARGET_ROLES",
    "DeploymentTargetRoleEnum",
]
