"""Release manifest primitives."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path


RELEASE_MANIFEST_NAME = "release_manifest.json"


def build_release_manifest(
    build_version: str,
    backend_repo: dict[str, str],
    frontend_repo: dict[str, str],
    backend_artifacts: dict[str, object] | None = None,
) -> dict:
    return {
        "build_version": build_version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "repositories": {
            "backend": backend_repo,
            "frontend": frontend_repo,
        },
        "artifacts": {
            "backend_db": backend_artifacts or {},
        },
    }


def write_release_manifest_file(release_dir: Path, manifest: dict) -> Path:
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def load_release_manifest(release_dir: Path) -> dict | None:
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def release_backend_commit(release_dir: Path) -> str:
    """Читает backend commit из ``release_manifest.json`` релиза."""
    manifest = load_release_manifest(release_dir)
    if not manifest:
        raise RuntimeError(f"Release manifest not found: {release_dir / RELEASE_MANIFEST_NAME}")
    commit = str(manifest.get("repositories", {}).get("backend", {}).get("commit_sha", "")).strip()
    if not commit:
        raise RuntimeError(f"Backend commit is missing in release manifest: {release_dir / RELEASE_MANIFEST_NAME}")
    return commit


def find_previous_release_manifest(release_dir: Path) -> tuple[Path, dict] | None:
    release_root = release_dir.parent
    if not release_root.exists():
        return None
    candidates = [
        path
        for path in release_root.iterdir()
        if path.is_dir() and path.resolve() != release_dir.resolve() and (path / RELEASE_MANIFEST_NAME).exists()
    ]
    for candidate in sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True):
        manifest = load_release_manifest(candidate)
        if manifest:
            return candidate, manifest
    return None


__all__ = [
    "RELEASE_MANIFEST_NAME",
    "build_release_manifest",
    "find_previous_release_manifest",
    "load_release_manifest",
    "release_backend_commit",
    "write_release_manifest_file",
]
