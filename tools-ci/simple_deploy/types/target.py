"""Типы deployment target."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints


DEPLOYMENT_TARGET_ROLES = ("backend", "frontend", "database", "cache", "reporting", "s3")


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
]
