"""Ручные процессы фиксации результата релиза на контуре.

Модуль отвечает за команды ``set-baseline``, ``mark-applied`` и
``mark-failed``, а также за низкоуровневую фиксацию успешной или неуспешной
deploy-попытки. Источники истины разделены явно: backend commit читается из
переносимого ``release_manifest.json``, а текущее состояние контуров и история
попыток пишутся в локальную SQLite-базу.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from simple_deploy.core.env import load_env
from simple_deploy.core.release_paths import resolve_release_dir
from simple_deploy.registry.commands import (
    record_deployment_applied,
    record_deployment_failed,
    set_contour_baseline,
)
from simple_deploy.registry.state import validate_contour
from simple_deploy.release.manifest import release_backend_commit


def mark_contour_applied(
    contour: str, build_version: str, release_dir: Path
) -> None:
    """Фиксирует успешное применение релиза и двигает baseline.

    Backend commit берется из ``release_manifest.json`` выбранного релиза.
    Функция делегирует запись ``contour_state`` и ``deployment_attempts`` в
    ``simple_deploy.registry.commands``.
    """
    backend_commit = release_backend_commit(release_dir)
    result = record_deployment_applied(contour, build_version, backend_commit)
    print(
        f"MARK applied: contour={result.contour} "
        f"build_version={result.build_version} "
        f"backend_commit={result.backend_commit}",
        flush=True,
    )


def mark_contour_failed(
    contour: str, build_version: str, release_dir: Path, error_text: str
) -> None:
    """Записывает неуспешную попытку применения без изменения baseline.

    Если manifest недоступен или поврежден, failed attempt все равно пишется с
    пустым backend commit. Это важно для ручной фиксации отказа TEST/PROD, где
    переносимый пакет мог быть неполным.
    """
    try:
        backend_commit = release_backend_commit(release_dir)
    except Exception:
        backend_commit = ""
    result = record_deployment_failed(
        contour, build_version, backend_commit, error_text
    )
    print(
        f"MARK failed: contour={result.contour} "
        f"build_version={result.build_version} "
        f"backend_commit={result.backend_commit}",
        flush=True,
    )


def mark_contour_failed_best_effort(
    contour: str, build_version: str, release_dir: Path, error: Exception
) -> None:
    """
    Пишет failed deploy attempt, не маскируя исходную deploy-ошибку.

    Это best-effort helper для deploy: если запись failed attempt сама падает,
    ошибка только выводится в лог, а исходное исключение deploy остается
    главным результатом процесса.

    """
    try:
        mark_contour_failed(contour, build_version, release_dir, str(error))
    except Exception as record_error:
        print(
            f"WARN failed to record failed deploy attempt: "
            f"contour={contour} build_version={build_version} "
            f"error={record_error}",
            flush=True,
        )


def set_baseline(args: argparse.Namespace) -> int:
    """
    Устанавливает baseline контура по build version или явному backend commit.

    Команда двигает ``contour_state``, но не пишет ``deployment_attempts``:
    baseline здесь задается оператором как начальная точка для будущих offline
    SQL ranges, а не как результат deploy-попытки.

    """
    print("BASELINE load config", flush=True)
    env = load_env(args.env_file, args.secrets_file, require_secrets=False)
    contour = validate_contour(args.contour)
    if args.backend_commit:
        build_version = args.build_version or "manual-baseline"
        backend_commit = args.backend_commit.strip()
    else:
        build_version, release_dir = resolve_release_dir(
            env, args.build_version, latest=False
        )
        backend_commit = release_backend_commit(release_dir)
    result = set_contour_baseline(contour, build_version, backend_commit)
    print(
        f"BASELINE set: contour={result.contour} "
        f"build_version={result.build_version} "
        f"backend_commit={result.backend_commit}",
        flush=True,
    )
    return 0


def mark_applied(args: argparse.Namespace) -> int:
    """CLI-обертка для фиксации успешного применения релиза.

    Команда читает release dir через текущий runner contract и затем вызывает
    ``mark_contour_applied``. Baseline двигается только после успешного чтения
    backend commit из manifest.
    """
    print("MARK-APPLIED load config", flush=True)
    env = load_env(args.env_file, args.secrets_file, require_secrets=False)
    build_version, release_dir = resolve_release_dir(
        env, args.build_version, latest=False
    )
    mark_contour_applied(args.contour, build_version, release_dir)
    return 0


def mark_failed(args: argparse.Namespace) -> int:
    """CLI-обертка для фиксации неуспешного применения релиза.

    Команда пишет failed attempt и не меняет baseline контура. Текст ошибки
    берется из CLI-аргумента ``--error`` без дополнительной нормализации.
    """
    print("MARK-FAILED load config", flush=True)
    env = load_env(args.env_file, args.secrets_file, require_secrets=False)
    build_version, release_dir = resolve_release_dir(
        env, args.build_version, latest=False
    )
    mark_contour_failed(args.contour, build_version, release_dir, args.error)
    return 0


__all__ = [
    "mark_applied",
    "mark_contour_applied",
    "mark_contour_failed",
    "mark_contour_failed_best_effort",
    "mark_failed",
    "set_baseline",
]
