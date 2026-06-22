"""Deploy-процесс совместимого Windows runner-а.

Модуль содержит верхнеуровневую orchestration-функцию ``deploy``: загрузку
runtime/env, выбор релиза, доставку app/db артефактов, порядок service steps,
schema/data SQL, management commands, healthcheck, фиксацию state и email.
"""

from __future__ import annotations

from simple_deploy.application.requests import DeployRequest
from simple_deploy.application.results import ProcessResult
from simple_deploy.config.runtime_loader import load_runtime_config
from simple_deploy.core.commands import run_or_raise
from simple_deploy.core.env import load_env, require_value
from simple_deploy.core.job_logging import job_log
from simple_deploy.core.release_paths import resolve_release_dir
from simple_deploy.core.ssh import sh_quote, ssh_command
from simple_deploy.processes.app_deploy import (
    backup_app_artifacts,
    deploy_summary_lines,
    management_commands,
    run_service_steps,
    unpack_app_artifact,
    upload_app_artifacts,
)
from simple_deploy.processes.data_sql import (
    cleanup_db_data_update_leftovers,
    run_db_data_insert,
    run_db_data_set_default_parallel,
    run_db_data_update_parallel,
    run_db_maintenance,
    run_db_schema_summary,
)
from simple_deploy.processes.healthcheck import (
    healthcheck,
    verify_maintenance_stub_http,
)
from simple_deploy.processes.mark import (
    mark_contour_applied,
    mark_contour_failed_best_effort,
)
from simple_deploy.processes.notifications import send_outlook_success_email
from simple_deploy.registry.state import validate_contour
from simple_deploy.release.artifacts import (
    require_artifact,
    resolve_artifacts,
    resolve_db_data_artifact,
    resolve_db_schema_artifact,
    resolve_maintenance_stub_artifact,
)


def deploy(request: DeployRequest) -> ProcessResult:
    """
    Выполняет deploy выбранного релиза на указанный контур.

    Baseline двигается только после успешного healthcheck и вызова
    ``mark_contour_applied``. Если deploy падает до успешной фиксации state,
    failed attempt пишется best-effort через
    ``mark_contour_failed_best_effort``.

    """
    job_log("DEPLOY load config")
    app_only = request.app_only
    env = load_env(
        request.env_file,
        request.secrets_file,
        require_secrets=not app_only,
    )
    runtime, _defaulted_runtime_keys = load_runtime_config(
        request.config_file
    )
    build_version, release_dir = resolve_release_dir(
        env, request.build_version, request.latest
    )
    contour = validate_contour(request.contour.value)
    job_log(f"DEPLOY build_version: {build_version}")
    job_log(f"DEPLOY contour: {contour}")
    job_log(f"DEPLOY release_dir: {release_dir}")
    job_log(f"DEPLOY mode: {'app-only' if app_only else 'full'}")

    success_recorded = False
    try:
        artifacts = resolve_artifacts(env, build_version, release_dir)
        app_user = require_value(env, "APP_VM_USER")
        app_host = require_value(env, "APP_VM_HOST")
        remote_tmp_root = require_value(env, "REMOTE_TMP_ROOT").rstrip("/")
        remote_dir = f"{remote_tmp_root}/{build_version}"

        if not app_only:
            cleanup_db_data_update_leftovers(env, runtime)

        if app_only:
            job_log("SKIP DB steps: app-only mode")
            app_upload_artifacts = artifacts
            backend_artifact = None
            frontend_artifact = None
            maintenance_stub_artifact = None
            db_schema_artifact = None
            db_insert_artifact = None
            db_update_parallel_artifact = None
            db_set_default_parallel_artifact = None
        else:
            backend_artifact = require_artifact(artifacts, "backend")
            frontend_artifact = require_artifact(artifacts, "frontend")
            db_schema_artifact = resolve_db_schema_artifact(
                env, build_version, release_dir, contour
            )
            if runtime.get("data_sql_enabled", True):
                db_insert_artifact = resolve_db_data_artifact(
                    env, build_version, release_dir, "insert"
                )
                db_update_parallel_artifact = resolve_db_data_artifact(
                    env,
                    build_version,
                    release_dir,
                    "update_parallel",
                )
                if request.include_set_default_sql:
                    db_set_default_parallel_artifact = (
                        resolve_db_data_artifact(
                            env,
                            build_version,
                            release_dir,
                            "set_default_parallel",
                        )
                    )
                else:
                    db_set_default_parallel_artifact = None
            else:
                db_insert_artifact = None
                db_update_parallel_artifact = None
                db_set_default_parallel_artifact = None
                job_log("SKIP DB data SQL artifacts: disabled")
            if runtime.get("maintenance_stub_enabled", True):
                maintenance_stub_artifact = resolve_maintenance_stub_artifact(
                    env, runtime, build_version
                )
            else:
                maintenance_stub_artifact = None
                job_log("SKIP maintenance stub: disabled")
            app_upload_artifacts = [
                artifact
                for artifact in (
                    backend_artifact,
                    frontend_artifact,
                    maintenance_stub_artifact,
                )
                if artifact is not None
            ]

        upload_app_artifacts(env, app_upload_artifacts, remote_dir)
        backup_app_artifacts(env, runtime, build_version, artifacts)

        run_service_steps(env, runtime, "before_unpack")

        if app_only:
            for artifact in artifacts:
                unpack_app_artifact(env, artifact)
        else:
            if maintenance_stub_artifact is not None:
                unpack_app_artifact(env, maintenance_stub_artifact)
                verify_maintenance_stub_http(env, runtime)
            else:
                job_log("SKIP maintenance stub unpack: disabled")

            run_db_schema_summary(env, runtime, db_schema_artifact)
            if db_insert_artifact is not None:
                run_db_data_insert(env, runtime, db_insert_artifact)
            if db_update_parallel_artifact is not None:
                run_db_data_update_parallel(
                    env,
                    runtime,
                    db_update_parallel_artifact,
                )
            if db_set_default_parallel_artifact is not None:
                run_db_data_set_default_parallel(
                    env,
                    runtime,
                    db_set_default_parallel_artifact,
                )
            for phase in ("before_unpack", "before_migrate", "after_migrate"):
                run_db_maintenance(env, runtime, phase)

            unpack_app_artifact(env, backend_artifact)

        run_service_steps(env, runtime, "after_unpack")

        for command in management_commands(env, runtime):
            app_workdir = sh_quote(require_value(env, "APP_WORKDIR"))
            app_venv = sh_quote(require_value(env, "APP_VENV_ACTIVATE_PATH"))
            remote = (
                f"cd {app_workdir} && "
                f". {app_venv} && "
                f"{command}"
            )
            job_log(f"RUN management command: {command}")
            run_or_raise(
                f"management command: {command}",
                ssh_command(
                    env, app_user, app_host, remote, "APP", timeout=300
                ),
            )

        run_service_steps(env, runtime, "after_migrate")

        if not app_only:
            unpack_app_artifact(env, frontend_artifact)
            run_service_steps(env, runtime, "after_frontend_unpack")

        if runtime.get("healthcheck_enabled", True):
            healthcheck(env, runtime, build_version)
        else:
            job_log("SKIP healthcheck: disabled")

        mark_contour_applied(contour, build_version, release_dir)
        success_recorded = True

        job_log("DEPLOY SUMMARY")
        for line in deploy_summary_lines(
            build_version, release_dir, artifacts
        ):
            job_log(line)

        send_outlook_success_email(
            env, runtime, build_version, release_dir, artifacts
        )
    except Exception as exc:
        if not success_recorded:
            mark_contour_failed_best_effort(
                contour, build_version, release_dir, exc
            )
        else:
            job_log(
                f"WARN deploy failed after successful state update: "
                f"contour={contour} build_version={build_version} error={exc}"
            )
        raise
    return ProcessResult.success(
        "deploy completed",
        build_version=build_version,
        contour=request.contour,
    )


__all__ = ["deploy"]
