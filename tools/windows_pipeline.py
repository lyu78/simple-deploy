"""Windows-only runner for simple-deploy.

This runner mirrors the operator-facing Ansible flow without requiring WSL.
It uses Python, Node/Git already installed on Windows, and Windows OpenSSH
(`ssh`/`scp`) for remote VM operations.
"""

from __future__ import annotations

import argparse
import fnmatch
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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = ROOT / ".env"
DEFAULT_SECRETS_FILE = ROOT / "local.secrets.env"
DEFAULT_CONFIG_FILE = ROOT / "windows_pipeline.local.json"
DEFAULT_LOG_DIR = ROOT / "logs"
DEFAULT_TIMEOUT = 20


DEFAULT_RUNTIME_CONFIG = {
    "backup_enabled": False,
    "db_maintenance_enabled": True,
    "db_psql_bin": "psql",
    "db_psql_host": "localhost",
    "db_maintenance_sql_phase": "before_unpack",
    "db_maintenance_sql": ["VACUUM ANALYZE;"],
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
}


@dataclass
class CommandResult:
    rc: int
    stdout: str
    stderr: str


@dataclass
class Artifact:
    name: str
    local_path: Path
    remote_archive: str
    extract_path: str


class Reporter:
    def __init__(self) -> None:
        self.issues: list[str] = []
        self.skipped: list[str] = []

    def pass_(self, name: str, detail: str = "") -> None:
        suffix = f": {detail}" if detail else ""
        print(f"DRY-RUN PASS {name}{suffix}")

    def fail(self, name: str, detail: str) -> None:
        print(f"DRY-RUN FAIL {name}: {detail}")
        self.issues.append(f"{name}: {detail}")

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
    for secret in mask:
        if secret:
            stdout = stdout.replace(secret, "***")
            stderr = stderr.replace(secret, "***")
    return CommandResult(completed.returncode, stdout, stderr)


def stream_command(
    args: list[str],
    cwd: Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> int:
    print(f"RUN {' '.join(args)}", flush=True)
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
            print(decode_subprocess_output(line), end="", flush=True)
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


def load_runtime_config(config_file: Path) -> dict:
    config = json.loads(json.dumps(DEFAULT_RUNTIME_CONFIG))
    if config_file.exists():
        with config_file.open("r", encoding="utf-8") as file:
            override = json.load(file)
        config.update(override)
    return config


def management_commands(env: dict[str, str], runtime: dict) -> list[str]:
    configured = runtime.get("management_commands", [])
    if configured:
        return configured
    manage_py = require_value(env, "APP_MANAGE_PY_PATH")
    return [
        f"python {sh_quote(manage_py)} migrate",
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
    if not build_env.get("RELEASE_ROOT_BASH"):
        build_env["RELEASE_ROOT_BASH"] = to_git_bash_path(release_root)
    if not build_env.get("BACKEND_REPO_ROOT_BASH"):
        backend_bash = build_env.get("BACKEND_TARGET_REPO_PATH_BASH", "")
        if not backend_bash:
            backend_bash = to_git_bash_path(require_value(env, "BACKEND_TARGET_REPO_PATH"))
        build_env["BACKEND_REPO_ROOT_BASH"] = backend_bash
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
        directory = ROOT / "builder" / "settings" / dirname
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


def check_ssh_key_files(reporter: Reporter, env: dict[str, str]) -> None:
    keys = [
        ("SSH key", env.get("SSH_KEY_PATH", "")),
        ("app SSH key", env.get("APP_SSH_KEY_PATH", "")),
        ("DB SSH key", env.get("DB_SSH_KEY_PATH", "")),
    ]
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


def scp_file(env: dict[str, str], local_path: Path, user: str, host: str, remote_path: str) -> CommandResult:
    return run_command(
        [
            "scp",
            *ssh_key_args(env, "APP"),
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


def check_ssh_runtime(reporter: Reporter, env: dict[str, str]) -> dict[str, bool]:
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
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

    db = ssh_command(env, db_user, db_host, "echo ok && command -v psql >/dev/null", "DB")
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


def derive_service_permission_check(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return ""
    if not tokens:
        return ""
    if tokens[0] == "sudo":
        return "sudo"
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
    for index, step in enumerate(steps, start=1):
        label = step.get("name") or f"service step #{index}"
        command = str(step.get("command", "")).strip()
        check_command_text = str(step.get("permission_check_command", "")).strip()

        if command.startswith("sudo ") or check_command_text.startswith("sudo "):
            reporter.fail(
                f"service permission {label}",
                "service step must run as APP_VM_USER without sudo",
            )
            continue

        if not check_command_text:
            check_command_text = derive_service_permission_check(command)
        if check_command_text == "sudo":
            reporter.fail(
                f"service permission {label}",
                "service step must run as APP_VM_USER without sudo",
            )
            continue
        if not check_command_text:
            reporter.skip(
                f"service permission {label}",
                "set permission_check_command for non-systemctl command",
            )
            continue

        result = ssh_command(env, app_user, app_host, check_command_text, "APP", timeout=30)
        output = (result.stdout or result.stderr).strip()
        if result.rc == 0:
            reporter.pass_(f"service permission {label}", output.splitlines()[0] if output else check_command_text)
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


def dry_run(args: argparse.Namespace) -> bool:
    reporter = Reporter()
    try:
        env = load_env(args.env_file, args.secrets_file, require_secrets=True)
        runtime = load_runtime_config(args.config_file)
        reporter.pass_("config files", f"{args.env_file}, {args.secrets_file}")
    except Exception as exc:
        reporter.fail("config files", str(exc))
        return reporter.result()

    for key in required_env_keys():
        if env.get(key, "").strip():
            reporter.pass_(f"env {key}")
        else:
            reporter.fail(f"env {key}", "значение не задано")

    check_command(reporter, "Python", [sys.executable, "--version"])
    check_windows_command(reporter, "git", "git --version")
    check_windows_command(reporter, "node", "node --version")
    check_windows_command(reporter, "npm", "npm --version")
    check_windows_command(reporter, "ssh", "ssh -V")
    check_windows_command(reporter, "scp", "where scp")

    git_bash = Path(env.get("GIT_BASH_PATH", ""))
    if git_bash.exists():
        reporter.pass_("Git Bash", str(git_bash))
    else:
        reporter.fail("Git Bash", f"не найден: {git_bash}")

    check_ssh_key_files(reporter, env)

    origins = [
        ("backend source repo", env.get("BACKEND_SOURCE_REPO_PATH", "")),
        ("backend target repo", env.get("BACKEND_TARGET_REPO_PATH", "")),
        ("frontend source repo", env.get("FRONTEND_SOURCE_REPO_PATH", "")),
        ("frontend target repo", env.get("FRONTEND_TARGET_REPO_PATH", "")),
    ]
    for name, path in origins:
        origin_url = check_repo(reporter, name, path)
        check_origin_network(reporter, f"{name} origin network", origin_url)

    try:
        ssh_state = check_ssh_runtime(reporter, env)
    except Exception as exc:
        reporter.fail("SSH runtime checks", str(exc))
        ssh_state = {"app": False, "db": False}
        reporter.skip("app VM deploy checks", "SSH runtime checks завершились ошибкой")
        reporter.skip("DB SQL checks", "SSH runtime checks завершились ошибкой")

    if not ssh_state["app"]:
        reporter.skip("app VM directory checks", "app VM unavailable")
        reporter.skip("service permission checks", "app VM unavailable")
        reporter.skip("DEV HTTP endpoint", "app VM недоступна, healthcheck неинформативен")
    else:
        check_app_deploy_directories(reporter, env, runtime)
        check_app_manage_py(reporter, env)
        check_service_permissions(reporter, env, runtime)
        if runtime.get("healthcheck_enabled", True):
            check_http(reporter, env, bool(runtime.get("healthcheck_validate_certs", False)))
        else:
            reporter.skip("DEV HTTP endpoint", "healthcheck disabled")

    if ssh_state["db"]:
        check_db_psql_login(reporter, env, runtime)
    else:
        reporter.skip("DB psql login", "DB VM SSH/psql unavailable")

    return reporter.result()


def required_env_keys() -> list[str]:
    return [
        "BUILD_VERSION_BASE",
        "GIT_BASH_PATH",
        "BACKEND_SOURCE_REPO_PATH",
        "BACKEND_TARGET_REPO_PATH",
        "BACKEND_TARGET_REPO_PATH_BASH",
        "FRONTEND_SOURCE_REPO_PATH",
        "FRONTEND_TARGET_REPO_PATH",
        "APP_VM_HOST",
        "APP_VM_USER",
        "DB_VM_HOST",
        "DB_VM_USER",
        "DB_PORT",
        "DB_NAME",
        "REMOTE_TMP_ROOT",
        "BACKEND_RELEASE_PATH",
        "FRONTEND_RELEASE_PATH",
        "APP_WORKDIR",
        "APP_VENV_ACTIVATE_PATH",
        "APP_MANAGE_PY_PATH",
        "DEV_DOMAIN",
        "TEST_DOMAIN",
        "PROD_DOMAIN",
        "FRONTEND_TEST_SERVER_NAME",
        "FRONTEND_PROD_SERVER_NAME",
    ]


def build(args: argparse.Namespace) -> int:
    env = load_env(args.env_file, args.secrets_file, require_secrets=False)
    print("BUILD prepare frontend env files", flush=True)
    prepare_frontend_env_files(env)
    build_env = prepare_build_env(env)
    return stream_command(
        [sys.executable, "-u", "create_release.py"],
        cwd=ROOT / "builder",
        timeout=args.timeout,
        env=build_env,
    )


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


def resolve_artifacts(env: dict[str, str], build_version: str, release_dir: Path) -> list[Artifact]:
    print(f"RESOLVE artifacts in: {release_dir}", flush=True)
    if not release_dir.is_dir():
        raise RuntimeError(f"Директория релиза не существует: {release_dir}")

    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    patterns = [
        (
            "backend",
            f"backend_r_{build_version}*.tar.gz",
            f"{remote_dir}/backend.tar.gz",
            require_value(env, "BACKEND_RELEASE_PATH"),
        ),
        (
            "frontend",
            f"frontend_r_{build_version}-bf_dev-env_{require_value(env, 'DEV_DOMAIN')}.tar.gz",
            f"{remote_dir}/frontend.tar.gz",
            require_value(env, "FRONTEND_RELEASE_PATH"),
        ),
    ]

    artifacts: list[Artifact] = []
    for name, pattern, remote_archive, extract_path in patterns:
        matches = [path for path in release_dir.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern)]
        if not matches:
            raise RuntimeError(f"В {release_dir} не найден архив по шаблону {pattern}")
        newest = max(matches, key=lambda path: path.stat().st_mtime)
        print(f"RESOLVE artifact {name}: {newest.name} -> {extract_path}", flush=True)
        artifacts.append(Artifact(name, newest, remote_archive, extract_path))
    return artifacts


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


def run_db_maintenance(env: dict[str, str], runtime: dict, phase: str) -> None:
    if not runtime.get("db_maintenance_enabled", True):
        print(f"SKIP DB maintenance {phase}: disabled")
        return

    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    psql_base, mask = db_psql_base_command(env, runtime)

    if phase == runtime.get("db_maintenance_sql_phase", "before_unpack"):
        for index, sql in enumerate(runtime.get("db_maintenance_sql", []), start=1):
            print(f"RUN DB inline SQL {phase} #{index}", flush=True)
            command = f"{psql_base} --command={sh_quote(sql)}"
            result = ssh_command(env, db_user, db_host, command, "DB", timeout=120, mask=mask)
            run_or_raise(f"DB inline SQL {phase} #{index}", result, mask=mask)

    for script in runtime.get("sql_scripts", []):
        if script.get("phase") != phase:
            continue
        path = ROOT / script["path"]
        sql = path.read_text(encoding="utf-8")
        print(f"RUN DB SQL script {path}", flush=True)
        result = ssh_command(env, db_user, db_host, psql_base, "DB", input_text=sql, timeout=120, mask=mask)
        run_or_raise(f"DB SQL script {path}", result, mask=mask)


def deploy(args: argparse.Namespace) -> int:
    print("DEPLOY load config", flush=True)
    env = load_env(args.env_file, args.secrets_file, require_secrets=True)
    runtime = load_runtime_config(args.config_file)
    build_version, release_dir = resolve_release_dir(env, args.build_version, args.latest)
    artifacts = resolve_artifacts(env, build_version, release_dir)
    print(f"DEPLOY build_version: {build_version}", flush=True)
    print(f"DEPLOY release_dir: {release_dir}", flush=True)

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"

    run_db_maintenance(env, runtime, "before_unpack")
    run_service_steps(env, runtime, "before_unpack")

    print(f"RUN create remote release dir: {remote_dir}", flush=True)
    run_or_raise("create remote release dir", ssh_command(env, app_user, app_host, f"mkdir -p {sh_quote(remote_dir)}", "APP"))
    for artifact in artifacts:
        print(f"RUN upload {artifact.name}: {artifact.local_path} -> {artifact.remote_archive}", flush=True)
        run_or_raise(f"upload {artifact.name}", scp_file(env, artifact.local_path, app_user, app_host, artifact.remote_archive))

    if runtime.get("backup_enabled", False):
        backup_root = f"{env.get('BACKUP_ROOT_BASE', '/tmp/simple-deploy-backups').rstrip('/')}/{build_version}"
        print(f"RUN create backup root: {backup_root}", flush=True)
        run_or_raise("create backup root", ssh_command(env, app_user, app_host, f"mkdir -p {sh_quote(backup_root)}", "APP"))
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
            run_or_raise(f"backup {artifact.name}", ssh_command(env, app_user, app_host, command, "APP", timeout=120))

    for artifact in artifacts:
        command = remote_clean_unpack_command(artifact)
        print(f"RUN unpack {artifact.name}: {artifact.remote_archive} -> {artifact.extract_path}", flush=True)
        run_or_raise(f"unpack {artifact.name}", ssh_command(env, app_user, app_host, command, "APP", timeout=120))

    run_service_steps(env, runtime, "after_unpack")
    run_db_maintenance(env, runtime, "before_migrate")

    for command in management_commands(env, runtime):
        remote = (
            f"cd {sh_quote(require_value(env, 'APP_WORKDIR'))} && "
            f". {sh_quote(require_value(env, 'APP_VENV_ACTIVATE_PATH'))} && "
            f"{command}"
        )
        print(f"RUN management command: {command}", flush=True)
        run_or_raise(f"management command: {command}", ssh_command(env, app_user, app_host, remote, "APP", timeout=300))

    run_db_maintenance(env, runtime, "after_migrate")
    run_service_steps(env, runtime, "after_migrate")

    if runtime.get("healthcheck_enabled", True):
        healthcheck(env, runtime, build_version)
    else:
        print("SKIP healthcheck: disabled")

    print("DEPLOY SUMMARY")
    print(f"build_version: {build_version}")
    print(f"release_dir: {release_dir}")
    for artifact in artifacts:
        print(f"{artifact.name}: {artifact.local_path} -> {artifact.extract_path}")
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

    subparsers.add_parser("dry-run")
    subparsers.add_parser("build")

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--build-version", default="")
    deploy_parser.add_argument("--latest", action="store_true")

    pipeline_parser = subparsers.add_parser("pipeline")
    pipeline_parser.add_argument("--build-version", default="")
    pipeline_parser.add_argument("--latest", action="store_true")
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
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
