"""Чистые entities релиза без привязки к SQLite/API/SSH."""

from __future__ import annotations

from dataclasses import dataclass, replace

from simple_deploy.types.artifact import ArtifactKind, ArtifactScope
from simple_deploy.types.contour import ContourCode
from simple_deploy.types.release import BuildVersionString
from simple_deploy.types.source import CommitShaString, RepoId
from simple_deploy.types.trigger import ReleaseTriggerType


@dataclass(frozen=True)
class SourceRepositoryRevision:
    """Фактическая revision одного source repository в source snapshot."""

    repo_id: RepoId
    ref: str
    commit_sha: CommitShaString
    origin_id: str


@dataclass(frozen=True)
class SourceSnapshot:
    """Immutable снимок source repositories, из которых собирается release."""

    revisions: tuple[SourceRepositoryRevision, ...]
    resolved_at: str
    trigger_type: ReleaseTriggerType | None = None

    def __post_init__(self) -> None:
        if not self.revisions:
            raise ValueError("SourceSnapshot must contain at least one repository revision")
        repo_ids = [revision.repo_id for revision in self.revisions]
        if len(repo_ids) != len(set(repo_ids)):
            raise ValueError("SourceSnapshot repository revisions must have unique repo_id values")


@dataclass(frozen=True)
class ReleaseArtifactRef:
    """Ссылка на artifact внутри release bundle manifest/read model."""

    artifact_id: str
    kind: ArtifactKind
    scope: ArtifactScope


@dataclass(frozen=True)
class ReleaseBundle:
    """Материализованный immutable результат успешной сборки release bundle."""

    build_version: BuildVersionString
    source_snapshot: SourceSnapshot
    artifacts: tuple[ReleaseArtifactRef, ...]
    created_at: str
    build_attempt_id: int

    def __post_init__(self) -> None:
        if self.build_attempt_id <= 0:
            raise ValueError("ReleaseBundle build_attempt_id must be positive")


@dataclass(frozen=True)
class ReleasePlacement:
    """Состояние размещения релиза на одном контуре."""

    build_version: BuildVersionString
    contour: ContourCode
    status: str
    updated_at: str
    deployment_attempt_id: int | None = None


@dataclass(frozen=True)
class Release:
    """Доменная сущность релиза и его связей с bundle/placements."""

    build_version: BuildVersionString
    source_snapshot: SourceSnapshot | None = None
    successful_bundle: ReleaseBundle | None = None
    placements: tuple[ReleasePlacement, ...] = ()

    def with_successful_bundle(self, bundle: ReleaseBundle) -> Release:
        """Возвращает release с единственным успешным bundle-ом."""

        if bundle.build_version != self.build_version:
            raise ValueError("ReleaseBundle build_version must match Release build_version")
        if self.source_snapshot is not None and bundle.source_snapshot != self.source_snapshot:
            raise ValueError("ReleaseBundle source_snapshot must match Release source_snapshot")
        if self.successful_bundle is not None and self.successful_bundle != bundle:
            raise ValueError("Release already has a successful bundle")
        source_snapshot = self.source_snapshot or bundle.source_snapshot
        return replace(self, source_snapshot=source_snapshot, successful_bundle=bundle)

    def with_placement(self, placement: ReleasePlacement) -> Release:
        """Возвращает release с обновленным placement для контура."""

        if placement.build_version != self.build_version:
            raise ValueError("ReleasePlacement build_version must match Release build_version")
        placements = tuple(
            existing for existing in self.placements if existing.contour != placement.contour
        )
        return replace(self, placements=(*placements, placement))


__all__ = [
    "Release",
    "ReleaseArtifactRef",
    "ReleaseBundle",
    "ReleasePlacement",
    "SourceRepositoryRevision",
    "SourceSnapshot",
]
