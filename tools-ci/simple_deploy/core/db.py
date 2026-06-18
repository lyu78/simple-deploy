"""Вспомогательные DB-функции, общие для dry-run и deploy процессов."""

from __future__ import annotations

from simple_deploy.core.env import require_value
from simple_deploy.core.ssh import sh_quote


def db_psql_base_command(
    env: dict[str, str], runtime: dict
) -> tuple[str, list[str]]:
    """Собирает базовую psql-команду и список секретов для маскирования."""
    password = env.get("DB_LOGIN_PASSWORD", "")
    psql_bin = str(runtime.get("db_psql_bin", "psql"))
    psql_host = str(runtime.get("db_psql_host", "localhost"))
    psql_base = (
        f"PGPASSWORD={sh_quote(password)} {sh_quote(psql_bin)} "
        "--set=ON_ERROR_STOP=1 "
        f"--host={sh_quote(psql_host)} "
        f"--port={sh_quote(require_value(env, 'DB_PORT'))} "
        f"--username={sh_quote(env.get('DB_LOGIN_USER', 'postgres'))} "
        f"--dbname={sh_quote(require_value(env, 'DB_NAME'))}"
    )
    return psql_base, [password]


__all__ = ["db_psql_base_command"]
