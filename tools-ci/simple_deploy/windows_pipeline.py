"""Compatibility runner для Windows-only simple-deploy.

Модуль сохраняет старый CLI/import контракт Windows runner-а и постепенно
сжимается до тонкого слоя CLI/logging/re-export поверх новых владельцев логики.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path

from simple_deploy.application.requests import (
    BuildRequest,
    DeployRequest,
    DryRunRequest,
    MarkAppliedRequest,
    MarkFailedRequest,
    PipelineRequest,
    SetBaselineRequest,
)
from simple_deploy.application.services import (
    build as _build_service,
)
from simple_deploy.application.services import (
    deploy as _deploy_service,
)
from simple_deploy.application.services import (
    dry_run as _dry_run_service,
)
from simple_deploy.application.services import (
    mark_applied as _mark_applied_service,
)
from simple_deploy.application.services import (
    mark_failed as _mark_failed_service,
)
from simple_deploy.application.services import (
    pipeline as _pipeline_service,
)
from simple_deploy.application.services import (
    set_baseline as _set_baseline_service,
)
from simple_deploy.cli.requests import (
    build_request_from_args,
    deploy_request_from_args,
    dry_run_request_from_args,
    mark_applied_request_from_args,
    mark_failed_request_from_args,
    pipeline_request_from_args,
    request_from_args,
    set_baseline_request_from_args,
)
from simple_deploy.core.paths import (
    DEFAULT_CONFIG_FILE,
    DEFAULT_ENV_FILE,
    DEFAULT_LOG_DIR,
    DEFAULT_SECRETS_FILE,
)
from simple_deploy.registry.state import (
    CONTOURS,
)


class Tee:
    """Пишет один и тот же текст сразу в несколько потоков вывода."""

    def __init__(self, *streams) -> None:
        """Сохраняет целевые потоки вывода."""
        self.streams = streams

    def write(self, text: str) -> int:
        """Записывает текст во все потоки и возвращает его длину."""
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        """Сбрасывает буферы всех потоков."""
        for stream in self.streams:
            stream.flush()


def create_log_file(command: str) -> Path:
    """Создает путь к log-файлу для запуска указанной CLI-команды."""
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_command = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-"
        for char in command or "run"
    )
    return DEFAULT_LOG_DIR / f"{timestamp}-{safe_command}.log"


@contextlib.contextmanager
def tee_output(command: str):
    """Дублирует stdout/stderr текущей команды в log-файл."""
    log_path = create_log_file(command)
    with log_path.open("w", encoding="utf-8") as log_file:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = Tee(original_stdout, log_file)
        sys.stderr = Tee(original_stderr, log_file)
        try:
            print(f"RUN LOG {log_path}", flush=True)
            yield log_path
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def dry_run(request: DryRunRequest | argparse.Namespace) -> bool:
    """Запускает dry-run через DTO, сохраняя legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = dry_run_request_from_args(request)
    return _dry_run_service(request)


def build(request: BuildRequest | argparse.Namespace) -> int:
    """Запускает build через DTO, сохраняя legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = build_request_from_args(request)
    return _build_service(request)


def deploy(request: DeployRequest | argparse.Namespace) -> int:
    """Запускает deploy через DTO, сохраняя legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = deploy_request_from_args(request)
    return _deploy_service(request)


def pipeline(request: PipelineRequest | argparse.Namespace) -> int:
    """Выполняет dry-run, build и deploy latest как одну CLI-команду."""
    if isinstance(request, argparse.Namespace):
        request = pipeline_request_from_args(request)
    return _pipeline_service(request)


def set_baseline(request: SetBaselineRequest | argparse.Namespace) -> int:
    """Запускает set-baseline через DTO и legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = set_baseline_request_from_args(request)
    return _set_baseline_service(request)


def mark_applied(request: MarkAppliedRequest | argparse.Namespace) -> int:
    """Запускает mark-applied через DTO и legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = mark_applied_request_from_args(request)
    return _mark_applied_service(request)


def mark_failed(request: MarkFailedRequest | argparse.Namespace) -> int:
    """Запускает mark-failed через DTO и legacy Namespace wrapper."""
    if isinstance(request, argparse.Namespace):
        request = mark_failed_request_from_args(request)
    return _mark_failed_service(request)


def parse_args() -> argparse.Namespace:
    """Разбирает аргументы legacy Windows runner CLI."""
    parser = argparse.ArgumentParser(
        description="Windows-only simple-deploy runner"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument(
        "--secrets-file", type=Path, default=DEFAULT_SECRETS_FILE
    )
    parser.add_argument(
        "--config-file", type=Path, default=DEFAULT_CONFIG_FILE
    )
    parser.add_argument("--timeout", type=int, default=3600)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run_parser = subparsers.add_parser("dry-run")
    dry_run_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help=(
            "Deprecated no-op: data SQL artifacts are checked and built "
            "by default."
        ),
    )
    dry_run_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help=(
            "Skip data SQL artifact validation for an explicit "
            "schema-only run."
        ),
    )
    dry_run_parser.add_argument("--app-only", action="store_true")

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help="Deprecated no-op: data SQL artifacts are built by default.",
    )
    build_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help=(
            "Skip data SQL artifact generation for an explicit "
            "schema-only build."
        ),
    )

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--build-version", default="")
    deploy_parser.add_argument("--latest", action="store_true")
    deploy_parser.add_argument("--contour", choices=CONTOURS, default="dev")
    deploy_parser.add_argument(
        "--include-set-default-sql",
        action="store_true",
        help=(
            "Include kind=set_default data SQL in the update runner. "
            "Disabled by default."
        ),
    )
    deploy_parser.add_argument("--app-only", action="store_true")

    pipeline_parser = subparsers.add_parser("pipeline")
    pipeline_parser.add_argument("--build-version", default="")
    pipeline_parser.add_argument("--latest", action="store_true")
    pipeline_parser.add_argument("--contour", choices=CONTOURS, default="dev")
    pipeline_parser.add_argument(
        "--include-set-default-sql",
        action="store_true",
        help=(
            "Include kind=set_default data SQL in the update runner. "
            "Disabled by default."
        ),
    )
    pipeline_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help=(
            "Deprecated no-op: data SQL artifacts are checked and built "
            "by default."
        ),
    )
    pipeline_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help=(
            "Skip data SQL artifact validation/generation for an "
            "explicit schema-only run."
        ),
    )
    pipeline_parser.add_argument("--app-only", action="store_true")

    baseline_parser = subparsers.add_parser("set-baseline")
    baseline_parser.add_argument("--contour", choices=CONTOURS, required=True)
    baseline_parser.add_argument("--build-version", default="")
    baseline_parser.add_argument("--backend-commit", default="")

    mark_applied_parser = subparsers.add_parser("mark-applied")
    mark_applied_parser.add_argument(
        "--contour", choices=CONTOURS, required=True
    )
    mark_applied_parser.add_argument("--build-version", required=True)

    mark_failed_parser = subparsers.add_parser("mark-failed")
    mark_failed_parser.add_argument(
        "--contour", choices=CONTOURS, required=True
    )
    mark_failed_parser.add_argument("--build-version", required=True)
    mark_failed_parser.add_argument("--error", required=True)
    return parser.parse_args()


def main() -> int:
    """Запускает выбранную CLI-команду и возвращает process exit code."""
    args = parse_args()
    with tee_output(args.command):
        try:
            request = request_from_args(args)
            if args.command == "dry-run":
                return 0 if dry_run(request) else 1
            if args.command == "build":
                return build(request)
            if args.command == "deploy":
                return deploy(request)
            if args.command == "pipeline":
                return pipeline(request)
            if args.command == "set-baseline":
                return set_baseline(request)
            if args.command == "mark-applied":
                return mark_applied(request)
            if args.command == "mark-failed":
                return mark_failed(request)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
