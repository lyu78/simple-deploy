"""Типы deployment target."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class DeploymentTargetRoleEnum(DomainStringEnum):
    """Справочник ролей технических точек размещения."""

    BACKEND = "backend"
    FRONTEND = "frontend"
    DATABASE = "database"
    CACHE = "cache"
    REPORTING = "reporting"
    S3 = "s3"


DEPLOYMENT_TARGET_ROLES = DeploymentTargetRoleEnum.get_values()


def _validate_deployment_target_role(value: str) -> str:
    """Проверяет роль deployment target."""

    if value not in DEPLOYMENT_TARGET_ROLES:
        raise ValueError(
            f"Unknown deployment target role: {value}. Expected one of: {', '.join(DEPLOYMENT_TARGET_ROLES)}"
        )
    return value


DeploymentTargetRole = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_deployment_target_role),
]
"""Роль технической точки размещения."""


__all__ = [
    "DEPLOYMENT_TARGET_ROLES",
    "DeploymentTargetRole",
    "DeploymentTargetRoleEnum",
]
