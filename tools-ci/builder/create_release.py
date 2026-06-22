from pathlib import Path
import subprocess
import sys


TOOLS_CI_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_CI_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI_ROOT))

from src.infra import (
    get_new_branch_name,
    get_new_build_version,
)
from simple_deploy.registry.commands import (
    finish_build_attempt,
    record_release_bundle_aggregate,
    start_build_attempt,
)
from src.utils import get_required_env
from simple_deploy.release.manifest import (
    build_release_manifest,
    release_bundle_from_manifest,
    write_release_manifest_file,
)

from src.build_backend import build_backend
from src.build_frontend import build_frontend


def git_output(repo_path: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def repo_manifest(repo_path: str) -> dict[str, str]:
    commit_sha = git_output(repo_path, "rev-parse", "HEAD")
    return {
        "source_repo_path": repo_path,
        "source_remote_url": git_output(repo_path, "remote", "get-url", "origin"),
        "branch": git_output(repo_path, "branch", "--show-current"),
        "commit_sha": commit_sha,
        "commit_short_sha": commit_sha[:12],
    }


def write_release_manifest(
    build_version: str,
    backend_artifacts: dict[str, object] | None = None,
    build_attempt_id: int = 1,
) -> dict:
    release_root = Path(get_required_env("RELEASE_ROOT_WINDOWS"))
    release_dir = release_root / build_version
    manifest = build_release_manifest(
        build_version=build_version,
        backend_repo=repo_manifest(get_required_env("BACKEND_SOURCE_REPO_PATH")),
        frontend_repo=repo_manifest(get_required_env("FRONTEND_SOURCE_REPO_PATH")),
        backend_artifacts=backend_artifacts,
    )
    manifest_path = write_release_manifest_file(release_dir, manifest)
    print(f"Release manifest created: {manifest_path}", flush=True)
    record_release_bundle_aggregate(
        release_bundle_from_manifest(
            manifest,
            build_attempt_id=build_attempt_id,
        )
    )
    return manifest


def safe_repo_commit(env_name: str) -> str:
    """Best-effort чтение commit-а для metadata build attempt."""
    try:
        return git_output(get_required_env(env_name), "rev-parse", "HEAD")
    except Exception:
        return ""


def record_build_failure(attempt_id: int, build_version: str, error: BaseException) -> None:
    """Best-effort запись failed build attempt без затирания исходной ошибки."""
    try:
        finish_build_attempt(
            attempt_id=attempt_id,
            status="failed",
            build_version=build_version,
            backend_commit=safe_repo_commit("BACKEND_SOURCE_REPO_PATH"),
            frontend_commit=safe_repo_commit("FRONTEND_SOURCE_REPO_PATH"),
            error=str(error),
        )
    except Exception as record_error:
        print(
            f"WARN failed to record failed build attempt: build_version={build_version} error={record_error}",
            flush=True,
        )


def main() -> int:
    # TODO добавить параметризацию веток репозиториев, на основе которых происходит сборка.
    # TODO добавить last commits для репозиториев, на основе которых была проведена сборка.
    # TODO добавить сохранение логов сборщика в файл.
    # TODO добавить возможность ручного ввода версии релиза, помимо автоматической,
    # через .env файл.
    build_version = get_new_build_version()
    branch_name = get_new_branch_name(build_version=build_version)

    build_attempt = start_build_attempt(
        build_version=build_version,
        backend_commit=safe_repo_commit("BACKEND_SOURCE_REPO_PATH"),
        frontend_commit=safe_repo_commit("FRONTEND_SOURCE_REPO_PATH"),
    )

    try:
        backend_artifacts = build_backend(
            build_version=build_version,
            branch_name=branch_name,
        )

        build_frontend(
            build_version=build_version,
            branch_name=branch_name,
        )

        manifest = write_release_manifest(
            build_version,
            backend_artifacts=backend_artifacts,
            build_attempt_id=build_attempt.attempt_id,
        )
        backend_repo = manifest["repositories"]["backend"]
        frontend_repo = manifest["repositories"]["frontend"]
        finish_build_attempt(
            attempt_id=build_attempt.attempt_id,
            status="success",
            build_version=build_version,
            backend_commit=backend_repo["commit_sha"],
            frontend_commit=frontend_repo["commit_sha"],
        )
    except (Exception, SystemExit) as exc:
        record_build_failure(build_attempt.attempt_id, build_version, exc)
        raise

    # TODO собирать summary и roles нужно на этапе пре-пушей.


    # ERROR удаляется архивес из финального пуша, что логично.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
