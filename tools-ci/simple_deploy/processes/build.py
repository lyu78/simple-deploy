"""Процесс сборки release package через builder.

Модуль содержит CLI-процесс ``build``: он готовит окружение Windows runner-а,
создает frontend env-файлы и запускает ``builder/create_release.py``. Builder
по-прежнему остается отдельным пакетом, а этот процесс только оркестрирует его
запуск из совместимого CLI.
"""

from __future__ import annotations

import argparse
import sys


def _runner_module():
    """Возвращает compatibility runner с helper-ами build orchestration.

    Ленивый импорт сохраняет старые patch paths ``tools.windows_pipeline.*`` и
    не переносит env/config helper-ы в этом срезе шага 5.
    """
    from simple_deploy import windows_pipeline

    return windows_pipeline


def build(args: argparse.Namespace) -> int:
    """Запускает builder/create_release.py с подготовленным окружением.

    Команда не пишет baseline и не фиксирует deploy state. Она только запускает
    процесс сборки, передавая builder-у флаг ``SIMPLE_DEPLOY_INCLUDE_DATA_SQL``
    согласно CLI-аргументам текущего runner-а.
    """
    runner = _runner_module()
    env = runner.load_env(args.env_file, args.secrets_file, require_secrets=False)
    print("BUILD prepare frontend env files", flush=True)
    runner.prepare_frontend_env_files(env)
    build_env = runner.prepare_build_env(env)
    build_env[runner.INCLUDE_DATA_SQL_ENV] = "1" if runner.data_sql_artifacts_enabled(args) else "0"
    return runner.stream_command(
        [sys.executable, "-u", "create_release.py"],
        cwd=runner.BUILDER_ROOT,
        timeout=args.timeout,
        env=build_env,
    )


__all__ = ["build"]
