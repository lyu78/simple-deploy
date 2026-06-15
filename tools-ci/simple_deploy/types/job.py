"""Типы локальных долгих операций."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

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


def _validate_job_kind(value: str) -> str:
    """Проверяет вид локальной долгой операции."""

    if value not in JOB_KINDS:
        raise ValueError(
            f"Unknown job kind: {value}. Expected one of: {', '.join(JOB_KINDS)}"
        )
    return value


JobKind = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_job_kind),
]
"""Вид локальной долгой операции."""


__all__ = [
    "JOB_KINDS",
    "JobKind",
    "JobKindEnum",
]
