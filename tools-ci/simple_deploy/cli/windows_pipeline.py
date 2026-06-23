"""Windows CLI adapter simple-deploy.

Модуль владеет разбором ``argparse``, tee-логированием команд и dispatch-ем
операторского CLI в application request DTO. Build, deploy, mark и dry-run
поведение намеренно делегируется application layer.
"""

from __future__ import annotations

import argparse
import sys
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
    DEFAULT_SECRETS_FILE,
)
from simple_deploy.core.job_logging import (
    Tee,
    create_log_file,
    tee_output,
)
from simple_deploy.jobs.worker import run_worker_loop
from simple_deploy.registry.state import (
    CONTOURS,
)


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
            "Run the separate kind=set_default data SQL step. "
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
            "Run the separate kind=set_default data SQL step. "
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
    baseline_parser.add_argument(
        "--backend-commit",
        default="",
        help=(
            "Legacy/recovery override. Prefer --build-version or "
            "initial_schema_baselines in runtime config."
        ),
    )

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

    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--once", action="store_true")
    worker_parser.add_argument("--poll-interval", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    """Запускает выбранную CLI-команду и возвращает process exit code."""
    args = parse_args()
    if args.command == "worker":
        try:
            return run_worker_loop(
                once=args.once,
                poll_interval=args.poll_interval,
            )
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

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


__all__ = [
    "Tee",
    "build",
    "create_log_file",
    "deploy",
    "dry_run",
    "main",
    "mark_applied",
    "mark_failed",
    "parse_args",
    "pipeline",
    "request_from_args",
    "set_baseline",
    "tee_output",
]


if __name__ == "__main__":
    raise SystemExit(main())
