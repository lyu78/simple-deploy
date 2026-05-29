from datetime import datetime
import json
from pathlib import Path
import subprocess
from contextlib import closing

from src.infra import (
    get_new_branch_name,
    get_new_build_version,
)
from src.release_state import connect_state_db, record_release
from src.utils import get_required_env

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
    backend_artifacts: dict[str, str] | None = None,
) -> None:
    release_root = Path(get_required_env("RELEASE_ROOT_WINDOWS"))
    release_dir = release_root / build_version
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "build_version": build_version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "repositories": {
            "backend": repo_manifest(get_required_env("BACKEND_SOURCE_REPO_PATH")),
            "frontend": repo_manifest(get_required_env("FRONTEND_SOURCE_REPO_PATH")),
        },
        "artifacts": {
            "backend_db": backend_artifacts or {},
        },
    }
    manifest_path = release_dir / "release_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Release manifest created: {manifest_path}", flush=True)
    backend_repo = manifest["repositories"]["backend"]
    frontend_repo = manifest["repositories"]["frontend"]
    with closing(connect_state_db()) as connection:
        record_release(
            connection,
            build_version=build_version,
            backend_commit=backend_repo["commit_sha"],
            frontend_commit=frontend_repo["commit_sha"],
            artifacts=manifest["artifacts"],
        )


if __name__ == "__main__":
    # TODO добавить параметризацию веток репозиториев, на основе которых происходит сборка.
    # TODO добавить last commits для репозиториев, на основе которых была проведена сборка.
    # TODO добавить сохранение логов сборщика в файл.
    # TODO добавить возможность ручного ввода версии релиза, помимо автоматической,
    # через .env файл.
    build_version = get_new_build_version()
    branch_name = get_new_branch_name(build_version=build_version)

    backend_artifacts = build_backend(
        build_version=build_version,
        branch_name=branch_name,
    )

    build_frontend(
        build_version=build_version,
        branch_name=branch_name,
    )

    write_release_manifest(build_version, backend_artifacts=backend_artifacts)

    # TODO собирать summary и roles нужно на этапе пре-пушей.


    # ERROR удаляется архивес из финального пуша, что логично.
