"""Release catalog helpers for operator-facing build selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from simple_deploy.registry.queries import (
    bounded_limit,
    release_bundle_read_model_from_state,
    release_read_models_from_state,
)
from simple_deploy.release.manifest import (
    load_release_manifest,
    release_backend_commit,
)
from simple_deploy.types.status import BuildAttemptStatusEnum


@dataclass(frozen=True)
class BuildOption:
    """Selectable release build with the commit metadata operators need."""

    build_version: str
    backend_commit: str
    frontend_commit: str = ""
    created_at: str = ""
    build_status: str = "success"
    source: str = "registry"


@dataclass(frozen=True)
class ReleaseCommitReference:
    """Resolved commit metadata for a build or bootstrap baseline."""

    build_version: str
    backend_commit: str
    frontend_commit: str = ""
    release_dir: Path | None = None
    source: str = "registry"


def _manifest_frontend_commit(release_dir: Path) -> str:
    manifest = load_release_manifest(release_dir)
    if not manifest:
        return ""
    return str(
        manifest.get("repositories", {})
        .get("frontend", {})
        .get("commit_sha", "")
    ).strip()


def _release_status_value(value: object) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _successful_attempt_created_at(release) -> str:
    for attempt in release.build_attempts:
        if attempt.status == BuildAttemptStatusEnum.SUCCESS:
            return attempt.finished_at
    return ""


def _release_read_model(build_version: str):
    for release in release_read_models_from_state(limit=200):
        if release.build_version == build_version:
            return release
    return None


def list_build_options(limit: int = 100) -> list[BuildOption]:
    """Returns successful builds that can be selected by operators."""
    releases = release_read_models_from_state(limit=bounded_limit(limit))
    options: list[BuildOption] = []
    for release in releases:
        if (
            release.build_status != BuildAttemptStatusEnum.SUCCESS
            or not release.backend_commit
        ):
            continue
        source = "registry" if release.bundle is not None else "build_attempt"
        created_at = (
            release.bundle.created_at
            if release.bundle is not None
            else _successful_attempt_created_at(release)
        )
        options.append(
            BuildOption(
                build_version=release.build_version,
                backend_commit=release.backend_commit,
                frontend_commit=release.frontend_commit,
                created_at=created_at,
                build_status=_release_status_value(release.build_status),
                source=source,
            )
        )
    return options


def resolve_release_commit(
    build_version: str,
    *,
    release_dir: Path | None = None,
    backend_commit: str = "",
) -> ReleaseCommitReference:
    """Resolves target backend commit for a release build.

    Registry is preferred because it is the local source of truth. Manifest is
    the fallback for portable TEST/PROD package flows where the SQLite row may
    not yet exist locally.
    """
    manual_commit = backend_commit.strip()
    if manual_commit:
        return ReleaseCommitReference(
            build_version=build_version or "manual-baseline",
            backend_commit=manual_commit,
            release_dir=release_dir,
            source="manual",
        )

    normalized_build_version = build_version.strip()
    if not normalized_build_version:
        raise RuntimeError("Build version is required to resolve release commit")

    bundle = release_bundle_read_model_from_state(normalized_build_version)
    if bundle is not None and bundle.backend_commit:
        return ReleaseCommitReference(
            build_version=bundle.build_version,
            backend_commit=bundle.backend_commit,
            frontend_commit=bundle.frontend_commit,
            release_dir=release_dir,
            source="registry",
        )

    release = _release_read_model(normalized_build_version)
    if (
        release is not None
        and release.build_status == BuildAttemptStatusEnum.SUCCESS
        and release.backend_commit
    ):
        return ReleaseCommitReference(
            build_version=release.build_version,
            backend_commit=release.backend_commit,
            frontend_commit=release.frontend_commit,
            release_dir=release_dir,
            source="build_attempt",
        )

    if release_dir is not None:
        return ReleaseCommitReference(
            build_version=normalized_build_version,
            backend_commit=release_backend_commit(release_dir),
            frontend_commit=_manifest_frontend_commit(release_dir),
            release_dir=release_dir,
            source="manifest",
        )

    raise RuntimeError(
        "Release commit was not found in registry: "
        f"build_version={normalized_build_version}"
    )


def initial_schema_baseline_reference(
    runtime: Mapping[str, object],
    contour: str,
) -> ReleaseCommitReference:
    """Reads bootstrap baseline for a contour from runtime config."""
    baselines = runtime.get("initial_schema_baselines", {})
    if not isinstance(baselines, Mapping):
        raise RuntimeError(
            "Runtime config initial_schema_baselines must be an object"
        )
    baseline = baselines.get(contour)
    if not isinstance(baseline, Mapping):
        raise RuntimeError(
            "Initial schema baseline is not configured for contour: "
            f"{contour}"
        )
    build_version = str(baseline.get("build_version", "")).strip()
    backend_commit = str(baseline.get("backend_commit", "")).strip()
    if not build_version or not backend_commit:
        raise RuntimeError(
            "Initial schema baseline requires build_version and backend_commit "
            f"for contour: {contour}"
        )
    return ReleaseCommitReference(
        build_version=build_version,
        backend_commit=backend_commit,
        source="initial_schema_baselines",
    )


__all__ = [
    "BuildOption",
    "ReleaseCommitReference",
    "initial_schema_baseline_reference",
    "list_build_options",
    "resolve_release_commit",
]
