"""Модуль размещения на локальном контуре и сборки архива с исходным кодом."""

from datetime import datetime
import logging
from pathlib import Path
import shutil
import sys
import tarfile
import subprocess

from src.infra import (
    git_checkout_dev,
    git_pull,
    git_checkout_new_branch,
    git_add_commit_push,
    get_new_branch_name,
    get_new_build_version,
)
from src.utils import (
    add_directory_to_tar,
    add_file_to_tar,
    get_required_env,
    git_output,
    one_match,
)
from src.files import (
    clear_directory_contents,
    copy_directory_contents,
    check_repo,
)

logging.basicConfig(level=logging.INFO)


def _copy_additional_artifact_generators(repo_path: Path) -> None:
    """Копирует генераторы дополнительных артефактов в scripts backend-репозитория."""
    builder_root = Path(__file__).resolve().parents[1]
    source_dir = builder_root / "scripts" / "additional_artifacts"
    target_dir = repo_path / "scripts"

    if not source_dir.is_dir():
        raise RuntimeError(f"Директория генераторов дополнительных артефактов не найдена: {source_dir}")

    if not target_dir.exists():
        logging.info("Директория scripts в backend-репозитории не найдена, создаю: %s", target_dir)
        target_dir.mkdir(parents=True)
    elif not target_dir.is_dir():
        raise RuntimeError(f"Путь scripts в backend-репозитории существует, но не является директорией: {target_dir}")

    for script_path in source_dir.glob("*.py"):
        shutil.copy2(script_path, target_dir / script_path.name)


def _run_additional_artifact_generators(repo_path: Path) -> None:
    """Запускает генераторы SQL-артефактов через backend virtualenv."""
    venv_relative_path = get_required_env("BACKEND_BUILD_VENV_RELATIVE_PATH")
    venv_activate_path = repo_path / Path(venv_relative_path)

    if not venv_activate_path.is_file():
        raise RuntimeError(f"Скрипт активации backend venv не найден: {venv_activate_path}")

    commands = [
        f'call "{venv_activate_path}"',
        "python scripts\\create_sql_migrations.py",
        "python scripts\\create_run_all_sql.py",
    ]
    command = " && ".join(commands)
    subprocess.run(["cmd.exe", "/C", command], cwd=repo_path, check=True)


def _create_db_migrations_archive(repo_path: str, build_version: str) -> dict[str, str]:
    """Создает архив schema/data SQL-миграций для текущего backend commit."""
    repo = Path(repo_path)
    release_dir = Path(get_required_env("RELEASE_ROOT_WINDOWS")) / build_version
    release_dir.mkdir(parents=True, exist_ok=True)

    commit_hash = git_output(repo_path, "rev-parse", "--short", "HEAD")
    _copy_additional_artifact_generators(repo)
    _run_additional_artifact_generators(repo)

    schema_sql = one_match(
        repo / "docs" / "database" / "summary",
        f"summary_sql_*_{commit_hash}.sql",
    )
    run_all_insert = one_match(repo, f"run_all_insert_{commit_hash}.sql")
    run_all_update = one_match(repo, f"run_all_update_{commit_hash}.sql")
    database_scripts_dir = repo / "docs" / "database" / "scripts"

    archive_name = f"db_migrations_r_{build_version}-c_{commit_hash}.tar.gz"
    archive_path = release_dir / archive_name
    with tarfile.open(archive_path, "w:gz") as archive:
        add_file_to_tar(
            archive,
            schema_sql,
            f"docs/database/summary/{schema_sql.name}",
        )
        add_directory_to_tar(
            archive,
            database_scripts_dir,
            "docs/database/scripts",
        )
        add_file_to_tar(archive, run_all_insert, run_all_insert.name)
        add_file_to_tar(archive, run_all_update, run_all_update.name)

    logging.info("Создан архив DB-миграций: %s", archive_path)
    return {
        "backend_commit_short_hash": commit_hash,
        "db_migrations_archive": archive_name,
    }


def build_backend(
    build_version: str,
    branch_name: str,
) -> dict[str, str]:
    """Основная функция скрипта"""
    logging.info("Начало автоматизации деплоя бэкенд-приложения")

    REPO1_PATH = get_required_env("BACKEND_SOURCE_REPO_PATH")
    REPO2_PATH = get_required_env("BACKEND_TARGET_REPO_PATH")

    if not check_repo(REPO1_PATH):
        sys.exit(1)

    if not check_repo(REPO2_PATH):
        sys.exit(1)

    if not git_checkout_dev(REPO1_PATH):
        logging.error("Ошибка при выполнении git checkout dev в репозитории №1")
        sys.exit(1)

    if not git_pull(REPO1_PATH):
        logging.error("Ошибка при выполнении git pull в репозитории №1")
        sys.exit(1)

    if not git_checkout_dev(REPO2_PATH):
        logging.error("Ошибка при выполнении git checkout dev в репозитории №2")
        sys.exit(1)

    if not git_pull(REPO2_PATH):
        logging.error("Ошибка при выполнении git pull в репозитории №2")
        sys.exit(1)

    if not git_checkout_new_branch(REPO2_PATH, branch_name):
        logging.error("Ошибка при создании новой ветки в репозитории №2")
        sys.exit(1)
    
    logging.info(f"Создана ветка: {branch_name}")

    if not clear_directory_contents(REPO2_PATH):
        logging.error("Ошибка при очистке репозитория №2")
        sys.exit(1)

    if not copy_directory_contents(REPO1_PATH, REPO2_PATH):
        logging.error(
            "Ошибка при копировании содержимого из репозитория №1 в №2"
        )
        sys.exit(1)

    commit_msg = f"Sync from repo1 to repo2 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"  # noqa
    if not git_add_commit_push(REPO2_PATH, commit_msg):
        logging.error("Ошибка при выполнении git операций в репозитории №2")
        sys.exit(1)

    # Создание архива для всех контуров (DEV, TEST, PROD)
    db_artifact_manifest = _create_db_migrations_archive(
        repo_path=REPO2_PATH,
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
