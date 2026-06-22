"""Функции deploy для application artifacts в Windows runner-е."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from simple_deploy.core.commands import run_or_raise
from simple_deploy.core.env import require_value
from simple_deploy.core.job_logging import job_log
from simple_deploy.core.ssh import scp_file, sh_quote, ssh_command
from simple_deploy.release.artifacts import Artifact


def management_commands(env: dict[str, str], runtime: dict) -> list[str]:
    """Возвращает runtime management-команды или Django defaults."""
    configured = runtime.get("management_commands", [])
    if configured:
        return configured
    manage_py = require_value(env, "APP_MANAGE_PY_PATH")
    return [
        f"python {sh_quote(manage_py)} migrate --fake",
        f"python {sh_quote(manage_py)} sync_action_role",
    ]


def remote_clean_unpack_command(artifact: Artifact) -> str:
    """Собирает удаленную команду очистки и распаковки artifact-а."""
    target = artifact.extract_path.rstrip("/")
    if target in {"", "/"}:
        raise RuntimeError(
            f"Unsafe extract path for {artifact.name}: {artifact.extract_path}"
        )
    return (
        "set -e; "
        f"target={sh_quote(target)}; "
        f"archive={sh_quote(artifact.remote_archive)}; "
        'case "$target" in ""|"/") '
        'echo "unsafe extract path: $target"; exit 20;; esac; '
        'test -d "$target"; '
        'find "$target" -mindepth 1 -maxdepth 1 ! -name ".env" '
        "-exec rm -rf -- {} +; "
        'tar -xzf "$archive" -C "$target" --strip-components=1'
    )


def upload_app_artifacts(
    env: dict[str, str], artifacts: list[Artifact], remote_dir: str
) -> None:
    """Создает release-каталог и загружает application artifacts."""
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    job_log(f"RUN create remote release dir: {remote_dir}")
    run_or_raise(
        "create remote release dir",
        ssh_command(
            env, app_user, app_host, f"mkdir -p {sh_quote(remote_dir)}", "APP"
        ),
    )
    for artifact in artifacts:
        job_log(
            f"RUN upload {artifact.name}: "
            f"{artifact.local_path} -> {artifact.remote_archive}"
        )
        run_or_raise(
            f"upload {artifact.name}",
            scp_file(
                env,
                artifact.local_path,
                app_user,
                app_host,
                artifact.remote_archive,
            ),
        )


def backup_app_artifacts(
    env: dict[str, str],
    runtime: dict,
    build_version: str,
    artifacts: list[Artifact],
) -> None:
    """Создает tar.gz backup application-каталогов перед распаковкой."""
    if not runtime.get("backup_enabled", False):
        return

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    backup_base = env.get(
        "BACKUP_ROOT_BASE", "/tmp/simple-deploy-backups"
    ).rstrip("/")
    backup_root = f"{backup_base}/{build_version}"
    job_log(f"RUN create backup root: {backup_root}")
    run_or_raise(
        "create backup root",
        ssh_command(
            env, app_user, app_host, f"mkdir -p {sh_quote(backup_root)}", "APP"
        ),
    )
    for artifact in artifacts:
        extract_path = artifact.extract_path.rstrip("/")
        backup_parent = str(PurePosixPath(extract_path).parent)
        backup_name = PurePosixPath(extract_path).name
        backup_archive = f"{backup_root}/{artifact.name}.tar.gz"
        command = (
            f"test -d {sh_quote(artifact.extract_path)} && "
            f"tar -czf {sh_quote(backup_archive)} "
            f"-C {sh_quote(backup_parent)} {sh_quote(backup_name)}"
        )
        job_log(f"RUN backup {artifact.name}: {artifact.extract_path}")
        run_or_raise(
            f"backup {artifact.name}",
            ssh_command(env, app_user, app_host, command, "APP", timeout=120),
        )


def unpack_app_artifact(env: dict[str, str], artifact: Artifact) -> None:
    """Распаковывает один application artifact на APP VM."""
    command = remote_clean_unpack_command(artifact)
    job_log(
        f"RUN unpack {artifact.name}: "
        f"{artifact.remote_archive} -> {artifact.extract_path}"
    )
    run_or_raise(
        f"unpack {artifact.name}",
        ssh_command(
            env,
            require_value(env, "APP_VM_USER"),
            require_value(env, "APP_VM_HOST"),
            command,
            "APP",
            timeout=120,
        ),
    )


def run_service_steps(env: dict[str, str], runtime: dict, phase: str) -> None:
    """Выполняет service steps заданной фазы на APP VM."""
    steps = []
    for step in runtime.get("service_steps", []):
        if step.get("phase", "after_migrate") == phase:
            steps.append(step)
    if not steps:
        job_log(f"SKIP service steps {phase}: empty")
        return
    for step in steps:
        label = step.get("name") or step["command"]
        command = step["command"]
        job_log(f"RUN service {phase}: {label}")
        result = ssh_command(
            env,
            require_value(env, "APP_VM_USER"),
            require_value(env, "APP_VM_HOST"),
            command,
            "APP",
            timeout=120,
        )
        run_or_raise(f"service {phase}: {label}", result)


def deploy_summary_lines(
    build_version: str, release_dir: Path, artifacts: list[Artifact]
) -> list[str]:
    """Формирует строки summary после deploy application artifacts."""
    lines = [
        f"build_version: {build_version}",
        f"release_dir: {release_dir}",
    ]
    for artifact in artifacts:
        lines.append(
            f"{artifact.name}: "
            f"{artifact.local_path} -> {artifact.extract_path}"
        )
    return lines


__all__ = [
    "management_commands",
    "remote_clean_unpack_command",
    "upload_app_artifacts",
    "backup_app_artifacts",
    "unpack_app_artifact",
    "run_service_steps",
    "deploy_summary_lines",
]
