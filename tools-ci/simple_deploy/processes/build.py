"""Процесс сборки release package через builder.

Модуль содержит CLI-процесс ``build``: он готовит окружение Windows runner-а,
создает frontend env-файлы и запускает ``builder/create_release.py``. Builder
по-прежнему остается отдельным пакетом, а этот процесс только оркестрирует его
запуск из совместимого CLI.
"""

from __future__ import annotations

import sys

from simple_deploy.application.requests import BuildRequest
from simple_deploy.application.results import ProcessResult
from simple_deploy.core.build_env import (
    data_sql_artifacts_enabled,
    prepare_build_env,
    prepare_frontend_env_files,
)
from simple_deploy.core.commands import stream_command
from simple_deploy.core.env import load_env
from simple_deploy.core.job_logging import job_log
from simple_deploy.core.paths import BUILDER_ROOT, INCLUDE_DATA_SQL_ENV


def build(request: BuildRequest) -> ProcessResult:
    """Запускает builder/create_release.py с подготовленным окружением.

    Команда не пишет baseline и не фиксирует deploy state. Она только запускает
    процесс сборки, передавая builder-у флаг ``SIMPLE_DEPLOY_INCLUDE_DATA_SQL``
    согласно типизированному request текущего runner-а.
    """
    env = load_env(
        request.env_file, request.secrets_file, require_secrets=False
    )
    job_log("BUILD prepare frontend env files")
    prepare_frontend_env_files(env)
    build_env = prepare_build_env(env)
    build_env[INCLUDE_DATA_SQL_ENV] = (
        "1"
        if data_sql_artifacts_enabled(request.skip_data_sql_artifacts)
        else "0"
    )
    exit_code = stream_command(
        [sys.executable, "-u", "create_release.py"],
        cwd=BUILDER_ROOT,
        timeout=request.timeout,
        env=build_env,
    )
    return ProcessResult.from_exit_code(
        exit_code,
        success_message="release bundle build completed",
        failure_message="release bundle build failed",
    )


__all__ = ["build"]
