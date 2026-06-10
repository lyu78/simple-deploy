"""Release artifact primitives and local artifact resolution."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path

from simple_deploy.release.state import validate_contour


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAINTENANCE_STUB_ARCHIVE = "tools-ci/maintenance_stub/maintenance_stub.tar.gz"


@dataclass
class Artifact:
    name: str
    local_path: Path
    remote_archive: str
    extract_path: str


@dataclass
class DbSqlArtifact:
    name: str
    local_path: Path
    remote_archive: str
    remote_extract_path: str
    entrypoint_dir: str
    entrypoint_pattern: str


def require_value(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная: {name}")
    return value


def runtime_local_path(path_value: object) -> Path:
    path = Path(str(path_value)).expanduser()
    if path.is_absolute():
        return path
    return ROOT / path


def resolve_artifacts(env: dict[str, str], build_version: str, release_dir: Path) -> list[Artifact]:
    print(f"RESOLVE artifacts in: {release_dir}", flush=True)
    if not release_dir.is_dir():
        raise RuntimeError(f"Директория релиза не существует: {release_dir}")

    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    patterns = [
        (
            "backend",
            f"backend_r_{build_version}*.tar.gz",
            f"{remote_dir}/backend.tar.gz",
            require_value(env, "BACKEND_RELEASE_PATH"),
        ),
        (
            "frontend",
            f"frontend_r_{build_version}-bf_dev-env_{require_value(env, 'DEV_DOMAIN')}.tar.gz",
            f"{remote_dir}/frontend.tar.gz",
            require_value(env, "FRONTEND_RELEASE_PATH"),
        ),
    ]

    artifacts: list[Artifact] = []
    for name, pattern, remote_archive, extract_path in patterns:
        matches = [path for path in release_dir.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern)]
        if not matches:
            raise RuntimeError(f"В {release_dir} не найден архив по шаблону {pattern}")
        newest = max(matches, key=lambda path: path.stat().st_mtime)
        print(f"RESOLVE artifact {name}: {newest.name} -> {extract_path}", flush=True)
        artifacts.append(Artifact(name, newest, remote_archive, extract_path))
    return artifacts


def resolve_db_schema_artifact(
    env: dict[str, str],
    build_version: str,
    release_dir: Path,
    contour: str = "dev",
) -> DbSqlArtifact:
    """Находит schema SQL archive для выбранного контура в директории релиза."""
    contour = validate_contour(contour)
    print(f"RESOLVE DB schema artifact in: {release_dir}", flush=True)
    if not release_dir.is_dir():
        raise RuntimeError(f"Директория релиза не существует: {release_dir}")

    pattern = f"db_schema_{contour}_r_{build_version}-c_*.tar.gz"
    matches = [path for path in release_dir.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern)]
    if not matches:
        raise RuntimeError(f"В {release_dir} не найден DB schema архив по шаблону {pattern}")

    newest = max(matches, key=lambda path: path.stat().st_mtime)
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    artifact = DbSqlArtifact(
        name=f"db_schema_{contour}",
        local_path=newest,
        remote_archive=f"{remote_dir}/db_schema_{contour}.tar.gz",
        remote_extract_path=f"{remote_dir}/db_schema_{contour}",
        entrypoint_dir=".",
        entrypoint_pattern=f"summary_sql_{contour}_*.sql",
    )
    print(
        f"RESOLVE DB schema artifact: {artifact.local_path.name} -> {artifact.remote_extract_path}",
        flush=True,
    )
    return artifact


def resolve_db_data_artifact(
    env: dict[str, str],
    build_version: str,
    release_dir: Path,
    kind: str,
) -> DbSqlArtifact:
    specs = {
        "insert": (
            "db_insert",
            f"db_insert_r_{build_version}-c_*.tar.gz",
            "db_insert.tar.gz",
            "db_insert",
            "run_all_insert_*.sql",
        ),
        "update_parallel": (
            "db_update_parallel",
            f"db_update_parallel_r_{build_version}-c_*.tar.gz",
            "db_update_parallel.tar.gz",
            "db_update_parallel",
            "run_all_update_parallel_*.sh",
        ),
    }
    if kind not in specs:
        raise RuntimeError(f"Unsupported DB data artifact kind: {kind}")
    if not release_dir.is_dir():
        raise RuntimeError(f"Release directory does not exist: {release_dir}")

    name, pattern, remote_archive_name, remote_extract_name, entrypoint_pattern = specs[kind]
    print(f"RESOLVE DB data artifact {name} in: {release_dir}", flush=True)
    matches = [path for path in release_dir.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern)]
    if not matches:
        raise RuntimeError(f"DB data artifact not found in {release_dir} by pattern {pattern}")

    newest = max(matches, key=lambda path: path.stat().st_mtime)
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    artifact = DbSqlArtifact(
        name=name,
        local_path=newest,
        remote_archive=f"{remote_dir}/{remote_archive_name}",
        remote_extract_path=f"{remote_dir}/{remote_extract_name}",
        entrypoint_dir=".",
        entrypoint_pattern=entrypoint_pattern,
    )
    print(
        f"RESOLVE DB data artifact {name}: {artifact.local_path.name} -> {artifact.remote_extract_path}",
        flush=True,
    )
    return artifact


def resolve_maintenance_stub_artifact(env: dict[str, str], runtime: dict, build_version: str) -> Artifact:
    local_path = runtime_local_path(runtime.get("maintenance_stub_archive_path", DEFAULT_MAINTENANCE_STUB_ARCHIVE))
    if not local_path.is_file():
        raise RuntimeError(f"Maintenance stub archive not found: {local_path}")
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    artifact = Artifact(
        name="maintenance_stub",
        local_path=local_path,
        remote_archive=f"{remote_dir}/maintenance_stub.tar.gz",
        extract_path=require_value(env, "FRONTEND_RELEASE_PATH"),
    )
    print(f"RESOLVE maintenance stub: {artifact.local_path} -> {artifact.extract_path}", flush=True)
    return artifact


def require_artifact(artifacts: list[Artifact], name: str) -> Artifact:
    for artifact in artifacts:
        if artifact.name == name:
            return artifact
    raise RuntimeError(f"Resolved app artifact is missing: {name}")


__all__ = [
    "DEFAULT_MAINTENANCE_STUB_ARCHIVE",
    "Artifact",
    "DbSqlArtifact",
    "require_artifact",
    "require_value",
    "resolve_artifacts",
    "resolve_db_data_artifact",
    "resolve_db_schema_artifact",
    "resolve_maintenance_stub_artifact",
    "runtime_local_path",
]
