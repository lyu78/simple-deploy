"""Backend source sync and release artifact build."""

from contextlib import closing
from datetime import datetime
import json
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

TOOLS_CI_ROOT = Path(__file__).resolve().parents[2]
if str(TOOLS_CI_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_CI_ROOT))

from src.files import (
    check_repo,
    sync_source_top_level_items,
)
from src.infra import (
    get_new_branch_name,
    get_new_build_version,
    git_add_commit_push,
    git_checkout_dev,
    git_checkout_new_branch,
    git_pull,
)
from simple_deploy.release.state import CONTOURS, connect_state_db, get_contour_state
from src.utils import (
    add_file_to_tar,
    get_required_env,
    git_output,
    one_match,
    to_git_bash_path,
)

logging.basicConfig(level=logging.INFO)

INCLUDE_RE = re.compile(r"^\s*\\i\s+['\"]?([^'\"\s]+)['\"]?")
SHELL_INCLUDE_RE = re.compile(r"^\s*#\s*simple-deploy-include:\s*([^\s]+)\s*$")
DATABASE_SCRIPTS_PREFIX = Path("docs/database/scripts")
BUILD_SCRIPTS_DIR_NAME = "build_scripts"
DEFAULT_BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH = "requirements.txt"
DEFAULT_BACKEND_APP_ROOT_DIR = "example_backend_app"
INCLUDE_DATA_SQL_ENV = "SIMPLE_DEPLOY_INCLUDE_DATA_SQL"
PIP_TRUSTED_HOSTS = (
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
)
PIP_DISABLE_VERSION_CHECK_ARG = "--disable-pip-version-check"


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


def _run_logged_command(args: list[str], cwd: Path) -> None:
    """Запускает команду с потоковым выводом и понятной ошибкой при non-zero exit."""
    command_text = subprocess.list2cmdline([str(arg) for arg in args])
    _log_build_step(f"command: {command_text}")
    try:
        process = subprocess.Popen(
            [str(arg) for arg in args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command executable not found: {command_text}") from exc

    output_lines: list[str] = []
    assert process.stdout is not None
    with process.stdout:
        for line in process.stdout:
            output_lines.append(line)
            print(line, end="", flush=True)
    return_code = process.wait()
    if return_code != 0:
        tail = "".join(output_lines[-80:])
        raise RuntimeError(
            f"Command failed with exit code {return_code}: {command_text}\n"
            f"Last output lines:\n{tail}"
        )


def _schema_baselines_json() -> str:
    with closing(connect_state_db()) as connection:
        baselines = {}
        missing = []
        for contour in CONTOURS:
            state = get_contour_state(connection, contour)
            if state is None:
                missing.append(contour)
            else:
                baselines[contour] = state.last_success_backend_commit
    if missing:
        raise RuntimeError(
            "Missing schema SQL baselines for contours: "
            f"{', '.join(missing)}. Run "
            "`tools-ci/tools/windows_pipeline.py set-baseline --contour <contour> --build-version <version>` first."
        )
    return json.dumps(baselines, ensure_ascii=False)


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
            _log_build_step(f"copy generator: {script_path.name} -> {target_dir / script_path.name}")
            shutil.copy2(script_path, target_dir / script_path.name)
    except Exception:
        _cleanup_build_scripts(target_dir)
        raise

    return target_dir


def _cleanup_build_scripts(build_scripts_dir: Path) -> None:
    if build_scripts_dir.is_dir():
        _log_build_step(f"remove transient build_scripts directory: {build_scripts_dir}")
        shutil.rmtree(build_scripts_dir)


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


def _backend_app_root_dir() -> str:
    """Возвращает директорию backend application root внутри source repo."""
    return os.environ.get("BACKEND_APP_ROOT_DIR", "").strip() or DEFAULT_BACKEND_APP_ROOT_DIR


def _include_data_sql_artifacts() -> bool:
    value = os.environ.get(INCLUDE_DATA_SQL_ENV, "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _pip_trusted_host_args() -> list[str]:
    args: list[str] = []
    for host in PIP_TRUSTED_HOSTS:
        args.extend(["--trusted-host", host])
    return args


def _install_backend_build_requirements(source_repo_path: Path, python_path: Path) -> None:
    requirements_path = _backend_build_requirements_path(source_repo_path)
    trusted_hosts = _pip_trusted_host_args()

    _log_build_step(f"install backend build requirements: {requirements_path}")
    _run_logged_command(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            PIP_DISABLE_VERSION_CHECK_ARG,
            *trusted_hosts,
            "-r",
            str(requirements_path),
        ],
        cwd=source_repo_path,
    )


def _prepare_backend_build_python(source_repo_path: Path) -> Path:
    """Готовит Python backend source repo для запуска build-only генераторов."""
    venv_activate_path = _ensure_backend_build_venv(source_repo_path)
    python_path = _python_path_from_activation_script(venv_activate_path)
    _install_backend_build_requirements(source_repo_path, python_path)
    _log_build_step(f"run generators from source repo: {source_repo_path}")
    _log_build_step(f"use source venv python: {python_path}")
    return python_path


def _run_artifact_generator(source_repo_path: Path, python_path: Path, script_name: str) -> None:
    """Запускает один build-only генератор через Python backend source venv."""
    script_path = source_repo_path / BUILD_SCRIPTS_DIR_NAME / script_name
    _log_build_step("")
    _log_build_step(f"run generator: {BUILD_SCRIPTS_DIR_NAME}/{script_name}")
    _run_logged_command(
        [str(python_path), "-Xutf8", str(script_path)],
        cwd=source_repo_path,
    )


def _run_additional_artifact_generators(source_repo_path: Path, build_scripts_dir: Path) -> None:
    """Run SQL artifact generators through the backend source virtualenv."""
    python_path = _prepare_backend_build_python(source_repo_path)
    _run_artifact_generator(source_repo_path, python_path, "create_sql_migrations.py")
    if _include_data_sql_artifacts():
        _run_artifact_generator(source_repo_path, python_path, "create_run_all_sql.py")
    else:
        _log_build_step("skip data SQL artifacts: disabled by --skip-data-sql-artifacts")


def _require_schema_metadata_after_generator(build_scripts_dir: Path) -> Path:
    schema_metadata_path = build_scripts_dir / "schema_migrations_metadata.json"
    if not schema_metadata_path.is_file():
        raise RuntimeError(
            "Schema migration generator exited successfully but did not create metadata: "
            f"{schema_metadata_path}. Check create_sql_migrations.py output above; "
            "common causes are missing backend dependencies, Django settings errors, "
            "or failed pip installation."
        )
    return schema_metadata_path


def _validate_db_script_include_path(repo: Path, owner: Path, include_text: str) -> Path:
    include_path = Path(include_text)
    if include_path.is_absolute() or ".." in include_path.parts:
        raise RuntimeError(f"Invalid include path in {owner}: {include_path}")

    if not include_path.is_relative_to(DATABASE_SCRIPTS_PREFIX):
        raise RuntimeError(
            f"Include path in {owner} must be inside {DATABASE_SCRIPTS_PREFIX}: {include_path}"
        )

    source_path = repo / include_path
    if not source_path.is_file():
        raise RuntimeError(f"Include file referenced by {owner} was not found: {source_path}")

    return include_path


def _run_all_include_paths(repo: Path, run_all_sql: Path) -> list[Path]:
    """Return the docs/database/scripts files referenced by a run_all SQL file."""
    include_paths: list[Path] = []
    for line in run_all_sql.read_text(encoding="utf-8").splitlines():
        match = INCLUDE_RE.match(line)
        if not match:
            continue

        include_paths.append(_validate_db_script_include_path(repo, run_all_sql, match.group(1)))

    return sorted(set(include_paths))


def _add_run_all_includes_to_tar(archive: tarfile.TarFile, repo: Path, run_all_sql: Path) -> None:
    for include_path in _run_all_include_paths(repo, run_all_sql):
        add_file_to_tar(archive, repo / include_path, include_path.as_posix())


def _shell_runner_include_paths(repo: Path, runner: Path) -> list[Path]:
    """Return the docs/database/scripts files referenced by a generated shell runner."""
    include_paths: list[Path] = []
    for line in runner.read_text(encoding="utf-8").splitlines():
        match = SHELL_INCLUDE_RE.match(line)
        if not match:
            continue
        include_paths.append(_validate_db_script_include_path(repo, runner, match.group(1)))
    return sorted(set(include_paths))


def _add_shell_runner_includes_to_tar(archive: tarfile.TarFile, repo: Path, runner: Path) -> None:
    for include_path in _shell_runner_include_paths(repo, runner):
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


def _create_db_migrations_archives(source_repo_path: str, build_version: str) -> dict[str, object]:
    """Create separate schema/insert/update DB archives for the current backend commit."""
    source_repo = Path(source_repo_path)
    release_dir = Path(get_required_env("RELEASE_ROOT_WINDOWS")) / build_version
    release_dir.mkdir(parents=True, exist_ok=True)

    commit_hash = git_output(source_repo_path, "rev-parse", "--short", "HEAD")
    build_scripts_dir = _prepare_build_scripts(source_repo)
    previous_baselines = os.environ.get("SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON")
    include_data_sql = _include_data_sql_artifacts()

    try:
        os.environ["SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON"] = _schema_baselines_json()
        python_path = _prepare_backend_build_python(source_repo)
        _run_artifact_generator(source_repo, python_path, "create_sql_migrations.py")
        schema_metadata_path = _require_schema_metadata_after_generator(build_scripts_dir)
        if include_data_sql:
            _run_artifact_generator(source_repo, python_path, "create_run_all_sql.py")
        else:
            _log_build_step("skip data SQL artifacts: disabled by --skip-data-sql-artifacts")

        _log_matching_files(
            build_scripts_dir,
            "summary_sql_*_*.sql",
            "schema summary SQL",
        )

        schema_metadata = json.loads(schema_metadata_path.read_text(encoding="utf-8"))
        schema_archives: dict[str, str] = {}
        for contour in CONTOURS:
            contour_metadata = schema_metadata["contours"][contour]
            schema_sql = build_scripts_dir / contour_metadata["entrypoint"]
            if not schema_sql.is_file():
                raise RuntimeError(f"Schema SQL was not generated for {contour}: {schema_sql}")
            schema_archives[contour] = _create_db_sql_artifact(
                release_dir,
                f"schema_{contour}",
                build_version,
                commit_hash,
                lambda archive: add_file_to_tar(
                    archive,
                    schema_sql,
                    schema_sql.name,
                ),
            )
        data_archives: dict[str, str] = {}
        if include_data_sql:
            _log_matching_files(
                build_scripts_dir,
                f"run_all_insert_{commit_hash}.sql",
                "run_all insert SQL",
            )
            _log_matching_files(
                build_scripts_dir,
                f"run_all_update_sequential_{commit_hash}.sql",
                "run_all update sequential SQL",
            )
            _log_matching_files(
                build_scripts_dir,
                f"run_all_update_parallel_{commit_hash}.sh",
                "run_all update parallel runner",
            )
            run_all_insert = one_match(build_scripts_dir, f"run_all_insert_{commit_hash}.sql")
            run_all_update_sequential = one_match(
                build_scripts_dir,
                f"run_all_update_sequential_{commit_hash}.sql",
            )
            run_all_update_parallel = one_match(
                build_scripts_dir,
                f"run_all_update_parallel_{commit_hash}.sh",
            )
            data_archives["db_insert_archive"] = _create_db_sql_artifact(
                release_dir,
                "insert",
                build_version,
                commit_hash,
                lambda archive: (
                    add_file_to_tar(archive, run_all_insert, run_all_insert.name),
                    _add_run_all_includes_to_tar(archive, source_repo, run_all_insert),
                ),
            )
            data_archives["db_update_sequential_archive"] = _create_db_sql_artifact(
                release_dir,
                "update_sequential",
                build_version,
                commit_hash,
                lambda archive: (
                    add_file_to_tar(archive, run_all_update_sequential, run_all_update_sequential.name),
                    _add_run_all_includes_to_tar(archive, source_repo, run_all_update_sequential),
                ),
            )
            data_archives["db_update_parallel_archive"] = _create_db_sql_artifact(
                release_dir,
                "update_parallel",
                build_version,
                commit_hash,
                lambda archive: (
                    add_file_to_tar(archive, run_all_update_parallel, run_all_update_parallel.name),
                    _add_shell_runner_includes_to_tar(archive, source_repo, run_all_update_parallel),
                ),
            )
    finally:
        if previous_baselines is None:
            os.environ.pop("SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON", None)
        else:
            os.environ["SIMPLE_DEPLOY_SCHEMA_BASELINES_JSON"] = previous_baselines
        _cleanup_build_scripts(build_scripts_dir)

    manifest = {
        "backend_commit_short_hash": commit_hash,
        "db_schema_archives": schema_archives,
        "db_schema_metadata": schema_metadata,
        "db_data_sql_enabled": include_data_sql,
        **data_archives,
    }
    return manifest


def build_backend(
    build_version: str,
    branch_name: str,
) -> dict[str, object]:
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

    if not sync_source_top_level_items(repo1_path, repo2_path):
        logging.error("Syncing backend source repo top-level items to target repo failed")
        sys.exit(1)

    commit_msg = f"Sync from repo1 to repo2 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"  # noqa
    if not git_add_commit_push(repo2_path, commit_msg):
        logging.error("Git add/commit/push failed in backend target repo")
        sys.exit(1)

    db_artifact_manifest = _create_db_migrations_archives(
        source_repo_path=repo1_path,
        build_version=build_version,
    )

    bash_path = get_required_env("GIT_BASH_PATH")
    build_script_path = r"scripts\archive_script_backend.sh"
    archive_env = os.environ.copy()
    archive_env["BACKEND_REPO_ROOT_BASH"] = to_git_bash_path(repo1_path)
    archive_env["BACKEND_APP_ROOT_DIR"] = _backend_app_root_dir()
    subprocess.run(
        [bash_path, build_script_path, "all_env", build_version, "all_env"],
        check=True,
        env=archive_env,
    )

    return db_artifact_manifest


if __name__ == "__main__":
    build_version = get_new_build_version()
    branch_name = get_new_branch_name(build_version=build_version)
    build_backend(
        build_version=build_version,
        branch_name=branch_name,
    )
