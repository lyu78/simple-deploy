"""Backend source sync and release artifact build."""

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
from typing import Callable

from src.files import (
    check_repo,
    clear_directory_contents,
    copy_directory_contents,
)
from src.infra import (
    get_new_branch_name,
    get_new_build_version,
    git_add_commit_push,
    git_checkout_dev,
    git_checkout_new_branch,
    git_pull,
)
from src.utils import (
    add_file_to_tar,
    get_required_env,
    git_output,
    one_match,
)

logging.basicConfig(level=logging.INFO)

INCLUDE_RE = re.compile(r"^\s*\\i\s+['\"]?([^'\"\s]+)['\"]?")
DATABASE_SCRIPTS_PREFIX = Path("docs/database/scripts")
BUILD_SCRIPTS_DIR_NAME = "build_scripts"
SCHEMA_SUMMARY_SQL_ENABLED = False
DEFAULT_BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH = "requirements.txt"
PIP_TRUSTED_HOSTS = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
)


def _log_build_step(message: str) -> None:
    print(f"[backend-db-artifacts] {message}", flush=True)


def _to_git_bash_path(path: Path) -> str:
    resolved = path.resolve()
    text = resolved.as_posix()
    if len(text) >= 3 and text[1:3] == ":/":
        return f"/{text[0].lower()}{text[2:]}"
    return text


def _run_git_bash(command: str, cwd: Path) -> None:
    bash_path = get_required_env("GIT_BASH_PATH")
    subprocess.run([bash_path, "-lc", command], cwd=cwd, check=True)


def _prepare_build_scripts(repo_path: Path) -> Path:
    """Create a clean transient directory with build-only helper scripts."""
    builder_root = Path(__file__).resolve().parents[1]
    source_dir = builder_root / "scripts" / "additional_artifacts"
    target_dir = repo_path / BUILD_SCRIPTS_DIR_NAME

    if not source_dir.is_dir():
        raise RuntimeError(f"Additional artifact generator directory not found: {source_dir}")

    if target_dir.exists():
        if not target_dir.is_dir():
            raise RuntimeError(f"Backend build scripts path exists but is not a directory: {target_dir}")
        _log_build_step(f"remove stale build_scripts directory: {target_dir}")
        shutil.rmtree(target_dir)

    _log_build_step(f"create build_scripts directory: {target_dir}")
    _log_build_step(f"copy artifact generators from: {source_dir}")
    target_dir.mkdir(parents=True)

    try:
        for script_path in source_dir.glob("*.py"):
            if not SCHEMA_SUMMARY_SQL_ENABLED and script_path.name == "create_sql_migrations.py":
                _log_build_step(f"skip generator copy while schema summary SQL is disabled: {script_path.name}")
                continue
            _log_build_step(f"copy generator: {script_path.name} -> {target_dir / script_path.name}")
            shutil.copy2(script_path, target_dir / script_path.name)
    except Exception:
        _cleanup_build_scripts(target_dir)
        raise

    return target_dir


def _cleanup_build_scripts(build_scripts_dir: Path) -> None:
    if build_scripts_dir.is_dir():
        _log_build_step(f"skip cleanup build_scripts directory for debug: {build_scripts_dir}")


def _log_matching_files(root: Path, pattern: str, label: str) -> None:
    matches = sorted(root.glob(pattern))
    match_names = ", ".join(match.name for match in matches) if matches else "none"
    _log_build_step(f"{label} lookup directory: {root}")
    _log_build_step(f"{label} lookup pattern: {pattern}")
    _log_build_step(f"{label} matches: {match_names}")


def _ensure_backend_build_venv(source_repo_path: Path) -> Path:
    """Return source backend venv activation path, creating venv when absent."""
    venv_relative_path = get_required_env("BACKEND_BUILD_VENV_RELATIVE_PATH")
    venv_activate_path = source_repo_path / Path(venv_relative_path)

    if venv_activate_path.is_file():
        return venv_activate_path

    venv_dir = venv_activate_path.parents[1]
    logging.info("Backend source venv not found, creating: %s", venv_dir)
    _run_git_bash(
        f"python -m venv {shlex.quote(_to_git_bash_path(venv_dir))}",
        cwd=source_repo_path,
    )

    if not venv_activate_path.is_file():
        raise RuntimeError(f"Backend venv activation script not found after creation: {venv_activate_path}")

    return venv_activate_path


def _python_path_from_activation_script(venv_activate_path: Path) -> Path:
    scripts_dir = venv_activate_path.parent
    python_path = scripts_dir / "python.exe"
    if not python_path.is_file():
        raise RuntimeError(f"Backend venv python not found: {python_path}")
    return python_path


def _backend_build_requirements_path(source_repo_path: Path) -> Path:
    requirements_relative_path = (
        get_required_env("BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH")
        if "BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH" in os.environ
        else DEFAULT_BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH
    )
    requirements_path = source_repo_path / Path(requirements_relative_path)
    if not requirements_path.is_file():
        raise RuntimeError(f"Backend build requirements file not found: {requirements_path}")
    return requirements_path


def _pip_trusted_host_args() -> str:
    return " ".join(f"--trusted-host {shlex.quote(host)}" for host in PIP_TRUSTED_HOSTS)


def _install_backend_build_requirements(source_repo_path: Path, python_path: Path) -> None:
    requirements_path = _backend_build_requirements_path(source_repo_path)
    bash_python = shlex.quote(_to_git_bash_path(python_path))
    bash_requirements = shlex.quote(_to_git_bash_path(requirements_path))
    trusted_hosts = _pip_trusted_host_args()

    _log_build_step(f"install backend build requirements: {requirements_path}")
    _run_git_bash(
        f"{bash_python} -m pip install {trusted_hosts} --upgrade pip",
        cwd=source_repo_path,
    )
    _run_git_bash(
        f"{bash_python} -m pip install {trusted_hosts} -r {bash_requirements}",
        cwd=source_repo_path,
    )


def _run_additional_artifact_generators(source_repo_path: Path, build_scripts_dir: Path) -> None:
    """Run SQL artifact generators through the backend source virtualenv."""
    venv_activate_path = _ensure_backend_build_venv(source_repo_path)
    python_path = _python_path_from_activation_script(venv_activate_path)
    _install_backend_build_requirements(source_repo_path, python_path)
    bash_python = shlex.quote(_to_git_bash_path(python_path))
    scripts = ["create_run_all_sql.py"]
    if SCHEMA_SUMMARY_SQL_ENABLED:
        scripts.insert(0, "create_sql_migrations.py")
    else:
        _log_build_step("skip schema summary SQL generator: temporarily disabled")
    _log_build_step(f"run generators from source repo: {source_repo_path}")
    _log_build_step(f"use source venv python: {python_path}")
    for script_name in scripts:
        script_path = f"{BUILD_SCRIPTS_DIR_NAME}/{script_name}"
        command = f"{bash_python} -Xutf8 {shlex.quote(script_path)}"
        _log_build_step("")
        _log_build_step(f"run generator: {script_path}")
        _log_build_step(f"command: {command}")
        _run_git_bash(command, cwd=source_repo_path)


def _run_all_include_paths(repo: Path, run_all_sql: Path) -> list[Path]:
    """Return the docs/database/scripts files referenced by a run_all SQL file."""
    include_paths: list[Path] = []

    for line in run_all_sql.read_text(encoding="utf-8").splitlines():
        match = INCLUDE_RE.match(line)
        if not match:
            continue

        include_path = Path(match.group(1))
        if include_path.is_absolute() or ".." in include_path.parts:
            raise RuntimeError(f"Invalid include path in {run_all_sql}: {include_path}")

        if not include_path.is_relative_to(DATABASE_SCRIPTS_PREFIX):
            raise RuntimeError(
                f"Include path in {run_all_sql} must be inside {DATABASE_SCRIPTS_PREFIX}: {include_path}"
            )

        source_path = repo / include_path
        if not source_path.is_file():
            raise RuntimeError(f"Include file referenced by {run_all_sql} was not found: {source_path}")

        include_paths.append(include_path)

    return sorted(set(include_paths))


def _add_run_all_includes_to_tar(archive: tarfile.TarFile, repo: Path, run_all_sql: Path) -> None:
    for include_path in _run_all_include_paths(repo, run_all_sql):
        add_file_to_tar(archive, repo / include_path, include_path.as_posix())


def _create_db_sql_artifact(
    release_dir: Path,
    artifact_type: str,
    build_version: str,
    commit_hash: str,
    add_contents: Callable[[tarfile.TarFile], None],
) -> str:
    archive_name = f"db_{artifact_type}_r_{build_version}-c_{commit_hash}.tar.gz"
    archive_path = release_dir / archive_name

    with tarfile.open(archive_path, "w:gz") as archive:
        add_contents(archive)

    logging.info("Created DB %s archive: %s", artifact_type, archive_path)
    return archive_name


def _create_db_migrations_archives(repo_path: str, source_repo_path: str, build_version: str) -> dict[str, str]:
    """Create separate schema/insert/update DB archives for the current backend commit."""
    repo = Path(repo_path)
    source_repo = Path(source_repo_path)
    release_dir = Path(get_required_env("RELEASE_ROOT_WINDOWS")) / build_version
    release_dir.mkdir(parents=True, exist_ok=True)

    commit_hash = git_output(source_repo_path, "rev-parse", "--short", "HEAD")
    build_scripts_dir = _prepare_build_scripts(source_repo)

    try:
        _run_additional_artifact_generators(source_repo, build_scripts_dir)

        if SCHEMA_SUMMARY_SQL_ENABLED:
            _log_matching_files(
                source_repo / "docs" / "database" / "summary",
                f"summary_sql_*_{commit_hash}.sql",
                "schema summary SQL",
            )
        else:
            _log_build_step("skip schema summary SQL archive: temporarily disabled")
        _log_matching_files(
            build_scripts_dir,
            f"run_all_insert_{commit_hash}.sql",
            "run_all insert SQL",
        )
        _log_matching_files(
            build_scripts_dir,
            f"run_all_update_{commit_hash}.sql",
            "run_all update SQL",
        )

        run_all_insert = one_match(build_scripts_dir, f"run_all_insert_{commit_hash}.sql")
        run_all_update = one_match(build_scripts_dir, f"run_all_update_{commit_hash}.sql")

        schema_archive = None
        if SCHEMA_SUMMARY_SQL_ENABLED:
            schema_sql = one_match(
                source_repo / "docs" / "database" / "summary",
                f"summary_sql_*_{commit_hash}.sql",
            )
            schema_archive = _create_db_sql_artifact(
                release_dir,
                "schema",
                build_version,
                commit_hash,
                lambda archive: add_file_to_tar(
                    archive,
                    schema_sql,
                    f"docs/database/summary/{schema_sql.name}",
                ),
            )
        insert_archive = _create_db_sql_artifact(
            release_dir,
            "insert",
            build_version,
            commit_hash,
            lambda archive: (
                add_file_to_tar(archive, run_all_insert, run_all_insert.name),
                _add_run_all_includes_to_tar(archive, source_repo, run_all_insert),
            ),
        )
        update_archive = _create_db_sql_artifact(
            release_dir,
            "update",
            build_version,
            commit_hash,
            lambda archive: (
                add_file_to_tar(archive, run_all_update, run_all_update.name),
                _add_run_all_includes_to_tar(archive, source_repo, run_all_update),
            ),
        )
    finally:
        _cleanup_build_scripts(build_scripts_dir)

    manifest = {
        "backend_commit_short_hash": commit_hash,
        "db_insert_archive": insert_archive,
        "db_update_archive": update_archive,
    }
    if schema_archive:
        manifest["db_schema_archive"] = schema_archive
    return manifest


def build_backend(
    build_version: str,
    branch_name: str,
) -> dict[str, str]:
    """Main backend build function."""
    logging.info("Starting backend deployment automation")

    repo1_path = get_required_env("BACKEND_SOURCE_REPO_PATH")
    repo2_path = get_required_env("BACKEND_TARGET_REPO_PATH")

    if not check_repo(repo1_path):
        sys.exit(1)

    if not check_repo(repo2_path):
        sys.exit(1)

    if not git_checkout_dev(repo1_path):
        logging.error("git checkout dev failed in backend source repo")
        sys.exit(1)

    if not git_pull(repo1_path):
        logging.error("git pull failed in backend source repo")
        sys.exit(1)

    if not git_checkout_dev(repo2_path):
        logging.error("git checkout dev failed in backend target repo")
        sys.exit(1)

    if not git_pull(repo2_path):
        logging.error("git pull failed in backend target repo")
        sys.exit(1)

    if not git_checkout_new_branch(repo2_path, branch_name):
        logging.error("Creating a new branch failed in backend target repo")
        sys.exit(1)

    logging.info("Created branch: %s", branch_name)

    if not clear_directory_contents(repo2_path):
        logging.error("Clearing backend target repo failed")
        sys.exit(1)

    if not copy_directory_contents(repo1_path, repo2_path):
        logging.error("Copying backend source repo contents to target repo failed")
        sys.exit(1)

    commit_msg = f"Sync from repo1 to repo2 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"  # noqa
    if not git_add_commit_push(repo2_path, commit_msg):
        logging.error("Git add/commit/push failed in backend target repo")
        sys.exit(1)

    db_artifact_manifest = _create_db_migrations_archives(
        repo_path=repo2_path,
        source_repo_path=repo1_path,
        build_version=build_version,
    )

    bash_path = get_required_env("GIT_BASH_PATH")
    build_script_path = r"scripts\archive_script_backend.sh"
    subprocess.run([bash_path, build_script_path, "all_env", build_version, "all_env"], check=True)

    return db_artifact_manifest


if __name__ == "__main__":
    build_version = get_new_build_version()
    branch_name = get_new_branch_name(build_version=build_version)
    build_backend(
        build_version=build_version,
        branch_name=branch_name,
    )
