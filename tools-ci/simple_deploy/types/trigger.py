"""Типы технических триггеров release intent."""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class ReleaseTriggerTypeEnum(DomainStringEnum):
    """Справочник технических источников создания release intent."""

    UNDEFINED = "undefined"
    MANUAL = "manual"
    BACKEND_BRANCH_PUSH = "backend_branch_push"
    BACKEND_RELEASE_BRANCH_PUSH = "backend_release_branch_push"
    SCHEDULED = "scheduled"


RELEASE_TRIGGER_TYPES = ReleaseTriggerTypeEnum.get_values()


__all__ = [
    "RELEASE_TRIGGER_TYPES",
    "ReleaseTriggerTypeEnum",
]
