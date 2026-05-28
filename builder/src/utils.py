import logging
import os
from pathlib import Path
import subprocess
import tarfile


def get_required_env(name: str) -> str:
    """Возвращает обязательную переменную окружения для Ansible-managed запуска."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return value


def run_command(cmd, cwd=None) -> bool:
    """Выполняет команду в оболочке и возвращает результат."""
    logging.info(f"Выполняю: {cmd}")
    result = subprocess.run(
        cmd, shell=True, cwd=cwd, text=True
    )

    if result.returncode != 0:
        logging.error(f"Ошибка при выполнении команды: {cmd}")
        return False

    logging.info(f"Успешно: {cmd}")
    return True


def git_output(repo_path: str, *args: str) -> str:
    """Возвращает stdout git-команды для указанного репозитория."""
    result = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def one_match(root: Path, pattern: str) -> Path:
    """Находит ровно один файл по шаблону, иначе останавливает выполнение."""
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(
            f"Ожидался ровно один файл по шаблону {pattern} в {root}, найдено: {len(matches)}."
        )
    return matches[0]


def add_file_to_tar(archive: tarfile.TarFile, source: Path, arcname: str) -> None:
    """Добавляет обязательный файл в tar-архив."""
    if not source.is_file():
        raise RuntimeError(f"Обязательный файл для архива не найден: {source}")
    archive.add(source, arcname=arcname)


def add_directory_to_tar(archive: tarfile.TarFile, source: Path, arcname: str) -> None:
    """Добавляет обязательную директорию в tar-архив."""
    if not source.is_dir():
        raise RuntimeError(f"Обязательная директория для архива не найдена: {source}")
    archive.add(source, arcname=arcname)
