"""Запуск локальных команд и потоковый вывод процесса."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from simple_deploy.core.paths import DEFAULT_TIMEOUT


@dataclass
class CommandResult:
    """Результат завершенной локальной команды."""

    rc: int
    stdout: str
    stderr: str


def decode_subprocess_output(data: bytes | str | None) -> str:
    """Декодирует stdout/stderr subprocess с учетом Windows console encodings."""

    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "cp1251", "cp866"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def mask_text(text: str, mask: Iterable[str] = ()) -> str:
    """Маскирует секреты в выводе команд."""

    masked = text
    for secret in mask:
        if secret:
            masked = masked.replace(secret, "***")
    return masked


def run_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    mask: Iterable[str] = (),
) -> CommandResult:
    """Запускает команду и возвращает stdout/stderr без streaming."""

    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            input=input_text.encode("utf-8") if input_text is not None else None,
            env=env,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = decode_subprocess_output(exc.stdout)
        stderr = decode_subprocess_output(exc.stderr)
        return CommandResult(124, stdout, stderr or f"timeout after {timeout}s")

    stdout = decode_subprocess_output(completed.stdout)
    stderr = decode_subprocess_output(completed.stderr)
    stdout = mask_text(stdout, mask)
    stderr = mask_text(stderr, mask)
    return CommandResult(completed.returncode, stdout, stderr)


def stream_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    mask: Iterable[str] = (),
) -> int:
    """Запускает команду и сразу печатает объединенный stdout/stderr."""

    mask_values = tuple(mask)
    printable_args = [mask_text(str(arg), mask_values) for arg in args]
    print(f"RUN {' '.join(printable_args)}", flush=True)
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    start = time.monotonic()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            print(mask_text(decode_subprocess_output(line), mask_values), end="", flush=True)
            if timeout is not None and time.monotonic() - start > timeout:
                process.kill()
                print(f"ERROR: timeout after {timeout}s", file=sys.stderr, flush=True)
                return 124
        return process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()


__all__ = [
    "CommandResult",
    "decode_subprocess_output",
    "mask_text",
    "run_command",
    "stream_command",
]
