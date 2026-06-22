"""Подготовка окружения для builder/create_release.py."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from simple_deploy.core.env import (
    require_value,
    to_git_bash_path,
    windows_release_root,
)
from simple_deploy.core.paths import (
    BUILDER_ROOT,
    DEFAULT_BACKEND_APP_ROOT_DIR,
    INCLUDE_DATA_SQL_ENV,
    PIP_TRUSTED_HOSTS,
)


def prepare_build_env(env: dict[str, str]) -> dict[str, str]:
    """Собирает окружение subprocess-а builder-а из runtime env."""
    build_env = os.environ.copy()
    build_env.update(env)
    build_env.setdefault("PYTHONIOENCODING", "utf-8")

    release_root = windows_release_root(env)
    build_env.setdefault("RELEASE_ROOT_WINDOWS", str(release_root))
    build_env.setdefault(
        "BACKEND_BUILD_VENV_RELATIVE_PATH", ".venv/Scripts/activate.bat"
    )
    build_env.setdefault(
        "BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH", "requirements.txt"
    )
    build_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    build_env.setdefault("PIP_TRUSTED_HOST", PIP_TRUSTED_HOSTS)
    if not build_env.get("BACKEND_APP_ROOT_DIR"):
        build_env["BACKEND_APP_ROOT_DIR"] = DEFAULT_BACKEND_APP_ROOT_DIR
    if not build_env.get("BACKEND_DJANGO_SETTINGS_MODULE"):
        build_env["BACKEND_DJANGO_SETTINGS_MODULE"] = (
            f"{build_env['BACKEND_APP_ROOT_DIR']}.settings.base"
        )
    if not build_env.get("RELEASE_ROOT_BASH"):
        build_env["RELEASE_ROOT_BASH"] = to_git_bash_path(release_root)
    build_env["BACKEND_REPO_ROOT_BASH"] = to_git_bash_path(
        require_value(env, "BACKEND_SOURCE_REPO_PATH")
    )
    if not build_env.get("FRONTEND_DEV_SERVER_NAME"):
        build_env["FRONTEND_DEV_SERVER_NAME"] = require_value(
            env, "DEV_DOMAIN"
        )
    return build_env


def set_env_line(path: Path, key: str, value: str) -> None:
    """Устанавливает значение env key в dotenv-like файле."""
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_frontend_env_files(
    env: dict[str, str], build_version: str = ""
) -> None:
    """Генерирует frontend env-файлы builder-а для DEV/TEST/PROD доменов."""
    settings = [
        ("frontend_dev", require_value(env, "DEV_DOMAIN")),
        ("frontend_test", require_value(env, "TEST_DOMAIN")),
        ("frontend_prod", require_value(env, "PROD_DOMAIN")),
    ]
    for dirname, domain in settings:
        directory = BUILDER_ROOT / "settings" / dirname
        template = directory / ".env.template"
        target = directory / ".env"
        if not template.exists():
            raise RuntimeError(f"Не найден frontend template: {template}")
        shutil.copy2(template, target)
        base_url = f"https://{domain}"
        replacements = {
            "REACT_APP_BASE_BACKEND_URL": base_url,
            "VITE_BASE_BACKEND_URL": base_url,
            "REACT_APP_FILE_PROXY_SERVICE_URL": f"{base_url}/file/",
            "VITE_FILE_PROXY_SERVICE_URL": f"{base_url}/file/",
            "REACT_APP_FILTERS_SERVICE_URL": f"{base_url}/filters/",
            "VITE_FILTERS_SERVICE_URL": f"{base_url}/filters/",
        }
        if build_version:
            replacements["VITE_BUILD_VERSION"] = build_version
        for key, value in replacements.items():
            set_env_line(target, key, value)


def data_sql_artifacts_enabled(skip_data_sql_artifacts: bool) -> bool:
    """Возвращает, нужно ли builder-у генерировать data SQL artifacts."""
    return not skip_data_sql_artifacts


__all__ = [
    "INCLUDE_DATA_SQL_ENV",
    "data_sql_artifacts_enabled",
    "prepare_build_env",
    "prepare_frontend_env_files",
    "set_env_line",
]
