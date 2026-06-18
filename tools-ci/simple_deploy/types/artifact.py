"""Типы классификации release artifacts."""

from __future__ import annotations

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


__all__ = [
    "ARTIFACT_KINDS",
    "ARTIFACT_SCOPES",
    "ArtifactKindEnum",
    "ArtifactScopeEnum",
]
