"""Процесс сборки release package через builder.

Модуль содержит CLI-процесс ``build``: он готовит окружение Windows runner-а,
создает frontend env-файлы и запускает ``builder/create_release.py``. Builder
по-прежнему остается отдельным пакетом, а этот процесс только оркестрирует его
запуск из совместимого CLI.
"""

from __future__ import annotations

import argparse
import sys

from simple_deploy.core.build_env import (
    data_sql_artifacts_enabled,
    prepare_build_env,
    prepare_frontend_env_files,
)
from simple_deploy.core.commands import stream_command
from simple_deploy.core.env import load_env
from simple_deploy.core.paths import BUILDER_ROOT, INCLUDE_DATA_SQL_ENV


def build(args: argparse.Namespace) -> int:
    """Запускает builder/create_release.py с подготовленным окружением.

    Команда не пишет baseline и не фиксирует deploy state. Она только запускает
    процесс сборки, передавая builder-у флаг ``SIMPLE_DEPLOY_INCLUDE_DATA_SQL``
    согласно CLI-аргументам текущего runner-а.
    """
    env = load_env(args.env_file, args.secrets_file, require_secrets=False)
    print("BUILD prepare frontend env files", flush=True)
    prepare_frontend_env_files(env)
    build_env = prepare_build_env(env)
    build_env[INCLUDE_DATA_SQL_ENV] = (
        "1" if data_sql_artifacts_enabled(args) else "0"
    )
    return stream_command(
        [sys.executable, "-u", "create_release.py"],
        cwd=BUILDER_ROOT,
        timeout=args.timeout,
        env=build_env,
    )


__all__ = ["build"]
