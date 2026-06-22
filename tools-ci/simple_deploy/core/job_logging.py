"""Shared job log helpers for CLI, workers and WebSocket tailing."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
import sys
import time

from simple_deploy.core.paths import DEFAULT_LOG_DIR

JOB_LOGGER_NAME = "simple_deploy.job"


class Tee:
    """Write the same text to multiple output streams."""

    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def create_log_file(command: str) -> Path:
    """Create a stable log file path for a command or local job."""
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_command = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in command or "run"
    )
    return DEFAULT_LOG_DIR / f"{timestamp}-{safe_command}.log"


def job_log(message: str, *, error: bool = False) -> None:
    """Write an operator-facing line through the job logger when active."""
    logger = logging.getLogger(JOB_LOGGER_NAME)
    if logger.handlers:
        logger.info(message)
        return
    print(message, file=sys.stderr if error else sys.stdout, flush=True)


@contextlib.contextmanager
def job_log_output(
    command: str,
    *,
    log_path: Path | None = None,
    announce: bool = True,
):
    """Mirror stdout/stderr and the job logger to console and a log file."""
    path = log_path or create_log_file(command)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log_file:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        tee_stdout = Tee(original_stdout, log_file)
        tee_stderr = Tee(original_stderr, log_file)
        logger = logging.getLogger(JOB_LOGGER_NAME)
        old_handlers = logger.handlers[:]
        old_level = logger.level
        old_propagate = logger.propagate
        handler = logging.StreamHandler(tee_stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False
        sys.stdout = tee_stdout
        sys.stderr = tee_stderr
        try:
            if announce:
                print(f"RUN LOG {path}", flush=True)
            yield path
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            logger.handlers = old_handlers
            logger.setLevel(old_level)
            logger.propagate = old_propagate


tee_output = job_log_output


__all__ = [
    "JOB_LOGGER_NAME",
    "Tee",
    "create_log_file",
    "job_log",
    "job_log_output",
    "tee_output",
]
