"""Application services для release/deploy команд.

Сервисный слой отделяет внешние adapters от операторских процессов:

* CLI adapter отвечает за ``argparse``, лог-файл и dispatch;
* web/API или local job runner смогут вызывать те же функции без импорта
  ``tools.windows_pipeline``;
* process modules пока остаются владельцами подробной orchestration-логики
  build/deploy/mark.

Функции принимают ``argparse.Namespace`` для совместимости с текущим CLI contract.
Когда появятся request DTO для web/API, этот модуль станет местом преобразования
DTO в process input, а не HTTP или registry layer.
"""

from __future__ import annotations

import argparse

from simple_deploy.processes.build import build as _build_process
from simple_deploy.processes.deploy import deploy as _deploy_process
from simple_deploy.processes.mark import (
    mark_applied as _mark_applied_process,
    mark_failed as _mark_failed_process,
    set_baseline as _set_baseline_process,
)


def build(args: argparse.Namespace) -> int:
    """Запускает application use case сборки release bundle."""

    return _build_process(args)


def deploy(args: argparse.Namespace) -> int:
    """Запускает application use case применения release bundle на контур."""

    return _deploy_process(args)


def set_baseline(args: argparse.Namespace) -> int:
    """Запускает application use case ручной установки baseline контура."""

    return _set_baseline_process(args)


def mark_applied(args: argparse.Namespace) -> int:
    """Запускает application use case ручной фиксации успешного deploy."""

    return _mark_applied_process(args)


def mark_failed(args: argparse.Namespace) -> int:
    """Запускает application use case ручной фиксации неуспешного deploy."""

    return _mark_failed_process(args)


__all__ = [
    "build",
    "deploy",
    "mark_applied",
    "mark_failed",
    "set_baseline",
]
