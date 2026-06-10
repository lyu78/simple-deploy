"""Windows-only runner для simple-deploy.

Модуль является основной операторской точкой входа на рабочей Windows-машине.
Он повторяет ключевые этапы Ansible-flow без обязательного WSL: читает
локальные ``.env``/``local.secrets.env``/``windows_pipeline.local.json``,
запускает build, доставляет артефакты на VM через Windows OpenSSH, выполняет
SQL/management/service steps и проверяет healthcheck.

Для SQL schema migrations runner также ведет локальную историю контуров через
SQLite: команды ``set-baseline``, ``mark-applied`` и ``mark-failed`` фиксируют,
с какого backend commit нужно строить следующий диапазон ``from -> to`` для
DEV/TEST/PROD. Сам runner не считает сборку релиза успешным применением:
baseline двигается только после подтвержденного deploy или явной команды
оператора.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shlex
import shutil
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib import error, parse, request

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
TOOLS_CI_ROOT = ROOT / "tools-ci"
BUILDER_ROOT = TOOLS_CI_ROOT / "builder"

from simple_deploy.release.state import (  # noqa: E402
    CONTOURS,
    validate_contour,
)
from simple_deploy.release.artifacts import (  # noqa: E402
    DEFAULT_MAINTENANCE_STUB_ARCHIVE,
    Artifact,
    DbSqlArtifact,
    require_artifact,
    resolve_artifacts,
    resolve_db_data_artifact,
    resolve_db_schema_artifact,
    resolve_maintenance_stub_artifact,
)
from simple_deploy.release.manifest import (  # noqa: E402
    RELEASE_MANIFEST_NAME,
    find_previous_release_manifest,
    load_release_manifest,
)
from simple_deploy.processes.data_sql import (  # noqa: E402
    DB_DATA_UPDATE_PROCESS_CLEANUP_SCRIPT,
    cleanup_db_data_update_leftovers,
    remote_db_schema_unpack_command,
    remote_db_sql_unpack_command,
    run_db_data_insert,
    run_db_data_update_parallel,
    run_db_maintenance,
    run_db_schema_summary,
    upload_unpack_db_sql_artifact,
)
from simple_deploy.processes.mark import (  # noqa: E402
    mark_applied,
    mark_contour_applied,
    mark_contour_failed,
    mark_contour_failed_best_effort,
    mark_failed,
    set_baseline,
)
from simple_deploy.processes.build import build  # noqa: E402
from simple_deploy.processes.dry_run import dry_run, required_env_keys  # noqa: E402

DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_SECRETS_FILE = ROOT / "local.secrets.env"
DEFAULT_CONFIG_FILE = ROOT / "windows_pipeline.local.json"
DEFAULT_LOG_DIR = ROOT / "logs"
DEFAULT_TIMEOUT = 20
DEFAULT_BACKEND_APP_ROOT_DIR = "example_backend_app"
PIP_TRUSTED_HOSTS = "pypi.org files.pythonhosted.org pypi.python.org"
INCLUDE_DATA_SQL_ENV = "SIMPLE_DEPLOY_INCLUDE_DATA_SQL"
DB_DATA_UPDATE_APP_NAME = "simple-deploy-data-update"
DATABASE_SCRIPTS_PREFIX = Path("docs/database/scripts")
DATA_SQL_INSERT_DIRS = ("app_ip_subcompany_catalogs",)
DATA_SQL_MIXED_DIRS = (
    "app_ip_subcompany",
    "app_ip_subcompany_cc",
    "app_ip_subcompany_onna",
    "app_ip_subcompany_prw",
)
DATA_SQL_INSERT_IF_MISSING_DIRS = ("insert_new_objects",)


@dataclass(frozen=True)
class SqlBusinessKey:
    columns: tuple[str, ...]
    ignore_blank: bool = False


@dataclass(frozen=True)
class SqlInsertRow:
    table: str
    columns: tuple[str, ...]
    values: tuple[str | None, ...]
    line: int


@dataclass(frozen=True)
class SqlValidationProblem:
    path: Path
    rule: str
    detail: str


CATALOG_BUSINESS_KEYS: dict[str, tuple[SqlBusinessKey, ...]] = {
    "app_ip_subcompany_catalog_contractsubject": (SqlBusinessKey(("title",)),),
    "app_ip_subcompany_catalog_contracttype": (SqlBusinessKey(("title",)),),
    "app_ip_subcompany_catalog_region": (SqlBusinessKey(("code",)),),
    "app_ip_subcompany_catalog_contractor": (SqlBusinessKey(("tin",), ignore_blank=True),),
}


DEFAULT_RUNTIME_CONFIG = {
    "backup_enabled": False,
    "maintenance_stub_enabled": True,
    "maintenance_stub_archive_path": DEFAULT_MAINTENANCE_STUB_ARCHIVE,
    "maintenance_stub_verify_enabled": True,
    "maintenance_stub_verify_marker": "Плановые технические работы",
    "maintenance_stub_verify_retries": 10,
    "maintenance_stub_verify_delay": 2,
    "data_sql_enabled": True,
    "db_maintenance_enabled": True,
    "db_psql_bin": "psql",
    "db_psql_host": "localhost",
    "db_maintenance_sql_phase": "after_migrate",
    "db_maintenance_sql": ["VACUUM ANALYZE;"],
    "db_maintenance_sql_timeout_seconds": 900,
    "db_data_sql_timeout_seconds": 21600,
    "db_update_parallel_max_workers": 8,
    "db_update_parallel_status_interval_seconds": 30,
    "sql_scripts": [],
    "management_commands": [],
    "service_permission_checks_enabled": True,
    "service_steps": [],
    "healthcheck_enabled": True,
    "healthcheck_validate_certs": False,
    "healthcheck_retries": 30,
    "healthcheck_delay": 5,
    "portal_version_check_enabled": True,
    "portal_version_asset_limit": 20,
    "healthcheck_commands": [],
    "outlook_email_enabled": False,
    "outlook_email_recipients": [],
    "outlook_email_cc": [],
    "outlook_email_subject": "Деплой успешно завершен: {build_version}",
    "outlook_email_body": (
        "Деплой успешно завершен.\n\n"
        "Версия сборки: {build_version}\n"
        "Стенд: {stand_url}\n"
        "Каталог релиза: {release_dir}\n\n"
        "Артефакты:\n{artifacts_text}\n\n"
        "Изменения с предыдущего релиза:\n{release_changelog_text}"
    ),
    "outlook_email_required": False,
}

DB_MAINTENANCE_PHASES = {"before_unpack", "before_migrate", "after_migrate"}
SERVICE_PHASES = {"before_unpack", "after_unpack", "after_migrate", "after_frontend_unpack"}
NGINX_SERVICE_TARGETS = {"nginx", "nginx.service"}
NGINX_STOP_START_ACTIONS = {"stop", "start"}
NGINX_UNSUPPORTED_ACTIONS = {
    "restart",
    "reload",
    "try-restart",
    "reload-or-restart",
    "reload-or-try-restart",
}
RUNTIME_BOOL_FIELDS = (
    "backup_enabled",
    "maintenance_stub_enabled",
    "maintenance_stub_verify_enabled",
    "data_sql_enabled",
    "db_maintenance_enabled",
    "service_permission_checks_enabled",
    "healthcheck_enabled",
    "healthcheck_validate_certs",
    "portal_version_check_enabled",
    "outlook_email_enabled",
    "outlook_email_required",
)
RUNTIME_POSITIVE_INT_FIELDS = (
    "db_maintenance_sql_timeout_seconds",
    "db_data_sql_timeout_seconds",
    "db_update_parallel_max_workers",
    "db_update_parallel_status_interval_seconds",
    "maintenance_stub_verify_retries",
    "maintenance_stub_verify_delay",
    "healthcheck_retries",
    "healthcheck_delay",
    "portal_version_asset_limit",
)


@dataclass
class CommandResult:
    rc: int
    stdout: str
    stderr: str


class Reporter:
    def __init__(self) -> None:
        self.issues: list[str] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []

    def pass_(self, name: str, detail: str = "") -> None:
        suffix = f": {detail}" if detail else ""
        print(f"DRY-RUN PASS {name}{suffix}")

    def fail(self, name: str, detail: str) -> None:
        print(f"DRY-RUN FAIL {name}: {detail}")
        self.issues.append(f"{name}: {detail}")

    def warn(self, name: str, detail: str) -> None:
        print(f"DRY-RUN WARN {name}: {detail}")
        self.warnings.append(f"{name}: {detail}")

    def skip(self, name: str, reason: str) -> None:
        print(f"DRY-RUN SKIP {name}: {reason}")
        self.skipped.append(f"{name}: {reason}")

    def result(self) -> bool:
        status = "FAIL" if self.issues else "PASS"
        print(f"DRY RUN RESULT: {status}")
        if self.skipped:
            print("skipped_checks:")
            for skipped in self.skipped:
                print(f"- {skipped}")
        if self.warnings:
            print("warnings:")
            for warning in self.warnings:
                print(f"- {warning}")
        if self.issues:
            print("failed_checks:")
            for issue in self.issues:
                print(f"- {issue}")
        return not self.issues


class ScriptSrcParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.srcs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        for name, value in attrs:
            if name.lower() == "src" and value:
                self.srcs.append(value)


class Tee:
    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, text: str) -> int:
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def create_log_file(command: str) -> Path:
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    safe_command = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in command or "run")
    return DEFAULT_LOG_DIR / f"{timestamp}-{safe_command}.log"


@contextlib.contextmanager
def tee_output(command: str):
    log_path = create_log_file(command)
    with log_path.open("w", encoding="utf-8") as log_file:
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = Tee(original_stdout, log_file)
        sys.stderr = Tee(original_stderr, log_file)
        try:
            print(f"RUN LOG {log_path}", flush=True)
            yield log_path
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr


def decode_subprocess_output(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "cp1251", "cp866"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def mask_text(text: str, mask: Iterable[str] = ()) -> str:
    masked = text
    for secret in mask:
        if secret:
            masked = masked.replace(secret, "***")
    return masked


def run_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    mask: Iterable[str] = (),
) -> CommandResult:
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            input=input_text.encode("utf-8") if input_text is not None else None,
            env=env,
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = decode_subprocess_output(exc.stdout)
        stderr = decode_subprocess_output(exc.stderr)
        return CommandResult(124, stdout, stderr or f"timeout after {timeout}s")

    stdout = decode_subprocess_output(completed.stdout)
    stderr = decode_subprocess_output(completed.stderr)
    stdout = mask_text(stdout, mask)
    stderr = mask_text(stderr, mask)
    return CommandResult(completed.returncode, stdout, stderr)


def stream_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
    mask: Iterable[str] = (),
) -> int:
    mask_values = tuple(mask)
    printable_args = [mask_text(str(arg), mask_values) for arg in args]
    print(f"RUN {' '.join(printable_args)}", flush=True)
    process = subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    start = time.monotonic()
    try:
        assert process.stdout is not None
        for line in process.stdout:
            print(mask_text(decode_subprocess_output(line), mask_values), end="", flush=True)
            if timeout is not None and time.monotonic() - start > timeout:
                process.kill()
                print(f"ERROR: timeout after {timeout}s", file=sys.stderr, flush=True)
                return 124
        return process.wait()
    finally:
        if process.stdout is not None:
            process.stdout.close()


def load_dotenv_file(path: Path, required: bool) -> dict[str, str]:
    if not path.exists():
        if required:
            raise RuntimeError(f"Файл не найден: {path}")
        return {}
    return {k.lstrip("\ufeff"): v for k, v in dotenv_values(path).items() if v is not None}


def load_env(env_file: Path, secrets_file: Path, require_secrets: bool) -> dict[str, str]:
    config = load_dotenv_file(env_file, required=True)
    secrets = load_dotenv_file(secrets_file, required=require_secrets)
    merged = {**config, **secrets}

    if require_secrets:
        db_user = merged.get("DB_LOGIN_USER", "").strip()
        db_password = merged.get("DB_LOGIN_PASSWORD", "").strip()
        if not db_user:
            raise RuntimeError("DB_LOGIN_USER must be set in local.secrets.env")
        if not db_password or db_password == "change-me":
            raise RuntimeError("DB_LOGIN_PASSWORD must be set in local.secrets.env")

    if "DB_LOGIN_USER" not in merged:
        merged["DB_LOGIN_USER"] = "postgres"
    if "DB_LOGIN_PASSWORD" not in merged:
        merged["DB_LOGIN_PASSWORD"] = ""
    return merged


def load_runtime_config(config_file: Path) -> tuple[dict, list[str]]:
    config = json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG))
    configured_keys: set[str] = set()
    if config_file.exists():
        with config_file.open("r", encoding="utf-8") as file:
            override = json.load(file)
        configured_keys = set(override)
        config.update(override)
    defaulted_keys = sorted(set(DEFAULT_RUNTIME_CONFIG) - configured_keys)
    return config, defaulted_keys


def runtime_default_preview(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def is_bare_systemctl_command(command: object) -> bool:
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens and tokens[0] == "systemctl")


def is_bare_systemctl_status_command(command: object) -> bool:
    if not isinstance(command, str):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return len(tokens) >= 3 and tokens[0] == "systemctl" and tokens[1] == "status"


def is_disallowed_bare_systemctl_command(command: object) -> bool:
    return is_bare_systemctl_command(command) and not is_bare_systemctl_status_command(command)


def systemctl_action(command: object) -> tuple[str, list[str]] | None:
    if not isinstance(command, str):
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    if not tokens:
        return None
    if tokens[0] == "sudo":
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):
            option = tokens.pop(0)
            if option in {"-u", "-g", "-h", "-p"} and tokens:
                tokens.pop(0)
    if not tokens or Path(tokens[0]).name != "systemctl":
        return None
    verbs = {
        "start",
        "stop",
        "restart",
        "reload",
        "try-restart",
        "reload-or-restart",
        "reload-or-try-restart",
        "status",
    }
    for index, token in enumerate(tokens[1:], start=1):
        if token in verbs:
            return token, tokens[index + 1 :]
    return None


def is_nginx_stop_start_command(command: object) -> bool:
    return nginx_systemctl_action(command) in NGINX_STOP_START_ACTIONS


def is_unsupported_nginx_command(command: object) -> bool:
    return nginx_systemctl_action(command) in NGINX_UNSUPPORTED_ACTIONS


def nginx_systemctl_action(command: object) -> str | None:
    action = systemctl_action(command)
    if not action:
        return None
    verb, targets = action
    if any(target in NGINX_SERVICE_TARGETS for target in targets):
        return verb
    return None


def is_readable_systemctl_status_result(command: str, result: CommandResult) -> bool:
    return is_bare_systemctl_status_command(command) and result.rc in {0, 3}


def check_runtime_config(reporter: Reporter, runtime: dict) -> bool:
    ok = True
    unknown_keys = sorted(set(runtime) - set(DEFAULT_RUNTIME_CONFIG))
    if unknown_keys:
        reporter.fail("runtime config keys", "unknown key(s): " + ", ".join(unknown_keys))
        ok = False
    else:
        reporter.pass_("runtime config keys", f"{len(DEFAULT_RUNTIME_CONFIG)} known key(s)")

    for field in RUNTIME_BOOL_FIELDS:
        if isinstance(runtime.get(field), bool):
            continue
        reporter.fail(f"runtime {field}", "expected boolean true/false")
        ok = False

    for field in RUNTIME_POSITIVE_INT_FIELDS:
        value = runtime.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            continue
        reporter.fail(f"runtime {field}", "expected positive integer")
        ok = False

    for field in (
        "db_psql_bin",
        "db_psql_host",
        "maintenance_stub_archive_path",
        "maintenance_stub_verify_marker",
    ):
        value = runtime.get(field)
        if isinstance(value, str) and value.strip():
            continue
        reporter.fail(f"runtime {field}", "expected non-empty string")
        ok = False

    phase = runtime.get("db_maintenance_sql_phase")
    if phase not in DB_MAINTENANCE_PHASES:
        reporter.fail(
            "runtime db_maintenance_sql_phase",
            "expected one of: " + ", ".join(sorted(DB_MAINTENANCE_PHASES)),
        )
        ok = False

    for field in ("db_maintenance_sql", "management_commands", "healthcheck_commands"):
        value = runtime.get(field)
        if not isinstance(value, list):
            reporter.fail(f"runtime {field}", "expected list")
            ok = False
            continue
        bad_indexes = [
            str(index)
            for index, item in enumerate(value, start=1)
            if not isinstance(item, str) or not item.strip()
        ]
        if bad_indexes:
            reporter.fail(
                f"runtime {field}",
                "expected non-empty string item(s), bad index(es): " + ", ".join(bad_indexes),
            )
            ok = False

    for field in ("outlook_email_recipients", "outlook_email_cc"):
        value = runtime.get(field)
        if isinstance(value, str):
            continue
        if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
            continue
        if isinstance(value, list) and not value:
            continue
        reporter.fail(f"runtime {field}", "expected string or list of non-empty strings")
        ok = False

    for field in ("outlook_email_subject", "outlook_email_body"):
        if isinstance(runtime.get(field), str):
            continue
        reporter.fail(f"runtime {field}", "expected string")
        ok = False

    sql_scripts = runtime.get("sql_scripts")
    if not isinstance(sql_scripts, list):
        reporter.fail("runtime sql_scripts", "expected list")
        ok = False
    else:
        for index, script in enumerate(sql_scripts, start=1):
            label = f"runtime sql_scripts #{index}"
            if not isinstance(script, dict):
                reporter.fail(label, "expected object with path and phase")
                ok = False
                continue
            path_value = script.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                reporter.fail(label, "path must be a non-empty string")
                ok = False
            else:
                path = ROOT / path_value
                if path.is_file():
                    reporter.pass_(f"{label} path", str(path))
                else:
                    reporter.fail(label, f"path not found: {path}")
                    ok = False
            script_phase = script.get("phase")
            if script_phase not in DB_MAINTENANCE_PHASES:
                reporter.fail(label, "phase must be one of: " + ", ".join(sorted(DB_MAINTENANCE_PHASES)))
                ok = False

    service_steps = runtime.get("service_steps")
    if not isinstance(service_steps, list):
        reporter.fail("runtime service_steps", "expected list")
        ok = False
    else:
        nginx_service_actions: list[tuple[int, str, str, str]] = []
        for index, step in enumerate(service_steps, start=1):
            label = f"runtime service_steps #{index}"
            if not isinstance(step, dict):
                reporter.fail(label, "expected object with command and optional phase")
                ok = False
                continue
            step_phase = step.get("phase", "after_migrate")
            if step_phase not in SERVICE_PHASES:
                reporter.fail(label, "phase must be one of: " + ", ".join(sorted(SERVICE_PHASES)))
                ok = False
            command = step.get("command")
            nginx_command_action = nginx_systemctl_action(command)
            if nginx_command_action in NGINX_STOP_START_ACTIONS:
                nginx_service_actions.append((index, label, str(step_phase), nginx_command_action))
            if not isinstance(command, str) or not command.strip():
                reporter.fail(label, "command must be a non-empty string")
                ok = False
            elif is_unsupported_nginx_command(command):
                reporter.fail(label, "nginx restart/reload commands are not supported; use stop nginx then start nginx")
                ok = False
            elif is_nginx_stop_start_command(command) and step_phase != "after_frontend_unpack":
                reporter.fail(
                    label,
                    "nginx stop/start commands must run in after_frontend_unpack after final frontend unpack",
                )
                ok = False
            elif is_disallowed_bare_systemctl_command(command):
                reporter.fail(label, "systemctl service commands except status must use sudo")
                ok = False
            for optional_field in ("name", "permission_check_command"):
                if optional_field in step and not isinstance(step[optional_field], str):
                    reporter.fail(label, f"{optional_field} must be a string when set")
                    ok = False
                elif is_unsupported_nginx_command(step.get(optional_field)):
                    reporter.fail(
                        label,
                        f"{optional_field} must not use nginx restart/reload; use stop nginx then start nginx",
                    )
                    ok = False
                elif is_nginx_stop_start_command(step.get(optional_field)) and step_phase != "after_frontend_unpack":
                    reporter.fail(
                        label,
                        f"{optional_field} must run nginx stop/start in after_frontend_unpack",
                    )
                    ok = False
                elif is_disallowed_bare_systemctl_command(step.get(optional_field)):
                    reporter.fail(label, f"{optional_field} must use sudo for systemctl commands except status")
                    ok = False
        for position, (_index, label, step_phase, verb) in enumerate(nginx_service_actions):
            if verb != "stop" or step_phase != "after_frontend_unpack":
                continue
            has_later_start = any(
                later_phase == "after_frontend_unpack" and later_verb == "start"
                for _later_index, _later_label, later_phase, later_verb in nginx_service_actions[position + 1 :]
            )
            if not has_later_start:
                reporter.fail(label, "nginx stop in after_frontend_unpack must be followed by nginx start before healthcheck")
                ok = False

    if ok:
        reporter.pass_("runtime config values", "types and ranges are valid")
    return ok


def management_commands(env: dict[str, str], runtime: dict) -> list[str]:
    configured = runtime.get("management_commands", [])
    if configured:
        return configured
    manage_py = require_value(env, "APP_MANAGE_PY_PATH")
    return [
        f"python {sh_quote(manage_py)} migrate --fake",
        f"python {sh_quote(manage_py)} sync_action_role",
    ]


def require_value(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная: {name}")
    return value


def resolve_ssh_key_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path

    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path

    return Path.home() / path


def ssh_key_args(env: dict[str, str], scope: str) -> list[str]:
    specific = env.get(f"{scope}_SSH_KEY_PATH", "").strip()
    generic = env.get("SSH_KEY_PATH", "").strip()
    path_value = specific or generic
    if not path_value:
        return []
    return ["-i", str(resolve_ssh_key_path(path_value))]


def windows_release_root(env: dict[str, str]) -> Path:
    explicit = env.get("RELEASE_ROOT_WINDOWS", "").strip()
    if explicit:
        return Path(explicit)

    wsl_path = env.get("RELEASE_ROOT_WSL", "").strip()
    converted = wsl_to_windows_path(wsl_path)
    if converted:
        return Path(converted)

    return ROOT / "releases"


def wsl_to_windows_path(path: str) -> str:
    if path.startswith("/mnt/") and len(path) > 6:
        drive = path[5].upper()
        rest = path[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return ""


def to_git_bash_path(path: str | Path) -> str:
    normalized = str(path).replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[0].lower()
        rest = normalized[2:].lstrip("/")
        return f"/{drive}/{rest}"
    return normalized


def prepare_build_env(env: dict[str, str]) -> dict[str, str]:
    build_env = os.environ.copy()
    build_env.update(env)
    build_env.setdefault("PYTHONIOENCODING", "utf-8")

    release_root = windows_release_root(env)
    build_env.setdefault("RELEASE_ROOT_WINDOWS", str(release_root))
    build_env.setdefault("BACKEND_BUILD_VENV_RELATIVE_PATH", ".venv/Scripts/activate.bat")
    build_env.setdefault("BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH", "requirements.txt")
    build_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    build_env.setdefault("PIP_TRUSTED_HOST", PIP_TRUSTED_HOSTS)
    if not build_env.get("BACKEND_APP_ROOT_DIR"):
        build_env["BACKEND_APP_ROOT_DIR"] = DEFAULT_BACKEND_APP_ROOT_DIR
    if not build_env.get("BACKEND_DJANGO_SETTINGS_MODULE"):
        build_env["BACKEND_DJANGO_SETTINGS_MODULE"] = f"{build_env['BACKEND_APP_ROOT_DIR']}.settings.base"
    if not build_env.get("RELEASE_ROOT_BASH"):
        build_env["RELEASE_ROOT_BASH"] = to_git_bash_path(release_root)
    build_env["BACKEND_REPO_ROOT_BASH"] = to_git_bash_path(require_value(env, "BACKEND_SOURCE_REPO_PATH"))
    if not build_env.get("FRONTEND_DEV_SERVER_NAME"):
        build_env["FRONTEND_DEV_SERVER_NAME"] = require_value(env, "DEV_DOMAIN")
    return build_env


def set_env_line(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = f"{key}="
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare_frontend_env_files(env: dict[str, str], build_version: str = "") -> None:
    settings = [
        ("frontend_dev", require_value(env, "DEV_DOMAIN")),
        ("frontend_test", require_value(env, "TEST_DOMAIN")),
        ("frontend_prod", require_value(env, "PROD_DOMAIN")),
    ]
    for dirname, domain in settings:
        directory = BUILDER_ROOT / "settings" / dirname
        template = directory / ".env.template"
        target = directory / ".env"
        if not template.exists():
            raise RuntimeError(f"Не найден frontend template: {template}")
        shutil.copy2(template, target)
        base_url = f"https://{domain}"
        replacements = {
            "REACT_APP_BASE_BACKEND_URL": base_url,
            "VITE_BASE_BACKEND_URL": base_url,
            "REACT_APP_FILE_PROXY_SERVICE_URL": f"{base_url}/file/",
            "VITE_FILE_PROXY_SERVICE_URL": f"{base_url}/file/",
            "REACT_APP_FILTERS_SERVICE_URL": f"{base_url}/filters/",
            "VITE_FILTERS_SERVICE_URL": f"{base_url}/filters/",
        }
        if build_version:
            replacements["VITE_BUILD_VERSION"] = build_version
        for key, value in replacements.items():
            set_env_line(target, key, value)


def check_command(reporter: Reporter, name: str, args: list[str]) -> bool:
    result = run_command(args)
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_(name, output.splitlines()[0] if output else "")
        return True
    reporter.fail(name, output or f"rc={result.rc}")
    return False


def check_windows_command(reporter: Reporter, name: str, command: str) -> bool:
    return check_command(reporter, name, ["cmd.exe", "/C", command])


def check_ssh_key_files(reporter: Reporter, env: dict[str, str], app_only: bool = False) -> None:
    keys = [
        ("SSH key", env.get("SSH_KEY_PATH", "")),
        ("app SSH key", env.get("APP_SSH_KEY_PATH", "")),
    ]
    if app_only:
        reporter.skip("DB SSH key", "app-only mode")
    else:
        keys.append(("DB SSH key", env.get("DB_SSH_KEY_PATH", "")))
    configured = False
    for name, path_value in keys:
        if not path_value.strip():
            continue
        configured = True
        key_path = resolve_ssh_key_path(path_value)
        if key_path.is_file():
            reporter.pass_(name, str(key_path))
        else:
            reporter.fail(name, f"not found: {key_path}")
    if not configured:
        reporter.skip("SSH key", "not configured; using default ssh config/agent")


def check_repo(reporter: Reporter, name: str, path_value: str) -> str:
    path = Path(path_value)
    if not path.exists():
        reporter.fail(name, f"директория отсутствует: {path}")
        return ""
    if not (path / ".git").exists():
        reporter.fail(name, f"не Git-репозиторий: {path}")
        return ""
    origin = run_command(["git", "-C", str(path), "remote", "get-url", "origin"])
    if origin.rc != 0:
        reporter.fail(name, (origin.stderr or origin.stdout).strip() or "origin не задан")
        return ""
    origin_url = origin.stdout.strip()
    reporter.pass_(name, origin_url)
    return origin_url


def check_backend_build_inputs(reporter: Reporter, env: dict[str, str]) -> None:
    """Проверяет локальные настройки backend build до запуска create_release.py."""
    try:
        build_env = prepare_build_env(env)
        source_repo = Path(require_value(build_env, "BACKEND_SOURCE_REPO_PATH"))
        app_root_dir = require_value(build_env, "BACKEND_APP_ROOT_DIR")
        settings_module = require_value(build_env, "BACKEND_DJANGO_SETTINGS_MODULE")
        requirements_relative_path = require_value(build_env, "BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH")
        venv_relative_path = require_value(build_env, "BACKEND_BUILD_VENV_RELATIVE_PATH")
    except Exception as exc:
        reporter.fail("backend build config", str(exc))
        return

    app_root_path = source_repo / Path(app_root_dir)
    if app_root_path.is_dir():
        reporter.pass_("backend app root", f"{app_root_dir} -> {app_root_path}")
    else:
        reporter.fail(
            "backend app root",
            f"BACKEND_APP_ROOT_DIR={app_root_dir!r} не найден: {app_root_path}. "
            "Задайте реальную директорию backend application root в .env.",
        )

    requirements_path = source_repo / Path(requirements_relative_path)
    if requirements_path.is_file():
        reporter.pass_("backend build requirements", str(requirements_path))
    else:
        reporter.fail(
            "backend build requirements",
            f"BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH={requirements_relative_path!r} не найден: {requirements_path}",
        )

    venv_activate_path = source_repo / Path(venv_relative_path)
    python_path = venv_activate_path.parent / "python.exe"
    if not python_path.is_file():
        reporter.skip(
            "backend Django settings import",
            f"venv python не найден: {python_path}; build создаст venv и установит requirements",
        )
        return

    import_code = (
        "import importlib, os, sys; "
        f"sys.path.insert(0, {str(app_root_path)!r}); "
        f"os.environ.setdefault('DJANGO_SETTINGS_MODULE', {settings_module!r}); "
        "importlib.import_module(os.environ['DJANGO_SETTINGS_MODULE']); "
        "print(os.environ['DJANGO_SETTINGS_MODULE'])"
    )
    result = run_command(
        [str(python_path), "-Xutf8", "-c", import_code],
        cwd=source_repo,
        timeout=60,
        env=build_env,
    )
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_("backend Django settings import", output or settings_module)
    else:
        reporter.fail(
            "backend Django settings import",
            output or f"rc={result.rc}; проверьте BACKEND_APP_ROOT_DIR и BACKEND_DJANGO_SETTINGS_MODULE",
        )


def is_data_insert_idempotent(path: Path) -> bool:
    """Проверяет базовую повторяемость full-state INSERT SQL."""
    content = path.read_text(encoding="utf-8", errors="ignore").upper()
    if "INSERT INTO" not in content:
        return True
    return (
        "ON CONFLICT" in content
        or "TRUNCATE" in content
        or "MERGE" in content
        or re.search(r"\bDROP\b", content) is not None
    )


def is_insert_if_missing_idempotent(path: Path) -> bool:
    """Проверяет, что insert-if-missing SQL только добавляет отсутствующие строки."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    upper_content = content.upper()
    if "INSERT INTO" not in upper_content:
        return True
    if re.search(r"\bTRUNCATE\b", content, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"\bON\s+CONFLICT\b(?:.|\n)*?\bDO\s+NOTHING\b",
            content,
            flags=re.IGNORECASE,
        )
    )


def iter_sql_files(root: Path, include_insert_only: bool) -> Iterable[Path]:
    """Возвращает SQL-файлы для data generator без записи run_all-файлов."""
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.sql")):
        normalized_parent = path.parent.as_posix().lower()
        if "set_default" in normalized_parent:
            continue
        if include_insert_only and "insert" not in normalized_parent:
            continue
        yield path


def split_sql_statements(content: str) -> list[tuple[str, int]]:
    statements: list[tuple[str, int]] = []
    start = 0
    start_line = 1
    line = 1
    in_string = False
    index = 0
    while index < len(content):
        char = content[index]
        if char == "'":
            if in_string and index + 1 < len(content) and content[index + 1] == "'":
                index += 1
            else:
                in_string = not in_string
        elif char == ";" and not in_string:
            raw_statement = content[start:index]
            statement = raw_statement.strip()
            if statement:
                leading_whitespace = raw_statement[: len(raw_statement) - len(raw_statement.lstrip())]
                statements.append((statement, start_line + leading_whitespace.count("\n")))
            start = index + 1
            start_line = line
        if char == "\n":
            line += 1
        index += 1

    raw_tail = content[start:]
    tail = raw_tail.strip()
    if tail:
        leading_whitespace = raw_tail[: len(raw_tail) - len(raw_tail.lstrip())]
        statements.append((tail, start_line + leading_whitespace.count("\n")))
    return statements


def split_sql_csv(text: str) -> list[str]:
    values: list[str] = []
    start = 0
    depth = 0
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "'":
            if in_string and index + 1 < len(text) and text[index + 1] == "'":
                index += 1
            else:
                in_string = not in_string
        elif not in_string:
            if char == "(":
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
            elif char == "," and depth == 0:
                values.append(text[start:index].strip())
                start = index + 1
        index += 1
    values.append(text[start:].strip())
    return values


def iter_values_tuples(values_sql: str) -> Iterable[tuple[str, int]]:
    depth = 0
    start: int | None = None
    line = 0
    tuple_line = 0
    in_string = False
    index = 0
    while index < len(values_sql):
        char = values_sql[index]
        if char == "'":
            if in_string and index + 1 < len(values_sql) and values_sql[index + 1] == "'":
                index += 1
            else:
                in_string = not in_string
        elif not in_string:
            if char == "(":
                if depth == 0:
                    start = index + 1
                    tuple_line = line
                depth += 1
            elif char == ")" and depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    yield values_sql[start:index], tuple_line
                    start = None
        if char == "\n":
            line += 1
        index += 1


def parse_sql_literal(value: str) -> str | None:
    value = value.strip()
    if value.upper() == "NULL":
        return None
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def normalize_sql_table(table: str) -> str:
    parts = [part.strip('"').lower() for part in table.split(".")]
    return parts[-1]


def parse_insert_rows(content: str) -> list[SqlInsertRow]:
    rows: list[SqlInsertRow] = []
    insert_re = re.compile(
        r"\bINSERT\s+INTO\s+([A-Za-z0-9_\".]+)\s*\((.*?)\)\s*VALUES\s*(.*)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for statement, statement_line in split_sql_statements(content):
        match = insert_re.search(statement)
        if not match:
            continue
        table = normalize_sql_table(match.group(1))
        columns = tuple(column.strip().strip('"').lower() for column in split_sql_csv(match.group(2)))
        values_line_offset = statement[: match.start(3)].count("\n")
        values_sql = re.split(r"\bON\s+CONFLICT\b|\bRETURNING\b", match.group(3), maxsplit=1, flags=re.IGNORECASE)[0]
        for tuple_sql, tuple_line in iter_values_tuples(values_sql):
            values = tuple(parse_sql_literal(value) for value in split_sql_csv(tuple_sql))
            if len(values) != len(columns):
                continue
            rows.append(
                SqlInsertRow(
                    table=table,
                    columns=columns,
                    values=values,
                    line=statement_line + values_line_offset + tuple_line,
                )
            )
    return rows


def find_catalog_business_key_conflicts(path: Path, relative_path: Path) -> list[SqlValidationProblem]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    grouped_rows: dict[tuple[str, tuple[str, ...]], dict[tuple[str | None, ...], SqlInsertRow]] = {}
    problems: list[SqlValidationProblem] = []

    for row in parse_insert_rows(content):
        business_keys = CATALOG_BUSINESS_KEYS.get(row.table, ())
        if not business_keys:
            continue
        row_by_column = dict(zip(row.columns, row.values))
        for business_key in business_keys:
            if not all(column in row_by_column for column in business_key.columns):
                continue
            key_values = tuple(row_by_column[column] for column in business_key.columns)
            if business_key.ignore_blank and any(value in (None, "") for value in key_values):
                continue

            group_key = (row.table, business_key.columns)
            rows_by_key = grouped_rows.setdefault(group_key, {})
            previous = rows_by_key.get(key_values)
            if previous is None:
                rows_by_key[key_values] = row
                continue
            if previous.values == row.values:
                continue

            id_index = row.columns.index("id") if "id" in row.columns else None
            previous_id = previous.values[id_index] if id_index is not None else "?"
            current_id = row.values[id_index] if id_index is not None else "?"
            problems.append(
                SqlValidationProblem(
                    path=relative_path,
                    rule="catalog business key duplicate",
                    detail=(
                        f"{row.table} key {business_key.columns}={key_values!r} "
                        f"conflicts at lines {previous.line} and {row.line} "
                        f"(id {previous_id!r} vs {current_id!r})"
                    ),
                )
            )

    return problems


def non_idempotent_data_insert_scripts(source_repo: Path) -> list[Path]:
    """Находит full-state data INSERT SQL, которые не имеют повторяемой стратегии."""
    scripts_root = source_repo / DATABASE_SCRIPTS_PREFIX
    problems: list[Path] = []

    for directory in DATA_SQL_INSERT_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=False):
            if not is_data_insert_idempotent(path):
                problems.append(path.relative_to(source_repo))

    for directory in DATA_SQL_MIXED_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=True):
            if not is_data_insert_idempotent(path):
                problems.append(path.relative_to(source_repo))

    return sorted(problems)


def validate_backend_data_insert_sql(source_repo: Path) -> list[SqlValidationProblem]:
    scripts_root = source_repo / DATABASE_SCRIPTS_PREFIX
    problems = [
        SqlValidationProblem(
            path=path,
            rule="full-state idempotency",
            detail="INSERT script must use ON CONFLICT, TRUNCATE, MERGE, or DROP",
        )
        for path in non_idempotent_data_insert_scripts(source_repo)
    ]

    for directory in DATA_SQL_INSERT_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=False):
            relative_path = path.relative_to(source_repo)
            problems.extend(find_catalog_business_key_conflicts(path, relative_path))

    for directory in DATA_SQL_MIXED_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=True):
            relative_path = path.relative_to(source_repo)
            problems.extend(find_catalog_business_key_conflicts(path, relative_path))

    for directory in DATA_SQL_INSERT_IF_MISSING_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=True):
            relative_path = path.relative_to(source_repo)
            if not is_insert_if_missing_idempotent(path):
                problems.append(
                    SqlValidationProblem(
                        path=relative_path,
                        rule="insert-if-missing idempotency",
                        detail="insert_new_objects SQL must not TRUNCATE and must use ON CONFLICT DO NOTHING",
                    )
                )
            problems.extend(find_catalog_business_key_conflicts(path, relative_path))

    return sorted(problems, key=lambda problem: (problem.path.as_posix(), problem.rule, problem.detail))


def check_backend_data_insert_idempotency(reporter: Reporter, env: dict[str, str]) -> None:
    """Проверяет idempotency data INSERT SQL до build, без создания build_scripts."""
    source_repo = Path(require_value(env, "BACKEND_SOURCE_REPO_PATH"))
    scripts_root = source_repo / DATABASE_SCRIPTS_PREFIX
    if not scripts_root.is_dir():
        reporter.skip("backend data INSERT idempotency", f"директория не найдена: {scripts_root}")
        return

    problems = validate_backend_data_insert_sql(source_repo)
    if not problems:
        reporter.pass_("backend data INSERT idempotency", "все INSERT-скрипты прошли validation rules")
        return

    shown = [
        f"{problem.path.as_posix()}: {problem.rule}: {problem.detail}"
        for problem in problems[:20]
    ]
    suffix = "" if len(problems) <= len(shown) else f"\n... и еще {len(problems) - len(shown)}"
    reporter.fail(
        "backend data INSERT idempotency",
        f"найдено {len(problems)} SQL validation problem(s):\n"
        + "\n".join(shown)
        + suffix,
    )


def check_origin_network(reporter: Reporter, name: str, origin_url: str) -> None:
    if not origin_url:
        reporter.skip(name, "origin URL неизвестен")
        return
    if origin_url.startswith(("git@", "ssh://")):
        reporter.skip(name, "SSH origin не проверяется без Git-аутентификации")
        return
    if not origin_url.startswith(("http://", "https://")):
        reporter.skip(name, f"неподдерживаемый origin URL: {origin_url}")
        return
    try:
        req = request.Request(origin_url, method="HEAD")
        with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as response:
            reporter.pass_(name, f"HTTP {response.status}")
    except error.HTTPError as exc:
        if exc.code in {200, 301, 302, 401, 403, 404}:
            reporter.pass_(name, f"HTTP {exc.code}")
        else:
            reporter.fail(name, f"HTTP {exc.code}")
    except Exception as exc:
        reporter.fail(name, str(exc))


def ssh_base_args(env: dict[str, str], user: str, host: str, scope: str) -> list[str]:
    return [
        "ssh",
        *ssh_key_args(env, scope),
        "-o", "BatchMode=yes",
        "-o", "NumberOfPasswordPrompts=1",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        f"{user}@{host}",
    ]


def ssh_command(
    env: dict[str, str],
    user: str,
    host: str,
    command: str,
    scope: str,
    input_text: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    mask: Iterable[str] = (),
) -> CommandResult:
    return run_command(
        ssh_base_args(env, user, host, scope) + [command],
        input_text=input_text,
        timeout=timeout,
        mask=mask,
    )


def stream_ssh_command(
    env: dict[str, str],
    user: str,
    host: str,
    command: str,
    scope: str,
    timeout: int | None = None,
    mask: Iterable[str] = (),
) -> CommandResult:
    rc = stream_command(
        ssh_base_args(env, user, host, scope) + [command],
        timeout=timeout,
        mask=mask,
    )
    return CommandResult(rc, "", "")


def scp_file(
    env: dict[str, str],
    local_path: Path,
    user: str,
    host: str,
    remote_path: str,
    scope: str = "APP",
) -> CommandResult:
    return run_command(
        [
            "scp",
            *ssh_key_args(env, scope),
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            str(local_path),
            f"{user}@{host}:{remote_path}",
        ],
        timeout=120,
    )


def sh_quote(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("'", "'\"'\"'") + "'"


def runtime_local_path(path_value: object) -> Path:
    path = Path(str(path_value)).expanduser()
    if path.is_absolute():
        return path
    return ROOT / path


def check_maintenance_stub_archive(reporter: Reporter, runtime: dict) -> None:
    if not runtime.get("maintenance_stub_enabled", True):
        reporter.skip("maintenance stub archive", "disabled")
        return
    path = runtime_local_path(runtime.get("maintenance_stub_archive_path", DEFAULT_MAINTENANCE_STUB_ARCHIVE))
    if path.is_file():
        reporter.pass_("maintenance stub archive", str(path))
    else:
        reporter.fail("maintenance stub archive", f"not found: {path}")


def check_ssh_runtime(reporter: Reporter, env: dict[str, str], app_only: bool = False) -> dict[str, bool]:
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    result = {"app": False, "db": False}

    app = ssh_command(
        env,
        app_user,
        app_host,
        "echo ok && command -v bash tar python find rm grep >/dev/null && tar --help | grep -q -- '--strip-components'",
        "APP",
    )
    if app.rc == 0:
        reporter.pass_("app VM SSH/runtime", app.stdout.strip())
        result["app"] = True
    else:
        reporter.fail("app VM SSH/runtime", (app.stderr or app.stdout).strip() or f"rc={app.rc}")
        reporter.skip("app VM deploy checks", "app VM SSH/runtime недоступен")

    if app_only:
        reporter.skip("DB VM SSH/psql", "app-only mode")
        reporter.skip("DB SQL checks", "app-only mode")
        return result

    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    db = ssh_command(
        env,
        db_user,
        db_host,
        "echo ok && command -v psql bash tar find rm chmod pgrep >/dev/null",
        "DB",
    )
    if db.rc == 0:
        reporter.pass_("DB VM SSH/psql", db.stdout.strip())
        result["db"] = True
    else:
        reporter.fail("DB VM SSH/psql", (db.stderr or db.stdout).strip() or f"rc={db.rc}")
        reporter.skip("DB SQL checks", "DB VM SSH/psql недоступен")
    return result


def db_psql_base_command(env: dict[str, str], runtime: dict) -> tuple[str, list[str]]:
    password = env.get("DB_LOGIN_PASSWORD", "")
    psql_bin = str(runtime.get("db_psql_bin", "psql"))
    psql_host = str(runtime.get("db_psql_host", "localhost"))
    psql_base = (
        f"PGPASSWORD={sh_quote(password)} {sh_quote(psql_bin)} --set=ON_ERROR_STOP=1 "
        f"--host={sh_quote(psql_host)} --port={sh_quote(require_value(env, 'DB_PORT'))} "
        f"--username={sh_quote(env.get('DB_LOGIN_USER', 'postgres'))} "
        f"--dbname={sh_quote(require_value(env, 'DB_NAME'))}"
    )
    return psql_base, [password]


def check_db_psql_login(reporter: Reporter, env: dict[str, str], runtime: dict) -> None:
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    psql_base, mask = db_psql_base_command(env, runtime)
    result = ssh_command(env, db_user, db_host, f"{psql_base} --command='SELECT 1;'", "DB", timeout=30, mask=mask)
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_("DB psql login", output.splitlines()[0] if output else "SELECT 1")
    else:
        for secret in mask:
            if secret:
                output = output.replace(secret, "***")
        reporter.fail("DB psql login", output or f"rc={result.rc}")


def check_outlook_email_config(reporter: Reporter, runtime: dict) -> None:
    if not runtime.get("outlook_email_enabled", False):
        reporter.skip("Outlook email", "отключено в windows_pipeline.local.json")
        return

    recipients = normalize_email_list(runtime.get("outlook_email_recipients", []))
    if recipients:
        reporter.pass_("Outlook email recipients", ", ".join(recipients))
    else:
        reporter.fail("Outlook email recipients", "задайте outlook_email_recipients")

    cc = normalize_email_list(runtime.get("outlook_email_cc", []))
    reporter.pass_("Outlook email cc", ", ".join(cc) if cc else "не задано")

    subject = str(runtime.get("outlook_email_subject", "")).strip()
    if subject:
        reporter.pass_("Outlook email subject", subject)
    else:
        reporter.fail("Outlook email subject", "задайте outlook_email_subject")

    body = str(runtime.get("outlook_email_body", "")).strip()
    if body:
        reporter.pass_("Outlook email body", f"{len(body)} символов")
    else:
        reporter.fail("Outlook email body", "задайте outlook_email_body")

    sample_context = {
        "build_version": "dry-run",
        "release_dir": str(ROOT / "releases" / "dry-run"),
        "dev_domain": "dev.example.local",
        "stand_url": "https://dev.example.local/",
        "artifacts_text": "- backend: dry-run\n- frontend: dry-run",
        "release_changelog_text": "Изменений нет.",
    }
    try:
        format_outlook_template(subject, sample_context)
        format_outlook_template(body, sample_context)
        reporter.pass_("Outlook email templates", "шаблоны темы и тела корректны")
    except Exception as exc:
        reporter.fail("Outlook email templates", str(exc))

    reporter.pass_(
        "Outlook email required",
        "да" if runtime.get("outlook_email_required", False) else "нет",
    )

    check_command(
        reporter,
        "Outlook COM",
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "$ErrorActionPreference='Stop'; $outlook = New-Object -ComObject Outlook.Application; 'ok'",
        ],
    )


def derive_service_permission_check(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return ""
    if not tokens:
        return ""
    if tokens[0] == "sudo":
        return command
    if tokens[0] != "systemctl":
        return ""

    verbs = {
        "start",
        "stop",
        "restart",
        "reload",
        "try-restart",
        "reload-or-restart",
        "reload-or-try-restart",
    }
    for index, token in enumerate(tokens[1:], start=1):
        if token in verbs:
            options = tokens[1:index]
            targets = tokens[index + 1 :]
            if not targets:
                return ""
            parts = ["systemctl", *options, "--dry-run", token, *targets]
            return " ".join(sh_quote(part) for part in parts)
    return ""


def sudo_list_command(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return ""
    if not tokens or tokens[0] != "sudo":
        return ""
    sudo_tokens = tokens[1:]
    while sudo_tokens and sudo_tokens[0].startswith("-"):
        option = sudo_tokens.pop(0)
        if option in {"-u", "-g", "-h", "-p"} and sudo_tokens:
            sudo_tokens.pop(0)
    if not sudo_tokens:
        return ""
    return "sudo -n -l " + " ".join(sh_quote(token) for token in sudo_tokens)


def is_sudo_command(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens and tokens[0] == "sudo")


def check_service_permissions(reporter: Reporter, env: dict[str, str], runtime: dict) -> None:
    if not runtime.get("service_permission_checks_enabled", True):
        reporter.skip("service permission checks", "disabled")
        return

    steps = runtime.get("service_steps", [])
    if not steps:
        reporter.skip("service permission checks", "service_steps empty")
        return

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    if any(is_sudo_command(str(step.get("permission_check_command") or step.get("command", "")).strip()) for step in steps):
        sudo_list_result = ssh_command(env, app_user, app_host, "sudo -n -l", "APP", timeout=30)
        sudo_list_output = (sudo_list_result.stdout or sudo_list_result.stderr).strip()
        if sudo_list_result.rc == 0:
            reporter.pass_("sudo allowed commands", sudo_list_output.splitlines()[0] if sudo_list_output else "sudo -n -l")
        else:
            reporter.fail("sudo allowed commands", sudo_list_output or f"rc={sudo_list_result.rc}")

    for index, step in enumerate(steps, start=1):
        label = step.get("name") or f"service step #{index}"
        command = str(step.get("command", "")).strip()
        check_command_text = str(step.get("permission_check_command", "")).strip()
        derived_check = False

        if not check_command_text:
            check_command_text = derive_service_permission_check(command)
            derived_check = bool(check_command_text)
        if not check_command_text:
            reporter.skip(
                f"service permission {label}",
                "set permission_check_command for non-systemctl command",
            )
            continue

        sudo_check = sudo_list_command(check_command_text or command)
        if sudo_check:
            sudo_result = ssh_command(env, app_user, app_host, sudo_check, "APP", timeout=30)
            sudo_output = (sudo_result.stdout or sudo_result.stderr).strip()
            if sudo_result.rc == 0:
                reporter.pass_(f"sudo permission {label}", sudo_output.splitlines()[0] if sudo_output else sudo_check)
                continue
            else:
                reporter.fail(f"sudo permission {label}", sudo_output or f"rc={sudo_result.rc}")
                continue

        result = ssh_command(env, app_user, app_host, check_command_text, "APP", timeout=30)
        output = (result.stdout or result.stderr).strip()
        if result.rc == 0 or is_readable_systemctl_status_result(check_command_text, result):
            detail = output.splitlines()[0] if output else check_command_text
            if derived_check:
                detail = f"{detail} (systemctl --dry-run; authorization not guaranteed)"
            if result.rc != 0:
                detail = f"{detail} (status readable; unit may be inactive)"
            reporter.pass_(f"service permission {label}", detail)
        else:
            reporter.fail(f"service permission {label}", output or f"rc={result.rc}")


def check_remote_directory(
    reporter: Reporter,
    env: dict[str, str],
    name: str,
    path_value: str,
) -> None:
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    path = path_value.rstrip("/")
    quoted_path = sh_quote(path)
    command = (
        "set -e; "
        f"path={quoted_path}; "
        'echo "checking path: $path"; '
        'echo "effective user/groups:"; '
        "id; "
        'echo "path permissions:"; '
        'stat -c "target %A %a owner=%U(%u) group=%G(%g) %n" "$path" 2>&1 || true; '
        'echo "parent permissions:"; '
        'namei -l "$path" 2>&1 || true; '
        'if command -v getfacl >/dev/null 2>&1; then '
        'echo "target ACL:"; '
        'getfacl -p "$path" 2>&1 || true; '
        "fi; "
        'if [ ! -e "$path" ]; then '
        'echo "missing path or parent directory is not searchable"; '
        'parent=$(dirname "$path"); '
        'stat -c "parent %A %a owner=%U(%u) group=%G(%g) %n" "$parent" 2>&1 || true; '
        "exit 10; "
        "fi; "
        'if [ ! -d "$path" ]; then '
        'echo "path exists but is not a directory"; '
        'stat -c "target %A %a owner=%U(%u) group=%G(%g) %n" "$path" 2>&1 || true; '
        "exit 11; "
        "fi; "
        'if [ ! -r "$path" ] || [ ! -w "$path" ] || [ ! -x "$path" ]; then '
        'echo "directory is not rwx for effective user/groups"; '
        'stat -c "target %A %a owner=%U(%u) group=%G(%g) %n" "$path" 2>&1 || true; '
        "exit 12; "
        "fi; "
        'tmp="$path/.simple-deploy-write-check-$$"; '
        'if ! printf "simple-deploy write check\\n" > "$tmp"; then '
        'echo "cannot create test file: $tmp"; '
        "exit 13; "
        "fi; "
        'if ! rm -f "$tmp"; then '
        'echo "cannot remove test file: $tmp"; '
        "exit 14; "
        "fi"
    )
    result = ssh_command(env, app_user, app_host, command, "APP", timeout=30)
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_(f"app VM directory {name}", path)
    else:
        reporter.fail(f"app VM directory {name}", output or f"rc={result.rc}")


def check_app_deploy_directories(reporter: Reporter, env: dict[str, str], runtime: dict) -> None:
    directories = [
        ("remote tmp root", require_value(env, "REMOTE_TMP_ROOT")),
        ("backend release path", require_value(env, "BACKEND_RELEASE_PATH")),
        ("frontend release path", require_value(env, "FRONTEND_RELEASE_PATH")),
        ("app workdir", require_value(env, "APP_WORKDIR")),
    ]
    if runtime.get("backup_enabled", False):
        directories.append(("backup root base", env.get("BACKUP_ROOT_BASE", "/tmp/simple-deploy-backups")))

    for name, path in directories:
        check_remote_directory(reporter, env, name, path)


def check_app_manage_py(reporter: Reporter, env: dict[str, str]) -> None:
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    app_workdir = require_value(env, "APP_WORKDIR")
    manage_py = require_value(env, "APP_MANAGE_PY_PATH")
    command = (
        f"cd {sh_quote(app_workdir)} && "
        f"test -f {sh_quote(manage_py)} && "
        f"test -r {sh_quote(manage_py)}"
    )
    result = ssh_command(env, app_user, app_host, command, "APP", timeout=30)
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_("app manage.py path", f"{app_workdir}/{manage_py}")
    else:
        reporter.fail("app manage.py path", output or f"not found/readable from APP_WORKDIR: {app_workdir}/{manage_py}")


def check_http(reporter: Reporter, env: dict[str, str], validate_certs: bool) -> None:
    url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    context = None if validate_certs else ssl._create_unverified_context()
    try:
        with request.urlopen(url, timeout=DEFAULT_TIMEOUT, context=context) as response:
            if response.status in {200, 302, 401, 403}:
                reporter.pass_("DEV HTTP endpoint", f"HTTP {response.status}")
            else:
                reporter.fail("DEV HTTP endpoint", f"HTTP {response.status}")
    except error.HTTPError as exc:
        if exc.code in {200, 302, 401, 403}:
            reporter.pass_("DEV HTTP endpoint", f"HTTP {exc.code}")
        else:
            reporter.fail("DEV HTTP endpoint", f"HTTP {exc.code}")
    except Exception as exc:
        reporter.fail("DEV HTTP endpoint", str(exc))


def read_http_text(url: str, context: ssl.SSLContext | None) -> str:
    with request.urlopen(url, timeout=DEFAULT_TIMEOUT, context=context) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        data = response.read()
    try:
        return data.decode(content_type)
    except (LookupError, UnicodeDecodeError):
        return decode_subprocess_output(data)


def script_urls_from_html(base_url: str, html: str) -> list[str]:
    parser = ScriptSrcParser()
    parser.feed(html)
    urls = []
    base_origin = parse.urlparse(base_url).netloc
    for src in parser.srcs:
        absolute = parse.urljoin(base_url, src)
        parsed = parse.urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.netloc == base_origin:
            urls.append(absolute)
    return urls


def version_found_in_text(text: str, expected_version: str) -> bool:
    if expected_version in text:
        return True
    escaped = re.escape(expected_version)
    compact_pattern = escaped.replace(r"\.", r"\s*\.\s*").replace(r"\-", r"\s*-\s*")
    return re.search(compact_pattern, text) is not None


def check_portal_release_version(env: dict[str, str], runtime: dict, expected_version: str) -> None:
    if not runtime.get("portal_version_check_enabled", True):
        print("SKIP portal version check: disabled")
        return
    if not expected_version:
        print("SKIP portal version check: build version unknown")
        return

    validate = bool(runtime.get("healthcheck_validate_certs", False))
    context = None if validate else ssl._create_unverified_context()
    url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    print(f"RUN portal version check: {url} expected={expected_version}", flush=True)

    html = read_http_text(url, context)
    if version_found_in_text(html, expected_version):
        print(f"PASS portal version check: found {expected_version} in HTML")
        return

    asset_limit = int(runtime.get("portal_version_asset_limit", 20))
    script_urls = script_urls_from_html(url, html)[:asset_limit]
    print(f"RUN portal version check: scanning {len(script_urls)} React assets", flush=True)
    for asset_url in script_urls:
        try:
            asset_text = read_http_text(asset_url, context)
        except Exception as exc:
            print(f"SKIP portal asset {asset_url}: {exc}", flush=True)
            continue
        if version_found_in_text(asset_text, expected_version):
            print(f"PASS portal version check: found {expected_version} in {asset_url}")
            return

    raise RuntimeError(f"portal version check failed: {expected_version} not found in HTML or React assets")


def verify_maintenance_stub_http(env: dict[str, str], runtime: dict) -> None:
    if not runtime.get("maintenance_stub_verify_enabled", True):
        print("SKIP maintenance stub HTTP check: disabled")
        return

    marker = str(runtime.get("maintenance_stub_verify_marker", "")).strip()
    if not marker:
        raise RuntimeError("maintenance stub HTTP check marker is empty")

    retries = int(runtime.get("maintenance_stub_verify_retries", 10))
    delay = int(runtime.get("maintenance_stub_verify_delay", 2))
    validate = bool(runtime.get("healthcheck_validate_certs", False))
    context = None if validate else ssl._create_unverified_context()
    base_url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    last_error = ""

    print(
        f"RUN maintenance stub HTTP check: {base_url} marker={marker!r} "
        f"(retries={retries}, delay={delay}s)",
        flush=True,
    )
    for attempt in range(1, retries + 1):
        url = base_url + f"?simple_deploy_maintenance_check={int(time.time())}_{attempt}"
        print(f"RUN maintenance stub HTTP check attempt {attempt}/{retries}", flush=True)
        try:
            html = read_http_text(url, context)
            if marker in html:
                print("PASS maintenance stub HTTP check: marker found")
                return
            preview = re.sub(r"\s+", " ", html).strip()[:300]
            last_error = f"marker not found; response preview: {preview}"
        except error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        if attempt < retries:
            time.sleep(delay)

    raise RuntimeError(f"maintenance stub HTTP check failed: {last_error}")


def data_sql_artifacts_enabled(args: argparse.Namespace) -> bool:
    return not getattr(args, "skip_data_sql_artifacts", False)


def resolve_release_dir(env: dict[str, str], build_version: str, latest: bool) -> tuple[str, Path]:
    release_root = windows_release_root(env)
    print(f"RESOLVE release root: {release_root}", flush=True)
    if latest:
        dirs = [path for path in release_root.iterdir() if path.is_dir()] if release_root.exists() else []
        if not dirs:
            raise RuntimeError(f"В {release_root} не найдены директории релизов")
        selected = max(dirs, key=lambda path: path.stat().st_mtime)
        print(f"RESOLVE latest release: {selected.name} ({selected})", flush=True)
        return selected.name, selected
    if not build_version:
        raise RuntimeError("Укажите --build-version или --latest")
    selected = release_root / build_version
    print(f"RESOLVE requested release: {selected.name} ({selected})", flush=True)
    return build_version, selected


def run_or_raise(label: str, result: CommandResult, mask: Iterable[str] = ()) -> None:
    print(f"CHECK {label}", flush=True)
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    for secret in mask:
        if secret:
            stdout = stdout.replace(secret, "***")
            stderr = stderr.replace(secret, "***")
    if result.rc == 0:
        if stdout:
            print(f"STDOUT {label}:\n{stdout}", flush=True)
        if stderr:
            print(f"STDERR {label}:\n{stderr}", flush=True)
        print(f"PASS {label}")
        return
    detail_parts = [f"rc={result.rc}"]
    if stdout:
        detail_parts.append(f"stdout:\n{stdout}")
    if stderr:
        detail_parts.append(f"stderr:\n{stderr}")
    detail = "\n".join(detail_parts)
    raise RuntimeError(f"{label}: {detail}")


def remote_clean_unpack_command(artifact: Artifact) -> str:
    target = artifact.extract_path.rstrip("/")
    if target in {"", "/"}:
        raise RuntimeError(f"Unsafe extract path for {artifact.name}: {artifact.extract_path}")
    return (
        "set -e; "
        f"target={sh_quote(target)}; "
        f"archive={sh_quote(artifact.remote_archive)}; "
        'case "$target" in ""|"/") echo "unsafe extract path: $target"; exit 20;; esac; '
        'test -d "$target"; '
        'find "$target" -mindepth 1 -maxdepth 1 ! -name ".env" -exec rm -rf -- {} +; '
        'tar -xzf "$archive" -C "$target" --strip-components=1'
    )


def upload_app_artifacts(env: dict[str, str], artifacts: list[Artifact], remote_dir: str) -> None:
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    print(f"RUN create remote release dir: {remote_dir}", flush=True)
    run_or_raise(
        "create remote release dir",
        ssh_command(env, app_user, app_host, f"mkdir -p {sh_quote(remote_dir)}", "APP"),
    )
    for artifact in artifacts:
        print(f"RUN upload {artifact.name}: {artifact.local_path} -> {artifact.remote_archive}", flush=True)
        run_or_raise(
            f"upload {artifact.name}",
            scp_file(env, artifact.local_path, app_user, app_host, artifact.remote_archive),
        )


def backup_app_artifacts(env: dict[str, str], runtime: dict, build_version: str, artifacts: list[Artifact]) -> None:
    if not runtime.get("backup_enabled", False):
        return

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    backup_root = f"{env.get('BACKUP_ROOT_BASE', '/tmp/simple-deploy-backups').rstrip('/')}/{build_version}"
    print(f"RUN create backup root: {backup_root}", flush=True)
    run_or_raise(
        "create backup root",
        ssh_command(env, app_user, app_host, f"mkdir -p {sh_quote(backup_root)}", "APP"),
    )
    for artifact in artifacts:
        extract_path = artifact.extract_path.rstrip("/")
        backup_parent = str(PurePosixPath(extract_path).parent)
        backup_name = PurePosixPath(extract_path).name
        command = (
            f"test -d {sh_quote(artifact.extract_path)} && "
            f"tar -czf {sh_quote(backup_root + '/' + artifact.name + '.tar.gz')} "
            f"-C {sh_quote(backup_parent)} {sh_quote(backup_name)}"
        )
        print(f"RUN backup {artifact.name}: {artifact.extract_path}", flush=True)
        run_or_raise(
            f"backup {artifact.name}",
            ssh_command(env, app_user, app_host, command, "APP", timeout=120),
        )


def unpack_app_artifact(env: dict[str, str], artifact: Artifact) -> None:
    command = remote_clean_unpack_command(artifact)
    print(f"RUN unpack {artifact.name}: {artifact.remote_archive} -> {artifact.extract_path}", flush=True)
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
    steps = []
    for step in runtime.get("service_steps", []):
        if step.get("phase", "after_migrate") == phase:
            steps.append(step)
    if not steps:
        print(f"SKIP service steps {phase}: empty")
        return
    for step in steps:
        label = step.get("name") or step["command"]
        command = step["command"]
        print(f"RUN service {phase}: {label}", flush=True)
        result = ssh_command(
            env,
            require_value(env, "APP_VM_USER"),
            require_value(env, "APP_VM_HOST"),
            command,
            "APP",
            timeout=120,
        )
        run_or_raise(f"service {phase}: {label}", result)


def git_log_merge_commits(repo_path: str, previous_sha: str, current_sha: str) -> list[dict[str, str]]:
    result = run_command(
        [
            "git",
            "-C",
            repo_path,
            "log",
            f"{previous_sha}..{current_sha}",
            "--first-parent",
            "--merges",
            "--pretty=format:%H%x1f%s%x1f%b%x1e",
        ],
        timeout=60,
    )
    if result.rc != 0:
        detail = (result.stderr or result.stdout).strip() or f"rc={result.rc}"
        raise RuntimeError(detail)

    commits = []
    for raw_entry in result.stdout.strip("\x1e\n").split("\x1e"):
        entry = raw_entry.strip()
        if not entry:
            continue
        parts = entry.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commits.append({"sha": parts[0].strip(), "subject": parts[1].strip(), "body": parts[2].strip()})
    return commits


def merge_request_line(commit: dict[str, str]) -> str | None:
    body = commit["body"]
    mr_match = re.search(r"See merge request\s+(.+?!(\d+))", body)
    if not mr_match:
        return None

    title = ""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("See merge request"):
            title = stripped
            break
    if not title:
        title = commit["subject"]
    return f"- !{mr_match.group(2)} {title}"


def repo_changelog_text(name: str, current_repo: dict, previous_repo: dict) -> str:
    current_sha = str(current_repo.get("commit_sha", "")).strip()
    previous_sha = str(previous_repo.get("commit_sha", "")).strip()
    repo_path = str(current_repo.get("source_repo_path", "")).strip()

    if not current_sha or not previous_sha:
        return f"{name}:\nМетаданные коммитов неполные, список изменений недоступен."
    if current_sha == previous_sha:
        return f"{name}:\nИзменений нет."
    if not repo_path:
        return f"{name}:\nПуть к source-репозиторию не задан, список изменений недоступен."

    try:
        commits = git_log_merge_commits(repo_path, previous_sha, current_sha)
    except Exception as exc:
        return f"{name}:\nПРЕДУПРЕЖДЕНИЕ: не удалось построить список изменений: {exc}"
    lines = [line for commit in commits if (line := merge_request_line(commit))]
    if not lines:
        return f"{name}:\nИзменения есть, но в first-parent истории не найдены влитые merge request."
    return f"{name}:\n" + "\n".join(lines)


def release_changelog_text(release_dir: Path) -> str:
    current_manifest = load_release_manifest(release_dir)
    if not current_manifest:
        return "Метаданные текущего релиза не найдены, список изменений недоступен."

    previous = find_previous_release_manifest(release_dir)
    if not previous:
        return "Метаданные предыдущего релиза не найдены, список изменений недоступен."
    previous_dir, previous_manifest = previous

    current_repos = current_manifest.get("repositories", {})
    previous_repos = previous_manifest.get("repositories", {})
    sections = [f"Предыдущий релиз: {previous_manifest.get('build_version', previous_dir.name)}"]
    repo_names = {"backend": "Backend", "frontend": "Frontend"}
    for repo_key, label in repo_names.items():
        current_repo = current_repos.get(repo_key)
        previous_repo = previous_repos.get(repo_key)
        if not current_repo or not previous_repo:
            sections.append(f"{label}:\nМетаданные релиза неполные, список изменений недоступен.")
            continue
        sections.append(repo_changelog_text(label, current_repo, previous_repo))
    return "\n\n".join(sections)


class SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def normalize_email_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = re.split(r"[;,]", value)
    elif isinstance(value, list):
        items = [str(item) for item in value]
    else:
        items = [str(value)]
    return [item.strip() for item in items if item.strip()]


def format_outlook_template(template: object, context: dict[str, object]) -> str:
    return str(template).format_map(SafeFormatDict(context))


def deploy_summary_lines(build_version: str, release_dir: Path, artifacts: list[Artifact]) -> list[str]:
    lines = [
        f"build_version: {build_version}",
        f"release_dir: {release_dir}",
    ]
    for artifact in artifacts:
        lines.append(f"{artifact.name}: {artifact.local_path} -> {artifact.extract_path}")
    return lines


def send_outlook_success_email(
    env: dict[str, str],
    runtime: dict,
    build_version: str,
    release_dir: Path,
    artifacts: list[Artifact],
) -> None:
    if not runtime.get("outlook_email_enabled", False):
        print("SKIP Outlook success email: отключено")
        return

    recipients = normalize_email_list(runtime.get("outlook_email_recipients", []))
    if not recipients:
        print("SKIP Outlook success email: список получателей пуст")
        return

    cc = normalize_email_list(runtime.get("outlook_email_cc", []))
    artifact_lines = [f"- {artifact.name}: {artifact.local_path} -> {artifact.extract_path}" for artifact in artifacts]
    try:
        changelog_text = release_changelog_text(release_dir)
    except Exception as exc:
        changelog_text = f"ПРЕДУПРЕЖДЕНИЕ: не удалось построить список изменений релиза: {exc}"
        print(f"WARN release changelog failed: {exc}", flush=True)
    context = {
        "build_version": build_version,
        "release_dir": str(release_dir),
        "dev_domain": require_value(env, "DEV_DOMAIN"),
        "stand_url": f"https://{require_value(env, 'DEV_DOMAIN')}/",
        "artifacts_text": "\n".join(artifact_lines),
        "release_changelog_text": changelog_text,
    }
    subject = format_outlook_template(runtime.get("outlook_email_subject", ""), context)
    body = format_outlook_template(runtime.get("outlook_email_body", ""), context)
    manifest_path = release_dir / RELEASE_MANIFEST_NAME
    attachment_paths = [str(manifest_path)] if manifest_path.is_file() else []
    if attachment_paths:
        print(f"INFO Outlook success email attachment: {manifest_path}", flush=True)
    else:
        print(f"WARN Outlook success email attachment missing: {manifest_path}", flush=True)
    payload = {
        "to": recipients,
        "cc": cc,
        "subject": subject,
        "body": body,
        "attachments": attachment_paths,
    }
    powershell = """
$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$outlook = New-Object -ComObject Outlook.Application
$mail = $outlook.CreateItem(0)
$mail.To = ($payload.to -join ';')
if ($payload.cc -and $payload.cc.Count -gt 0) {
    $mail.CC = ($payload.cc -join ';')
}
$mail.Subject = [string]$payload.subject
$mail.BodyFormat = 2
$encodedBody = [System.Net.WebUtility]::HtmlEncode([string]$payload.body)
$encodedBody = $encodedBody -replace "(`r`n|`n|`r)", "<br>"
$mail.HTMLBody = "<html><body style=""font-family: Arial, sans-serif; font-size: 10pt;"">$encodedBody</body></html>"
if ($payload.attachments) {
    foreach ($attachment in $payload.attachments) {
        if (-not [string]::IsNullOrWhiteSpace([string]$attachment)) {
            [void]$mail.Attachments.Add([string]$attachment)
        }
    }
}
$mail.Send()
Write-Output 'sent'
""".strip()

    print(f"RUN Outlook success email: {', '.join(recipients)}", flush=True)
    result = run_command(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", powershell],
        input_text=json.dumps(payload),
        timeout=60,
    )
    if result.rc == 0:
        print("PASS Outlook success email")
        return

    detail = (result.stderr or result.stdout).strip() or f"rc={result.rc}"
    if runtime.get("outlook_email_required", False):
        raise RuntimeError(f"Не удалось отправить письмо через Outlook: {detail}")
    print(f"WARN Outlook success email failed: {detail}", flush=True)


def deploy(args: argparse.Namespace) -> int:
    """Выполняет deploy выбранного релиза на указанный контур."""
    print("DEPLOY load config", flush=True)
    app_only = bool(getattr(args, "app_only", False))
    env = load_env(args.env_file, args.secrets_file, require_secrets=not app_only)
    runtime, _defaulted_runtime_keys = load_runtime_config(args.config_file)
    build_version, release_dir = resolve_release_dir(env, args.build_version, args.latest)
    contour = validate_contour(args.contour)
    print(f"DEPLOY build_version: {build_version}", flush=True)
    print(f"DEPLOY contour: {contour}", flush=True)
    print(f"DEPLOY release_dir: {release_dir}", flush=True)
    print(f"DEPLOY mode: {'app-only' if app_only else 'full'}", flush=True)

    success_recorded = False
    try:
        artifacts = resolve_artifacts(env, build_version, release_dir)
        app_user = require_value(env, "APP_VM_USER")
        app_host = require_value(env, "APP_VM_HOST")
        remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"

        if not app_only:
            cleanup_db_data_update_leftovers(env, runtime)

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
            backend_artifact = require_artifact(artifacts, "backend")
            frontend_artifact = require_artifact(artifacts, "frontend")
            db_schema_artifact = resolve_db_schema_artifact(env, build_version, release_dir, contour)
            if runtime.get("data_sql_enabled", True):
                db_insert_artifact = resolve_db_data_artifact(env, build_version, release_dir, "insert")
                db_update_parallel_artifact = resolve_db_data_artifact(
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
                maintenance_stub_artifact = resolve_maintenance_stub_artifact(env, runtime, build_version)
            else:
                maintenance_stub_artifact = None
                print("SKIP maintenance stub: disabled", flush=True)
            app_upload_artifacts = [
                artifact
                for artifact in (backend_artifact, frontend_artifact, maintenance_stub_artifact)
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
                print("SKIP maintenance stub unpack: disabled", flush=True)

            run_db_schema_summary(env, runtime, db_schema_artifact)
            if db_insert_artifact is not None:
                run_db_data_insert(env, runtime, db_insert_artifact)
            if db_update_parallel_artifact is not None:
                run_db_data_update_parallel(
                    env,
                    runtime,
                    db_update_parallel_artifact,
                    include_set_default_sql=getattr(args, "include_set_default_sql", False),
                )
            for phase in ("before_unpack", "before_migrate", "after_migrate"):
                run_db_maintenance(env, runtime, phase)

            unpack_app_artifact(env, backend_artifact)

        run_service_steps(env, runtime, "after_unpack")

        for command in management_commands(env, runtime):
            remote = (
                f"cd {sh_quote(require_value(env, 'APP_WORKDIR'))} && "
                f". {sh_quote(require_value(env, 'APP_VENV_ACTIVATE_PATH'))} && "
                f"{command}"
            )
            print(f"RUN management command: {command}", flush=True)
            run_or_raise(
                f"management command: {command}",
                ssh_command(env, app_user, app_host, remote, "APP", timeout=300),
            )

        run_service_steps(env, runtime, "after_migrate")

        if not app_only:
            unpack_app_artifact(env, frontend_artifact)
            run_service_steps(env, runtime, "after_frontend_unpack")

        if runtime.get("healthcheck_enabled", True):
            healthcheck(env, runtime, build_version)
        else:
            print("SKIP healthcheck: disabled")

        mark_contour_applied(contour, build_version, release_dir)
        success_recorded = True

        print("DEPLOY SUMMARY")
        for line in deploy_summary_lines(build_version, release_dir, artifacts):
            print(line)

        send_outlook_success_email(env, runtime, build_version, release_dir, artifacts)
    except Exception as exc:
        if not success_recorded:
            mark_contour_failed_best_effort(contour, build_version, release_dir, exc)
        else:
            print(
                f"WARN deploy failed after successful state update: "
                f"contour={contour} build_version={build_version} error={exc}",
                flush=True,
            )
        raise
    return 0


def healthcheck(env: dict[str, str], runtime: dict, expected_version: str = "") -> None:
    retries = int(runtime.get("healthcheck_retries", 30))
    delay = int(runtime.get("healthcheck_delay", 5))
    validate = bool(runtime.get("healthcheck_validate_certs", False))
    url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    context = None if validate else ssl._create_unverified_context()
    last_error = ""
    print(f"RUN healthcheck HTTP: {url} (retries={retries}, delay={delay}s)", flush=True)
    for attempt in range(1, retries + 1):
        print(f"RUN healthcheck attempt {attempt}/{retries}", flush=True)
        try:
            with request.urlopen(url, timeout=DEFAULT_TIMEOUT, context=context) as response:
                if response.status in {200, 302, 401, 403}:
                    print(f"PASS healthcheck HTTP {response.status}")
                    break
                last_error = f"HTTP {response.status}"
        except error.HTTPError as exc:
            if exc.code in {200, 302, 401, 403}:
                print(f"PASS healthcheck HTTP {exc.code}")
                break
            last_error = f"HTTP {exc.code}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(delay)
    else:
        raise RuntimeError(f"healthcheck failed: {last_error}")

    check_portal_release_version(env, runtime, expected_version)

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    for command in runtime.get("healthcheck_commands", []):
        print(f"RUN healthcheck command: {command}", flush=True)
        run_or_raise(f"healthcheck command: {command}", ssh_command(env, app_user, app_host, command, "APP", timeout=120))


def pipeline(args: argparse.Namespace) -> int:
    if not dry_run(args):
        return 1
    build_rc = build(args)
    if build_rc != 0:
        return build_rc
    args.latest = True
    args.build_version = ""
    return deploy(args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows-only simple-deploy runner")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS_FILE)
    parser.add_argument("--config-file", type=Path, default=DEFAULT_CONFIG_FILE)
    parser.add_argument("--timeout", type=int, default=3600)
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run_parser = subparsers.add_parser("dry-run")
    dry_run_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help="Deprecated no-op: data SQL artifacts are checked and built by default.",
    )
    dry_run_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help="Skip data SQL artifact validation for an explicit schema-only run.",
    )
    dry_run_parser.add_argument("--app-only", action="store_true")

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help="Deprecated no-op: data SQL artifacts are built by default.",
    )
    build_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help="Skip data SQL artifact generation for an explicit schema-only build.",
    )

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--build-version", default="")
    deploy_parser.add_argument("--latest", action="store_true")
    deploy_parser.add_argument("--contour", choices=CONTOURS, default="dev")
    deploy_parser.add_argument(
        "--include-set-default-sql",
        action="store_true",
        help="Include kind=set_default data SQL in the update runner. Disabled by default.",
    )
    deploy_parser.add_argument("--app-only", action="store_true")

    pipeline_parser = subparsers.add_parser("pipeline")
    pipeline_parser.add_argument("--build-version", default="")
    pipeline_parser.add_argument("--latest", action="store_true")
    pipeline_parser.add_argument("--contour", choices=CONTOURS, default="dev")
    pipeline_parser.add_argument(
        "--include-set-default-sql",
        action="store_true",
        help="Include kind=set_default data SQL in the update runner. Disabled by default.",
    )
    pipeline_parser.add_argument(
        "--include-data-sql",
        action="store_true",
        help="Deprecated no-op: data SQL artifacts are checked and built by default.",
    )
    pipeline_parser.add_argument(
        "--skip-data-sql-artifacts",
        action="store_true",
        help="Skip data SQL artifact validation/generation for an explicit schema-only run.",
    )
    pipeline_parser.add_argument("--app-only", action="store_true")

    baseline_parser = subparsers.add_parser("set-baseline")
    baseline_parser.add_argument("--contour", choices=CONTOURS, required=True)
    baseline_parser.add_argument("--build-version", default="")
    baseline_parser.add_argument("--backend-commit", default="")

    mark_applied_parser = subparsers.add_parser("mark-applied")
    mark_applied_parser.add_argument("--contour", choices=CONTOURS, required=True)
    mark_applied_parser.add_argument("--build-version", required=True)

    mark_failed_parser = subparsers.add_parser("mark-failed")
    mark_failed_parser.add_argument("--contour", choices=CONTOURS, required=True)
    mark_failed_parser.add_argument("--build-version", required=True)
    mark_failed_parser.add_argument("--error", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    with tee_output(args.command):
        try:
            if args.command == "dry-run":
                return 0 if dry_run(args) else 1
            if args.command == "build":
                return build(args)
            if args.command == "deploy":
                return deploy(args)
            if args.command == "pipeline":
                return pipeline(args)
            if args.command == "set-baseline":
                return set_baseline(args)
            if args.command == "mark-applied":
                return mark_applied(args)
            if args.command == "mark-failed":
                return mark_failed(args)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
