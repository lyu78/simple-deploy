"""Выполняет сборку фронтенд-приложения."""

from datetime import datetime
import logging
import sys

from src.infra import (
    git_checkout_dev,
    git_pull,
    git_checkout_new_branch,
    git_add_commit_push,
    get_new_branch_name,
    get_new_build_version,
    git_npm_i,
)
from src.utils import get_required_env
from src.build import (
    get_building_archive_preprod,
    get_building_archive_dev,
    get_building_archive_prod,
)
from src.files import (
    clear_directory_contents,
    copy_directory_contents,
    check_repo,
)

logging.basicConfig(level=logging.INFO)


def build_frontend(
    build_version: str,
    branch_name: str,
):
    """Собирает архивы фронтенда для контуров."""
    logging.info("Начало автоматизации деплоя фронтенд-приложения")

    REPO1_PATH = get_required_env("FRONTEND_SOURCE_REPO_PATH")
    REPO2_PATH = get_required_env("FRONTEND_TARGET_REPO_PATH")

    if not check_repo(REPO1_PATH):
        sys.exit(1)

    if not check_repo(REPO2_PATH):
        sys.exit(1)

    # Исходный репозиторий.
    if not git_checkout_dev(REPO1_PATH):
        logging.error(
            "Ошибка при выполнении git checkout dev в репозитории №1"
        )
        sys.exit(1)

    if not git_npm_i(REPO1_PATH):
        logging.error("Ошибка при выполнении npm_i в репозитории №1")
        sys.exit(1)

    if not git_pull(REPO1_PATH):
        logging.error("Ошибка при выполнении git pull в репозитории №1")
        sys.exit(1)

    # Целевой репозиторий.
    if not git_checkout_dev(REPO2_PATH):
        logging.error(
            "Ошибка при выполнении git checkout dev в репозитории №2"
        )
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

    if not git_npm_i(REPO2_PATH):
        logging.error("Ошибка при выполнении npm_i в репозитории №2")
        sys.exit(1)

    # Build dev.
    if not get_building_archive_dev(
        repo2_path=REPO2_PATH,
        build_version=build_version
    ):
        logging.error("Сформировать архив build для dev контура не удалось.")
        sys.exit(1)

    commit_msg = f"Sync from repo1 to repo2 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"  # noqa

    if not git_add_commit_push(REPO2_PATH, commit_msg):
        logging.error("Ошибка при выполнении git операций в репозитории №2")
        sys.exit(1)

    # Build test.
    if not get_building_archive_preprod(
        repo2_path=REPO2_PATH,
        build_version=build_version
    ):
        logging.error("Сформировать архив build для test контура не удалось.")
        sys.exit(1)

    # Build prod.
    if not get_building_archive_prod(
        repo2_path=REPO2_PATH,
        build_version=build_version
    ):
        logging.error("Сформировать архив build для prod контура не удалось.")
        sys.exit(1)


if __name__ == "__main__":
    build_version = get_new_build_version()
    branch_name = get_new_branch_name(build_version=build_version)
    build_frontend(
        build_version=build_version,
        branch_name=branch_name,
    )
