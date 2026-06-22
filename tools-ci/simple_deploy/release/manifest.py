"""Примитивы переносимого ``release_manifest.json``.

Manifest описывает конкретный собранный релиз: версию, время создания,
исходные backend/frontend репозитории и список артефактов. Он переносится
вместе с директорией релиза и дополняет локальную SQLite-базу, но не заменяет
ее: SQLite хранит операционное состояние контуров, а manifest описывает
содержимое одного артефакта релиза.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from simple_deploy.entities.release import (
    ReleaseArtifactRef,
    ReleaseBundle,
    SourceRepositoryRevision,
    SourceSnapshot,
)
from simple_deploy.types.artifact import ArtifactKindEnum, ArtifactScopeEnum
from simple_deploy.types.trigger import ReleaseTriggerTypeEnum

RELEASE_MANIFEST_NAME = "release_manifest.json"


def _created_at() -> str:
    """Возвращает timestamp создания release manifest."""
    return datetime.now().isoformat(timespec="seconds")


def _repo_revision(repo_id: str, repo: dict[str, str]) -> SourceRepositoryRevision:
    """Создает source revision из текущего manifest repository fragment."""
    return SourceRepositoryRevision(
        repo_id=repo_id,
        ref=str(repo.get("branch", "")),
        commit_sha=str(repo.get("commit_sha", "")),
        origin_id=str(repo.get("source_remote_url") or repo_id),
        metadata=repo,
    )


def release_bundle_from_manifest(
    manifest: dict,
    *,
    build_attempt_id: int = 1,
) -> ReleaseBundle:
    """Преобразует переносимый manifest dict в доменный release bundle."""
    repositories = manifest.get("repositories", {})
    revisions = tuple(
        _repo_revision(repo_id, repo)
        for repo_id, repo in repositories.items()
        if isinstance(repo, dict)
    )
    source_snapshot = SourceSnapshot(
        revisions=revisions,
        resolved_at=str(manifest.get("created_at", "")),
        trigger_type=ReleaseTriggerTypeEnum.UNDEFINED,
    )
    artifacts = tuple(
        ReleaseArtifactRef(
            artifact_id=artifact_id,
            kind=(
                ArtifactKindEnum.DB_DATA
                if artifact_id == "backend_db"
                else ArtifactKindEnum.MANIFEST
            ),
            scope=ArtifactScopeEnum.SHARED,
            metadata=metadata if isinstance(metadata, dict) else {},
        )
        for artifact_id, metadata in manifest.get("artifacts", {}).items()
    )
    return ReleaseBundle(
        build_version=str(manifest.get("build_version", "")),
        source_snapshot=source_snapshot,
        artifacts=artifacts,
        created_at=str(manifest.get("created_at", "")),
        build_attempt_id=build_attempt_id,
    )


def manifest_from_release_bundle(bundle: ReleaseBundle) -> dict:
    """Сериализует доменный release bundle в текущую форму release_manifest.json."""
    repositories = {}
    for revision in bundle.source_snapshot.revisions:
        repo = dict(revision.metadata)
        repo.setdefault("branch", revision.ref)
        repo.setdefault("commit_sha", revision.commit_sha)
        repo.setdefault("source_remote_url", revision.origin_id)
        repositories[revision.repo_id] = repo
    artifacts = {
        artifact.artifact_id: dict(artifact.metadata)
        for artifact in bundle.artifacts
    }
    return {
        "build_version": bundle.build_version,
        "created_at": bundle.created_at,
        "repositories": repositories,
        "artifacts": artifacts,
    }


def build_release_manifest(
    build_version: str,
    backend_repo: dict[str, str],
    frontend_repo: dict[str, str],
    backend_artifacts: dict[str, object] | None = None,
) -> dict:
    """Формирует структуру ``release_manifest.json`` в памяти.

    Функция принимает уже собранные метаданные backend/frontend репозиториев и
    backend-артефактов. Она не читает Git и не пишет файл: вызывающий код
    отвечает за получение метаданных и последующую запись manifest в директорию
    релиза.
    """
    created_at = _created_at()
    source_snapshot = SourceSnapshot(
        revisions=(
            _repo_revision("backend", backend_repo),
            _repo_revision("frontend", frontend_repo),
        ),
        resolved_at=created_at,
        trigger_type=ReleaseTriggerTypeEnum.UNDEFINED,
    )
    bundle = ReleaseBundle(
        build_version=build_version,
        source_snapshot=source_snapshot,
        artifacts=(
            ReleaseArtifactRef(
                artifact_id="backend_db",
                kind=ArtifactKindEnum.DB_DATA,
                scope=ArtifactScopeEnum.SHARED,
                metadata=backend_artifacts or {},
            ),
        ),
        created_at=created_at,
        build_attempt_id=1,
    )
    return manifest_from_release_bundle(bundle)


def write_release_manifest_file(release_dir: Path, manifest: dict) -> Path:
    """Записывает manifest в директорию релиза.

    Функция создает директорию релиза при необходимости и сохраняет JSON в
    ``release_manifest.json`` с UTF-8 и стабильным переносом строки в конце.
    Она не обновляет SQLite-состояние: фиксация успешной сборки выполняется
    отдельным вызовом ``registry.commands``.
    """
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def load_release_manifest(release_dir: Path) -> dict | None:
    """Читает manifest из директории релиза, если он существует.

    Возвращает ``None`` при отсутствии файла, чтобы вызывающий код мог отличить
    "релиз без manifest" от поврежденного JSON. Ошибки чтения или парсинга не
    подавляются, потому что такой manifest нельзя считать надежным источником
    метаданных релиза.
    """
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    if not manifest_path.exists():
        return None
    with manifest_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def release_backend_commit(release_dir: Path) -> str:
    """
    Возвращает backend commit из manifest релиза.

    Функция используется командами mark/deploy для записи результата в
    registry. Она только читает переносимый manifest и не двигает baseline
    сама; изменение baseline выполняет ``registry.commands`` после успешного
    применения релиза.

    """
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    manifest = load_release_manifest(release_dir)
    if not manifest:
        raise RuntimeError(f"Release manifest not found: {manifest_path}")
    commit = str(
        manifest.get("repositories", {})
        .get("backend", {})
        .get("commit_sha", "")
    ).strip()
    if not commit:
        raise RuntimeError(
            "Backend commit is missing in release manifest: "
            f"{manifest_path}"
        )
    return commit


def find_previous_release_manifest(
    release_dir: Path,
) -> tuple[Path, dict] | None:
    """Ищет предыдущий релиз с manifest рядом с текущей директорией релиза.

    Поиск идет по соседним директориям в release root и выбирает самый свежий
    кандидат по времени модификации. Функция best-effort: если предыдущий
    manifest отсутствует, она возвращает ``None`` и оставляет вызывающему коду
    право показать changelog как недоступный.
    """
    release_root = release_dir.parent
    if not release_root.exists():
        return None
    candidates = [
        path
        for path in release_root.iterdir()
        if path.is_dir()
        and path.resolve() != release_dir.resolve()
        and (path / RELEASE_MANIFEST_NAME).exists()
    ]
    for candidate in sorted(
        candidates, key=lambda path: path.stat().st_mtime, reverse=True
    ):
        manifest = load_release_manifest(candidate)
        if manifest:
            return candidate, manifest
    return None


__all__ = [
    "RELEASE_MANIFEST_NAME",
    "build_release_manifest",
    "find_previous_release_manifest",
    "manifest_from_release_bundle",
    "load_release_manifest",
    "release_bundle_from_manifest",
    "release_backend_commit",
    "write_release_manifest_file",
]
