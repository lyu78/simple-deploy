"""Типы классификации release artifacts."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from simple_deploy.types._enum import DomainStringEnum


class ArtifactKindEnum(DomainStringEnum):
    """Справочник типов файлов внутри release bundle."""

    BACKEND = "backend"
    FRONTEND = "frontend"
    DB_SCHEMA = "db_schema"
    DB_DATA = "db_data"
    MAINTENANCE_STUB = "maintenance_stub"
    MANIFEST = "manifest"


class ArtifactScopeEnum(DomainStringEnum):
    """Справочник областей применимости артефактов release bundle."""

    SHARED = "shared"
    CONTOUR_SPECIFIC = "contour_specific"
    TARGET_SPECIFIC = "target_specific"


ARTIFACT_KINDS = ArtifactKindEnum.get_values()
ARTIFACT_SCOPES = ArtifactScopeEnum.get_values()


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
    "ArtifactKindEnum",
    "ArtifactScope",
    "ArtifactScopeEnum",
]
