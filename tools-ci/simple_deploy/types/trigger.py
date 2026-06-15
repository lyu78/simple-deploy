"""Типы технических триггеров release intent."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class ReleaseTriggerTypeEnum(DomainStringEnum):
    """Справочник технических источников создания release intent."""

    MANUAL = "manual"
    BACKEND_BRANCH_PUSH = "backend_branch_push"
    BACKEND_RELEASE_BRANCH_PUSH = "backend_release_branch_push"
    SCHEDULED = "scheduled"


RELEASE_TRIGGER_TYPES = ReleaseTriggerTypeEnum.get_values()


def _validate_release_trigger_type(value: str) -> str:
    """Проверяет тип технического триггера релиза."""

    if value not in RELEASE_TRIGGER_TYPES:
        raise ValueError(
            f"Unknown release trigger type: {value}. Expected one of: {', '.join(RELEASE_TRIGGER_TYPES)}"
        )
    return value


ReleaseTriggerType = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_release_trigger_type),
]
"""Технический источник создания release intent."""


__all__ = [
    "RELEASE_TRIGGER_TYPES",
    "ReleaseTriggerType",
    "ReleaseTriggerTypeEnum",
]
