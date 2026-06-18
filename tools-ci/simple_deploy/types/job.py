"""Типы локальных долгих операций."""

from __future__ import annotations

from simple_deploy.types._enum import DomainStringEnum


class JobKindEnum(DomainStringEnum):
    """Справочник видов локальных долгих операций."""

    DRY_RUN = "dry_run"
    BUILD = "build"
    DEPLOY = "deploy"
    PIPELINE = "pipeline"
    SET_BASELINE = "set_baseline"
    MARK_APPLIED = "mark_applied"
    MARK_FAILED = "mark_failed"


JOB_KINDS = JobKindEnum.get_values()


__all__ = [
    "JOB_KINDS",
    "JobKindEnum",
]
