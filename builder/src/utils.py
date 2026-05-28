import logging
import os
import subprocess


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
