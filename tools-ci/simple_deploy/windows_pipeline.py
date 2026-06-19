"""Deprecated compatibility shim for legacy Windows runner imports.

The CLI implementation lives in ``simple_deploy.cli.windows_pipeline``. The
historical script path ``tools-ci/tools/windows_pipeline.py`` imports that
module directly; this shim keeps older ``simple_deploy.windows_pipeline``
imports working during the refactor.
"""

from __future__ import annotations

from simple_deploy.cli.windows_pipeline import (
    Tee,
    build,
    create_log_file,
    deploy,
    dry_run,
    main,
    mark_applied,
    mark_failed,
    parse_args,
    pipeline,
    request_from_args,
    set_baseline,
    tee_output,
)

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
