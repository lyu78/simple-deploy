"""Типы классификации release artifacts."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints


ARTIFACT_KINDS = ("backend", "frontend", "db_schema", "db_data", "maintenance_stub", "manifest")
ARTIFACT_SCOPES = ("shared", "contour_specific", "target_specific")


def _validate_artifact_kind(value: str) -> str:
    """Проверяет тип артефакта release bundle."""

    if value not in ARTIFACT_KINDS:
        raise ValueError(f"Unknown artifact kind: {value}. Expected one of: {', '.join(ARTIFACT_KINDS)}")
    return value


def _validate_artifact_scope(value: str) -> str:
    """Проверяет scope артефакта release bundle."""

    if value not in ARTIFACT_SCOPES:
        raise ValueError(f"Unknown artifact scope: {value}. Expected one of: {', '.join(ARTIFACT_SCOPES)}")
    return value


ArtifactKind = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_artifact_kind),
]
"""Тип файла внутри release bundle."""


ArtifactScope = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True),
    AfterValidator(_validate_artifact_scope),
]
"""Область применимости артефакта release bundle."""


__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_SCOPES",
    "ArtifactKind",
    "ArtifactScope",
]
