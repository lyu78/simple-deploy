"""Процессные операции DB schema/data SQL для deploy runner-а.

Модуль отвечает за доставку SQL-артефактов на DB VM, unpack архива, запуск
schema summary SQL, data INSERT, parallel data UPDATE и maintenance SQL.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from simple_deploy.core.commands import run_or_raise
from simple_deploy.core.db import db_psql_base_command
from simple_deploy.core.env import require_value
from simple_deploy.core.job_logging import job_log
from simple_deploy.core.paths import ROOT
from simple_deploy.core.ssh import (
    scp_file,
    sh_quote,
    ssh_command,
    stream_ssh_command,
)
from simple_deploy.release.artifacts import DbSqlArtifact

DB_DATA_UPDATE_APP_NAME = "simple-deploy-data-update"
DB_DATA_UPDATE_PROCESS_CLEANUP_SCRIPT = r"""set -uo pipefail

command -v pgrep >/dev/null 2>&1 || {
  echo "pgrep executable not found"
  exit 2
}

PATTERN='run_all_update_parallel_.*[.]sh|psql .*docs/database/scripts'

print_matches() {
  pgrep -af "$PATTERN" || true
}

read_pids() {
  pgrep -f "$PATTERN" || true
}

matches="$(print_matches)"
if [[ -z "$matches" ]]; then
  echo "No leftover DB data update OS processes"
  exit 0
fi

echo "Found leftover DB data update OS processes:"
printf '%s\n' "$matches"

mapfile -t pids < <(read_pids)
if [[ "${#pids[@]}" -gt 0 ]]; then
  echo "Sending TERM to ${#pids[@]} process(es)"
  kill -TERM "${pids[@]}" 2>/dev/null || true
  sleep 5
fi

mapfile -t remaining < <(read_pids)
if [[ "${#remaining[@]}" -gt 0 ]]; then
  echo "Sending KILL to ${#remaining[@]} process(es)"
  kill -KILL "${remaining[@]}" 2>/dev/null || true
  sleep 1
fi

remaining_matches="$(print_matches)"
if [[ -n "$remaining_matches" ]]; then
  echo "Failed to stop DB data update OS processes:"
  printf '%s\n' "$remaining_matches"
  exit 1
fi

echo "Stopped leftover DB data update OS processes"
"""


def remote_db_sql_unpack_command(artifact: DbSqlArtifact) -> str:
    """
    Строит remote shell-команду безопасного unpack DB SQL архива.

    Функция только формирует строку команды и не обращается к VM. Она
    проверяет, что target path не пустой и не корневой, пересоздает директорию
    распаковки и гарантирует наличие ровно одного entrypoint-файла по pattern
    артефакта.

    """
    return (
        "set -e; "
        f"archive={sh_quote(artifact.remote_archive)}; "
        f"target={sh_quote(artifact.remote_extract_path)}; "
        'case "$target" in ""|"/") echo "unsafe extract path: $target"; '
        "exit 20;; esac; "
        'rm -rf "$target"; '
        'mkdir -p "$target"; '
        'tar -xzf "$archive" -C "$target"; '
        f'entrypoint_dir="$target/{artifact.entrypoint_dir}"; '
        'test -d "$entrypoint_dir"; '
        f'test "$(find "$entrypoint_dir" -maxdepth 1 -type f -name '
        f'{sh_quote(artifact.entrypoint_pattern)} | wc -l)" -eq 1'
    )


def remote_db_schema_unpack_command(artifact: DbSqlArtifact) -> str:
    """Строит remote unpack-команду для schema SQL артефакта.

    Сейчас schema и data SQL архивы распаковываются одинаково, поэтому функция
    оставлена как совместимый alias с говорящим именем для старого runner API.
    """
    return remote_db_sql_unpack_command(artifact)


def upload_unpack_db_sql_artifact(
    env: dict[str, str], artifact: DbSqlArtifact
) -> None:
    """Загружает DB SQL архив на DB VM и распаковывает его.

    Источником истины для remote paths является ``DbSqlArtifact``. Функция не
    применяет SQL к базе: она только создает remote release dir, копирует архив
    через scp и запускает unpack-проверку entrypoint.
    """
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    remote_dir = str(PurePosixPath(artifact.remote_archive).parent)

    job_log(f"RUN create DB remote release dir: {remote_dir}")
    run_or_raise(
        "create DB remote release dir",
        ssh_command(
            env, db_user, db_host, f"mkdir -p {sh_quote(remote_dir)}", "DB"
        ),
    )

    job_log(
        f"RUN upload {artifact.name}: "
        f"{artifact.local_path} -> {artifact.remote_archive}"
    )
    run_or_raise(
        f"upload {artifact.name}",
        scp_file(
            env,
            artifact.local_path,
            db_user,
            db_host,
            artifact.remote_archive,
            scope="DB",
        ),
    )

    job_log(
        f"RUN unpack {artifact.name}: "
        f"{artifact.remote_archive} -> {artifact.remote_extract_path}"
    )
    run_or_raise(
        f"unpack {artifact.name}",
        ssh_command(
            env,
            db_user,
            db_host,
            remote_db_sql_unpack_command(artifact),
            "DB",
            timeout=120,
        ),
    )


def run_db_schema_summary(
    env: dict[str, str], runtime: dict, artifact: DbSqlArtifact
) -> None:
    """
    Применяет schema summary SQL из распакованного schema артефакта.

    Функция сначала доставляет архив через ``upload_unpack_db_sql_artifact``,
    затем запускает найденный entrypoint через ``psql --single-transaction``.
    Baseline контура здесь не меняется: это делает deploy/mark слой только
    после успешного завершения всего процесса.

    """
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    psql_base, mask = db_psql_base_command(env, runtime)

    upload_unpack_db_sql_artifact(env, artifact)

    command = (
        "set -e; "
        f"cd {sh_quote(artifact.remote_extract_path)}; "
        f"sql_file=$(find {sh_quote(artifact.entrypoint_dir)} "
        "-maxdepth 1 -type f "
        f"-name {sh_quote(artifact.entrypoint_pattern)} | sort | tail -n 1); "
        'test -n "$sql_file"; '
        f'{psql_base} --single-transaction -f "$sql_file"'
    )
    job_log(
        "RUN DB schema summary SQL: "
        f"{artifact.remote_extract_path}/{artifact.entrypoint_dir}"
    )
    result = ssh_command(
        env, db_user, db_host, command, "DB", timeout=300, mask=mask
    )
    run_or_raise("DB schema summary SQL", result, mask=mask)


def run_db_data_insert(
    env: dict[str, str], runtime: dict, artifact: DbSqlArtifact
) -> None:
    """Применяет data INSERT SQL из переносимого data SQL артефакта.

    Функция доставляет архив, ищет единственный run_all INSERT entrypoint и
    пишет remote log рядом с распакованным артефактом. Она не двигает baseline:
    успешное применение релиза фиксируется только deploy/mark слоем.
    """
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    psql_base, mask = db_psql_base_command(env, runtime)
    timeout = int(runtime.get("db_data_sql_timeout_seconds", 21600))

    upload_unpack_db_sql_artifact(env, artifact)

    command = (
        "set -e; "
        f"cd {sh_quote(artifact.remote_extract_path)}; "
        f"sql_file=$(find {sh_quote(artifact.entrypoint_dir)} "
        "-maxdepth 1 -type f "
        f"-name {sh_quote(artifact.entrypoint_pattern)} | sort | tail -n 1); "
        'test -n "$sql_file"; '
        'log_dir="logs/insert"; '
        'mkdir -p "$log_dir"; '
        'log_file="$log_dir/$(date +%Y%m%d_%H%M%S)_'
        '$(basename "$sql_file").log"; '
        "start_ts=$(date +%s); "
        f'if {psql_base} -f "$sql_file" > "$log_file" 2>&1; then '
        "end_ts=$(date +%s); "
        "duration=$((end_ts-start_ts)); "
        'printf "DB data insert SQL completed in %ss\\n" "$duration"; '
        "else "
        "rc=$?; "
        "end_ts=$(date +%s); "
        "duration=$((end_ts-start_ts)); "
        'printf "DB data insert SQL failed after %ss; log: %s/%s\\n" '
        '"$duration" "$PWD" "$log_file"; '
        'tail -n 80 "$log_file"; '
        'exit "$rc"; '
        "fi"
    )
    job_log(
        "RUN DB data insert SQL: "
        f"{artifact.remote_extract_path}/{artifact.entrypoint_dir}"
    )
    result = ssh_command(
        env, db_user, db_host, command, "DB", timeout=timeout, mask=mask
    )
    if result.rc == 0:
        detail = (result.stdout or result.stderr).strip()
        job_log(f"PASS {detail or 'DB data insert SQL completed'}")
        return
    run_or_raise("DB data insert SQL", result, mask=mask)


def run_db_data_update_parallel(
    env: dict[str, str],
    runtime: dict,
    artifact: DbSqlArtifact,
    include_set_default_sql: bool = False,
) -> None:
    """Запускает parallel data UPDATE runner на DB VM.

    Функция передает runner-у PostgreSQL env, параметры parallel execution и
    флаг включения ``set_default``. Пароль маскируется в выводе. Baseline не
    меняется, потому что это только один этап deploy-процесса.
    """
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    password = env.get("DB_LOGIN_PASSWORD", "")
    timeout = int(runtime.get("db_data_sql_timeout_seconds", 21600))

    upload_unpack_db_sql_artifact(env, artifact)

    runner_env = {
        "PGHOST": str(runtime.get("db_psql_host", "localhost")),
        "PGPORT": require_value(env, "DB_PORT"),
        "PGUSER": env.get("DB_LOGIN_USER", "postgres"),
        "PGDATABASE": require_value(env, "DB_NAME"),
        "PGPASSWORD": password,
        "PGAPPNAME": DB_DATA_UPDATE_APP_NAME,
        "PSQL_BIN": str(runtime.get("db_psql_bin", "psql")),
        "SIMPLE_DEPLOY_UPDATE_MAX_WORKERS": str(
            runtime.get("db_update_parallel_max_workers", 8)
        ),
        "SIMPLE_DEPLOY_UPDATE_STATUS_INTERVAL_SECONDS": str(
            runtime.get("db_update_parallel_status_interval_seconds", 30)
        ),
        "SIMPLE_DEPLOY_INCLUDE_SET_DEFAULT": "1"
        if include_set_default_sql
        else "0",
    }
    env_prefix = " ".join(
        f"{name}={sh_quote(value)}" for name, value in runner_env.items()
    )
    command = (
        "set -e; "
        f"cd {sh_quote(artifact.remote_extract_path)}; "
        f"runner=$(find {sh_quote(artifact.entrypoint_dir)} "
        "-maxdepth 1 -type f "
        f"-name {sh_quote(artifact.entrypoint_pattern)} | sort | tail -n 1); "
        'test -n "$runner"; '
        'chmod +x "$runner"; '
        f'{env_prefix} bash "$runner"'
    )
    job_log(
        "RUN DB data update parallel: "
        f"{artifact.remote_extract_path}/{artifact.entrypoint_dir}"
    )
    result = stream_ssh_command(
        env,
        db_user,
        db_host,
        command,
        "DB",
        timeout=timeout,
        mask=[password],
    )
    run_or_raise("DB data update parallel", result, mask=[password])


def cleanup_db_data_update_leftovers(
    env: dict[str, str], runtime: dict
) -> None:
    """Очищает зависшие data UPDATE процессы перед новым full deploy.

    Cleanup состоит из двух best-effort этапов с hard fail при неуспехе:
    остановка OS-процессов runner-а на DB VM и завершение PostgreSQL backend-ов
    с application_name ``simple-deploy-data-update``. Baseline не меняется.
    """
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    password = env.get("DB_LOGIN_PASSWORD", "")

    job_log("RUN DB data update preflight cleanup: OS processes")
    process_result = ssh_command(
        env,
        db_user,
        db_host,
        "bash -s",
        "DB",
        input_text=DB_DATA_UPDATE_PROCESS_CLEANUP_SCRIPT,
        timeout=90,
        mask=[password],
    )
    run_or_raise(
        "DB data update OS process cleanup", process_result, mask=[password]
    )

    psql_base, mask = db_psql_base_command(env, runtime)
    sql = f"""
WITH targets AS (
    SELECT pid
    FROM pg_stat_activity
    WHERE datname = current_database()
      AND application_name = '{DB_DATA_UPDATE_APP_NAME}'
      AND pid <> pg_backend_pid()
),
terminated AS (
    SELECT pid, pg_terminate_backend(pid) AS terminated
    FROM targets
)
SELECT 'terminated_backend_count=' || count(*) FILTER (WHERE terminated)
FROM terminated;
"""
    command = f"{psql_base} --tuples-only --no-align --command={sh_quote(sql)}"
    job_log("RUN DB data update preflight cleanup: PostgreSQL backends")
    backend_result = ssh_command(
        env, db_user, db_host, command, "DB", timeout=60, mask=mask
    )
    run_or_raise(
        "DB data update PostgreSQL backend cleanup", backend_result, mask=mask
    )


def run_db_maintenance(env: dict[str, str], runtime: dict, phase: str) -> None:
    """Выполняет inline/file maintenance SQL для указанной deploy-фазы.

    Функция читает SQL scripts относительно корня репозитория runner-а и
    отправляет их в psql через SSH. Maintenance не двигает baseline и считается
    частью общего deploy-процесса.
    """
    if not runtime.get("db_maintenance_enabled", True):
        job_log(f"SKIP DB maintenance {phase}: disabled")
        return

    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    psql_base, mask = db_psql_base_command(env, runtime)
    timeout = int(runtime.get("db_maintenance_sql_timeout_seconds", 900))

    if phase == runtime.get("db_maintenance_sql_phase", "before_unpack"):
        for index, sql in enumerate(
            runtime.get("db_maintenance_sql", []), start=1
        ):
            job_log(f"RUN DB inline SQL {phase} #{index}")
            command = f"{psql_base} --command={sh_quote(sql)}"
            result = ssh_command(
                env,
                db_user,
                db_host,
                command,
                "DB",
                timeout=timeout,
                mask=mask,
            )
            run_or_raise(f"DB inline SQL {phase} #{index}", result, mask=mask)

    for script in runtime.get("sql_scripts", []):
        if script.get("phase") != phase:
            continue
        path = ROOT / script["path"]
        sql = path.read_text(encoding="utf-8")
        job_log(f"RUN DB SQL script {path}")
        result = ssh_command(
            env,
            db_user,
            db_host,
            psql_base,
            "DB",
            input_text=sql,
            timeout=timeout,
            mask=mask,
        )
        run_or_raise(f"DB SQL script {path}", result, mask=mask)


__all__ = [
    "DB_DATA_UPDATE_PROCESS_CLEANUP_SCRIPT",
    "DB_DATA_UPDATE_APP_NAME",
    "cleanup_db_data_update_leftovers",
    "remote_db_schema_unpack_command",
    "remote_db_sql_unpack_command",
    "run_db_data_insert",
    "run_db_data_update_parallel",
    "run_db_maintenance",
    "run_db_schema_summary",
    "upload_unpack_db_sql_artifact",
]
