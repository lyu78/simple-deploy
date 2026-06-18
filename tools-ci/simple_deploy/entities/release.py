"""Чистые entities релиза без привязки к SQLite/API/SSH."""

from __future__ import annotations

from dataclasses import dataclass, replace

from simple_deploy.types.artifact import ArtifactKindEnum, ArtifactScopeEnum
from simple_deploy.types.contour import ContourCodeEnum
from simple_deploy.types.fields import (
    ArtifactIdString,
    CreatedAtString,
    ResolvedAtString,
    SourceOriginIdString,
    SourceRefString,
    UpdatedAtString,
)
from simple_deploy.types.release import BuildVersionString
from simple_deploy.types.source import CommitShaString, RepoId
from simple_deploy.types.status import DeploymentAttemptStatusEnum
from simple_deploy.types.trigger import ReleaseTriggerTypeEnum


@dataclass(frozen=True)
class SourceRepositoryRevision:
    """
    Фактическая revision одного source repository в source snapshot.

    ``repo_id`` - строковый код логического репозитория из topology
    ``source_repositories``. Это не числовой id и не путь к репозиторию:
    ожидаются значения вроде ``backend`` или ``frontend-app``.
    """

    repo_id: RepoId
    ref: SourceRefString
    commit_sha: CommitShaString
    origin_id: SourceOriginIdString


@dataclass(frozen=True)
class SourceSnapshot:
    """
    Immutable снимок source repositories.

    Из него собирается release.
    """

    revisions: tuple[SourceRepositoryRevision, ...]
    resolved_at: ResolvedAtString
    trigger_type: ReleaseTriggerTypeEnum = ReleaseTriggerTypeEnum.UNDEFINED

    def __post_init__(self) -> None:
        if not self.revisions:
            raise ValueError(
                "SourceSnapshot must contain at least one repository revision"
            )
        repo_ids = [revision.repo_id for revision in self.revisions]
        if len(repo_ids) != len(set(repo_ids)):
            raise ValueError(
                "SourceSnapshot repository revisions must have "
                "unique repo_id values"
            )


@dataclass(frozen=True)
class ReleaseArtifactRef:
    """Ссылка на artifact внутри release bundle manifest/read model."""

    artifact_id: ArtifactIdString
    kind: ArtifactKindEnum
    scope: ArtifactScopeEnum


@dataclass(frozen=True)
class ReleaseBundle:
    """Материализованный результат успешной сборки release bundle."""

    build_version: BuildVersionString
    source_snapshot: SourceSnapshot
    artifacts: tuple[ReleaseArtifactRef, ...]
    created_at: CreatedAtString
    build_attempt_id: int

    def __post_init__(self) -> None:
        if self.build_attempt_id <= 0:
            raise ValueError("ReleaseBundle build_attempt_id must be positive")


@dataclass(frozen=True)
class ReleasePlacement:
    """Состояние размещения релиза на одном контуре."""

    build_version: BuildVersionString
    contour: ContourCodeEnum
    status: DeploymentAttemptStatusEnum
    updated_at: UpdatedAtString
    deployment_attempt_id: int | None = None


@dataclass(frozen=True)
class Release:
    """Доменная сущность релиза и его связей с bundle/placements."""

    build_version: BuildVersionString
    source_snapshot: SourceSnapshot | None = None
    successful_bundle: ReleaseBundle | None = None
    placements: tuple[ReleasePlacement, ...] = ()

    def with_successful_bundle(self, bundle: ReleaseBundle) -> Release:
        """Возвращает release с успешным bundle-ом."""
        if bundle.build_version != self.build_version:
            raise ValueError(
                "ReleaseBundle build_version must match Release build_version"
            )
        if (
            self.source_snapshot is not None
            and bundle.source_snapshot != self.source_snapshot
        ):
            raise ValueError(
                "ReleaseBundle source_snapshot must match "
                "Release source_snapshot"
            )
        if (
            self.successful_bundle is not None
            and self.successful_bundle != bundle
        ):
            raise ValueError("Release already has a successful bundle")
        source_snapshot = self.source_snapshot or bundle.source_snapshot
        return replace(
            self, source_snapshot=source_snapshot, successful_bundle=bundle
        )

    def with_placement(self, placement: ReleasePlacement) -> Release:
        """Возвращает release с обновленным placement."""
        if placement.build_version != self.build_version:
            raise ValueError(
                "ReleasePlacement build_version must match "
                "Release build_version"
            )
        placements = tuple(
            existing
            for existing in self.placements
            if existing.contour != placement.contour
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
