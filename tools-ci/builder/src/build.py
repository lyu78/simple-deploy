from enum import Enum
import logging
from pathlib import Path
from dotenv import dotenv_values, set_key

from pydantic import BaseModel, computed_field

from src.utils import get_required_env, run_command
from src.files import copy_file_to_repo2


def _update_vite_build_version(repo_path: str, build_version: str):
    """
    Обновляет значение переменной VITE_BUILD_VERSION в .env файле.

    :param env_path: Путь к .env файлу.
    :param new_version: Новое значение версии (например, "1.2.3").
    """
    env_path = Path(repo_path) / ".env"

    if not env_path.is_file():
        logging.error(f"Файл .env не найден в {repo_path}")
        return False

    env_vars = dotenv_values(env_path)

    if "VITE_BUILD_VERSION" not in env_vars:
        logging.error("Переменная VITE_BUILD_VERSION не найдена в .env")
        return False

    try:
        success, _, _ = set_key(
            dotenv_path=env_path,
            key_to_set='VITE_BUILD_VERSION',
            value_to_set=build_version)

        if success:
            logging.info(
                f"VITE_BUILD_VERSION обновлена на: {build_version}"
            )
            return True
        else:
            logging.error('Не удалось обновить VITE_BUILD_VERSION.')
            return False

    except Exception as e:
        logging.error(f'Непредвиденная ошибка обновления версии билда: {e}')
        return False


class BuildFormat(Enum):
    """Формат сборки vite."""

    DEV = "development"
    PREPROD = "preproduction"
    PROD = "production"


class ServerName(Enum):
    """Префикс имени сервера."""

    DEV = get_required_env("FRONTEND_DEV_SERVER_NAME")
    TEST = get_required_env("FRONTEND_TEST_SERVER_NAME")
    PROD = get_required_env("FRONTEND_PROD_SERVER_NAME")


class FrontendEnv(BaseModel):
    """Окружение билда фронтенда"""

    path: str
    server_name: ServerName


class FrontendBuilding(BaseModel):
    """Билд фронтенда."""

    build_format: BuildFormat
    env: FrontendEnv
    script_dir: str = "scripts"
    script_name: str = "archive_script_frontend.sh"

    @computed_field
    @property
    def script_path(self) -> str:
        return rf"{self.script_dir}\{self.script_name}"


frontend_building_dev = FrontendBuilding(
    build_format=BuildFormat.DEV,
    env=FrontendEnv(
        path=r"settings\frontend_dev\.env",
        server_name=ServerName.DEV,
    ),
)

frontend_building_test = FrontendBuilding(
    build_format=BuildFormat.PREPROD,
    env=FrontendEnv(
        path=r"settings\frontend_test\.env",
        server_name=ServerName.TEST,
    ),
)

frontend_building_prod = FrontendBuilding(
    build_format=BuildFormat.PREPROD,
    env=FrontendEnv(
        path=r"settings\frontend_prod\.env",
        server_name=ServerName.PROD,
    ),
)

def _create_frontend_build(
    repo_path: str,
    build_version: str,
    frontend_building: FrontendBuilding,
):
    """Билдит фронтенд для контура."""
    logging.info(
        f"\n---Сборка билда для релиза {build_version} "
        f"в формате {frontend_building.build_format.name.lower()} "
        f"для {frontend_building.env.server_name.value} в {repo_path} ---"
    )
    return run_command(
        f"npx vite build --mode {frontend_building.build_format.value} "
        f"&& sh {frontend_building.script_name} {frontend_building.build_format.name.lower()} "
        f"{build_version} {frontend_building.env.server_name.value}",
        cwd=repo_path
    )


def _get_building_archive(
    repo2_path: str,
    build_version: str,
    frontend_building: FrontendBuilding = frontend_building_prod,
):
    """Формирует build для контура."""
    if not copy_file_to_repo2(
        repo2_path=repo2_path,
        file_relative_path=frontend_building.env.path
    ):
        logging.error(
            f"Ошибка при выполнении копирования {frontend_building.env.path} "
            "в репозитории №2"
        )
        return False

    if not copy_file_to_repo2(
        repo2_path=repo2_path,
        file_relative_path=frontend_building.script_path
    ):
        logging.error(
            "Ошибка при выполнении копирования "
            f"{frontend_building.script_path} в репозитории №2"
        )
        return False

    if not _update_vite_build_version(
        repo_path=repo2_path,
        build_version=build_version,
    ):
        return False

    if not _create_frontend_build(
        repo_path=repo2_path,
        build_version=build_version,
        frontend_building=frontend_building,
    ):
        logging.error(
            "Ошибка при выполнении сборки фронтенда для прода в репозитории №2"
        )
        return False
    return True


def get_building_archive_prod(
    repo2_path: str,
    build_version: str,
):
    """Формирует build для продуктивного контура ЦОД-М."""
    return _get_building_archive(
        repo2_path=repo2_path,
        build_version=build_version,
        frontend_building=frontend_building_prod,
    )


def get_building_archive_preprod(
    repo2_path: str,
    build_version: str,
):
    """Формирует build для тестового контура ЦОД-М."""
    return _get_building_archive(
        repo2_path=repo2_path,
        build_version=build_version,
        frontend_building=frontend_building_test,
    )


def get_building_archive_dev(
    repo2_path: str,
    build_version: str,
):
    """Формирует build для dev контура ЦПС."""
    if not copy_file_to_repo2(
        repo2_path=repo2_path,
        file_relative_path=r"settings\frontend_dev\.gitignore"
    ):
        logging.error(
            "Ошибка при выполнении копирования .gitignore в репозитории №2"
        )
        return False

    return _get_building_archive(
        repo2_path=repo2_path,
        build_version=build_version,
        frontend_building=frontend_building_dev,
    )
