"""Чтение runtime env и базовые path helpers."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from simple_deploy.core.paths import ROOT


def load_dotenv_file(path: Path, required: bool) -> dict[str, str]:
    """Читает dotenv-файл и убирает BOM из ключей."""
    if not path.exists():
        if required:
            raise RuntimeError(f"Файл не найден: {path}")
        return {}
    return {
        key.lstrip("\ufeff"): value
        for key, value in dotenv_values(path).items()
        if value is not None
    }


def load_env(
    env_file: Path, secrets_file: Path, require_secrets: bool
) -> dict[str, str]:
    """Собирает runtime env из публичного env-файла и local secrets."""
    config = load_dotenv_file(env_file, required=True)
    secrets = load_dotenv_file(secrets_file, required=require_secrets)
    merged = {**config, **secrets}

    if require_secrets:
        db_user = merged.get("DB_LOGIN_USER", "").strip()
        db_password = merged.get("DB_LOGIN_PASSWORD", "").strip()
        if not db_user:
            raise RuntimeError(
                "DB_LOGIN_USER must be set in local.secrets.env"
            )
        if not db_password or db_password == "change-me":
            raise RuntimeError(
                "DB_LOGIN_PASSWORD must be set in local.secrets.env"
            )

    if "DB_LOGIN_USER" not in merged:
        merged["DB_LOGIN_USER"] = "postgres"
    if "DB_LOGIN_PASSWORD" not in merged:
        merged["DB_LOGIN_PASSWORD"] = ""
    return merged


def require_value(env: dict[str, str], name: str) -> str:
    """Возвращает обязательное значение runtime env."""
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная: {name}")
    return value


def wsl_to_windows_path(path: str) -> str:
    """Преобразует ``/mnt/c/...`` в Windows path, если формат распознан."""
    if path.startswith("/mnt/") and len(path) > 6:
        drive = path[5].upper()
        rest = path[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return ""


def windows_release_root(env: dict[str, str]) -> Path:
    """Возвращает Windows-корень директории релизов из runtime env."""
    explicit = env.get("RELEASE_ROOT_WINDOWS", "").strip()
    if explicit:
        return Path(explicit)

    wsl_path = env.get("RELEASE_ROOT_WSL", "").strip()
    converted = wsl_to_windows_path(wsl_path)
    if converted:
        return Path(converted)

    return ROOT / "releases"


def to_git_bash_path(path: str | Path) -> str:
    """Преобразует Windows path в path, понятный Git Bash."""
    normalized = str(path).replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[0].lower()
        rest = normalized[2:].lstrip("/")
        return f"/{drive}/{rest}"
    return normalized


__all__ = [
    "load_dotenv_file",
    "load_env",
    "require_value",
    "to_git_bash_path",
    "windows_release_root",
    "wsl_to_windows_path",
]
