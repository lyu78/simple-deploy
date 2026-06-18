"""Вспомогательные функции SSH/SCP для Windows runner-а."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from simple_deploy.core.commands import (
    CommandResult,
    run_command,
    stream_command,
)
from simple_deploy.core.paths import DEFAULT_TIMEOUT


def resolve_ssh_key_path(path_value: str) -> Path:
    """Разрешает путь к SSH-ключу относительно cwd или домашней директории."""
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path

    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path

    return Path.home() / path


def ssh_key_args(env: dict[str, str], scope: str) -> list[str]:
    """Возвращает аргументы OpenSSH для ключа заданной области подключения."""
    specific = env.get(f"{scope}_SSH_KEY_PATH", "").strip()
    generic = env.get("SSH_KEY_PATH", "").strip()
    path_value = specific or generic
    if not path_value:
        return []
    return ["-i", str(resolve_ssh_key_path(path_value))]


def ssh_base_args(
    env: dict[str, str], user: str, host: str, scope: str
) -> list[str]:
    """Собирает базовую команду ssh с безопасными для automation опциями."""
    return [
        "ssh",
        *ssh_key_args(env, scope),
        "-o",
        "BatchMode=yes",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"{user}@{host}",
    ]


def ssh_command(
    env: dict[str, str],
    user: str,
    host: str,
    command: str,
    scope: str,
    input_text: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    mask: Iterable[str] = (),
) -> CommandResult:
    """Выполняет SSH-команду и возвращает полный результат процесса."""
    return run_command(
        ssh_base_args(env, user, host, scope) + [command],
        input_text=input_text,
        timeout=timeout,
        mask=mask,
    )


def stream_ssh_command(
    env: dict[str, str],
    user: str,
    host: str,
    command: str,
    scope: str,
    timeout: int | None = None,
    mask: Iterable[str] = (),
) -> CommandResult:
    """Выполняет удаленную SSH-команду с потоковым выводом в консоль."""
    rc = stream_command(
        ssh_base_args(env, user, host, scope) + [command],
        timeout=timeout,
        mask=mask,
    )
    return CommandResult(rc, "", "")


def scp_file(
    env: dict[str, str],
    local_path: Path,
    user: str,
    host: str,
    remote_path: str,
    scope: str = "APP",
) -> CommandResult:
    """Копирует локальный файл на удаленный хост через scp."""
    return run_command(
        [
            "scp",
            *ssh_key_args(env, scope),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            str(local_path),
            f"{user}@{host}:{remote_path}",
        ],
        timeout=120,
    )


def sh_quote(value: str | Path) -> str:
    """Экранирует значение для безопасной вставки в POSIX shell-команду."""
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


__all__ = [
    "resolve_ssh_key_path",
    "ssh_key_args",
    "ssh_base_args",
    "ssh_command",
    "stream_ssh_command",
    "scp_file",
    "sh_quote",
]
