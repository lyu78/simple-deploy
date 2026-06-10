"""Deploy-процесс совместимого Windows runner-а.

Модуль содержит верхнеуровневую orchestration-функцию ``deploy``: загрузку
runtime/env, выбор релиза, доставку app/db артефактов, порядок service steps,
schema/data SQL, management commands, healthcheck, фиксацию state и email. На
этом срезе helper-ы остаются в compatibility runner-е, чтобы перенос deploy не
смешивался с переносом core/SSH/app helpers.
"""

from __future__ import annotations

import argparse


def _runner_module():
    """Возвращает compatibility runner с helper-ами deploy orchestration.

    Ленивый импорт сохраняет старый public API ``tools.windows_pipeline.deploy``
    и все существующие patch paths вокруг app/db/service helper-ов.
    """
    from simple_deploy import windows_pipeline

    return windows_pipeline


def deploy(args: argparse.Namespace) -> int:
    """Выполняет deploy выбранного релиза на указанный контур.

    Baseline двигается только после успешного healthcheck и вызова
    ``mark_contour_applied``. Если deploy падает до успешной фиксации state,
    failed attempt пишется best-effort через ``mark_contour_failed_best_effort``.
    """
    runner = _runner_module()
    print("DEPLOY load config", flush=True)
    app_only = bool(getattr(args, "app_only", False))
    env = runner.load_env(args.env_file, args.secrets_file, require_secrets=not app_only)
    runtime, _defaulted_runtime_keys = runner.load_runtime_config(args.config_file)
    build_version, release_dir = runner.resolve_release_dir(env, args.build_version, args.latest)
    contour = runner.validate_contour(args.contour)
    print(f"DEPLOY build_version: {build_version}", flush=True)
    print(f"DEPLOY contour: {contour}", flush=True)
    print(f"DEPLOY release_dir: {release_dir}", flush=True)
    print(f"DEPLOY mode: {'app-only' if app_only else 'full'}", flush=True)

    success_recorded = False
    try:
        artifacts = runner.resolve_artifacts(env, build_version, release_dir)
        app_user = runner.require_value(env, "APP_VM_USER")
        app_host = runner.require_value(env, "APP_VM_HOST")
        remote_dir = f"{runner.require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"

        if not app_only:
            runner.cleanup_db_data_update_leftovers(env, runtime)

        if app_only:
            print("SKIP DB steps: app-only mode", flush=True)
            app_upload_artifacts = artifacts
            backend_artifact = None
            frontend_artifact = None
            maintenance_stub_artifact = None
            db_schema_artifact = None
            db_insert_artifact = None
            db_update_parallel_artifact = None
        else:
            backend_artifact = runner.require_artifact(artifacts, "backend")
            frontend_artifact = runner.require_artifact(artifacts, "frontend")
            db_schema_artifact = runner.resolve_db_schema_artifact(env, build_version, release_dir, contour)
            if runtime.get("data_sql_enabled", True):
                db_insert_artifact = runner.resolve_db_data_artifact(env, build_version, release_dir, "insert")
                db_update_parallel_artifact = runner.resolve_db_data_artifact(
                    env,
                    build_version,
                    release_dir,
                    "update_parallel",
                )
            else:
                db_insert_artifact = None
                db_update_parallel_artifact = None
                print("SKIP DB data SQL artifacts: disabled", flush=True)
            if runtime.get("maintenance_stub_enabled", True):
                maintenance_stub_artifact = runner.resolve_maintenance_stub_artifact(env, runtime, build_version)
            else:
                maintenance_stub_artifact = None
                print("SKIP maintenance stub: disabled", flush=True)
            app_upload_artifacts = [
                artifact
                for artifact in (backend_artifact, frontend_artifact, maintenance_stub_artifact)
                if artifact is not None
            ]

        runner.upload_app_artifacts(env, app_upload_artifacts, remote_dir)
        runner.backup_app_artifacts(env, runtime, build_version, artifacts)

        runner.run_service_steps(env, runtime, "before_unpack")

        if app_only:
            for artifact in artifacts:
                runner.unpack_app_artifact(env, artifact)
        else:
            if maintenance_stub_artifact is not None:
                runner.unpack_app_artifact(env, maintenance_stub_artifact)
                runner.verify_maintenance_stub_http(env, runtime)
            else:
                print("SKIP maintenance stub unpack: disabled", flush=True)

            runner.run_db_schema_summary(env, runtime, db_schema_artifact)
            if db_insert_artifact is not None:
                runner.run_db_data_insert(env, runtime, db_insert_artifact)
            if db_update_parallel_artifact is not None:
                runner.run_db_data_update_parallel(
                    env,
                    runtime,
                    db_update_parallel_artifact,
                    include_set_default_sql=getattr(args, "include_set_default_sql", False),
                )
            for phase in ("before_unpack", "before_migrate", "after_migrate"):
                runner.run_db_maintenance(env, runtime, phase)

            runner.unpack_app_artifact(env, backend_artifact)

        runner.run_service_steps(env, runtime, "after_unpack")

        for command in runner.management_commands(env, runtime):
            remote = (
                f"cd {runner.sh_quote(runner.require_value(env, 'APP_WORKDIR'))} && "
                f". {runner.sh_quote(runner.require_value(env, 'APP_VENV_ACTIVATE_PATH'))} && "
                f"{command}"
            )
            print(f"RUN management command: {command}", flush=True)
            runner.run_or_raise(
                f"management command: {command}",
                runner.ssh_command(env, app_user, app_host, remote, "APP", timeout=300),
            )

        runner.run_service_steps(env, runtime, "after_migrate")

        if not app_only:
            runner.unpack_app_artifact(env, frontend_artifact)
            runner.run_service_steps(env, runtime, "after_frontend_unpack")

        if runtime.get("healthcheck_enabled", True):
            runner.healthcheck(env, runtime, build_version)
        else:
            print("SKIP healthcheck: disabled")

        runner.mark_contour_applied(contour, build_version, release_dir)
        success_recorded = True

        print("DEPLOY SUMMARY")
        for line in runner.deploy_summary_lines(build_version, release_dir, artifacts):
            print(line)

        runner.send_outlook_success_email(env, runtime, build_version, release_dir, artifacts)
    except Exception as exc:
        if not success_recorded:
            runner.mark_contour_failed_best_effort(contour, build_version, release_dir, exc)
        else:
            print(
                f"WARN deploy failed after successful state update: "
                f"contour={contour} build_version={build_version} error={exc}",
                flush=True,
            )
        raise
    return 0


__all__ = ["deploy"]
