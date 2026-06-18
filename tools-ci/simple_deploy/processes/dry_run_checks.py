"""Предварительные preflight-проверки dry-run для Windows runner-а."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import ssl
from typing import Iterable
from urllib import error, request

from simple_deploy.config.validation import (
    is_bare_systemctl_status_command,
    SYSTEMCTL_ACTIONS,
)
from simple_deploy.core.build_env import prepare_build_env
from simple_deploy.core.commands import CommandResult, run_command
from simple_deploy.core.db import db_psql_base_command
from simple_deploy.core.email import (
    format_outlook_template,
    normalize_email_list,
)
from simple_deploy.core.env import require_value
from simple_deploy.core.paths import DEFAULT_TIMEOUT, ROOT
from simple_deploy.core.ssh import resolve_ssh_key_path, sh_quote, ssh_command
from simple_deploy.release.artifacts import DEFAULT_MAINTENANCE_STUB_ARCHIVE
from simple_deploy.types.fields import (
    SqlTableNameString,
    SqlValidationDetailText,
    SqlValidationRuleString,
)

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
    """Описание бизнес-ключа для поиска конфликтов в catalog INSERT SQL."""

    columns: tuple[str, ...]
    ignore_blank: bool = False


@dataclass(frozen=True)
class SqlInsertRow:
    """Разобранная строка INSERT statement для SQL validation."""

    table: SqlTableNameString
    columns: tuple[str, ...]
    values: tuple[str | None, ...]
    line: int


@dataclass(frozen=True)
class SqlValidationProblem:
    """Проблема SQL validation, найденная в конкретном файле."""

    path: Path
    rule: SqlValidationRuleString
    detail: SqlValidationDetailText


CATALOG_BUSINESS_KEYS: dict[str, tuple[SqlBusinessKey, ...]] = {
    "app_ip_subcompany_catalog_contractsubject": (SqlBusinessKey(("title",)),),
    "app_ip_subcompany_catalog_contracttype": (SqlBusinessKey(("title",)),),
    "app_ip_subcompany_catalog_region": (SqlBusinessKey(("code",)),),
    "app_ip_subcompany_catalog_contractor": (
        SqlBusinessKey(("tin",), ignore_blank=True),
    ),
}


class Reporter:
    """Накопитель результата dry-run с единым форматом вывода."""

    def __init__(self) -> None:
        """Инициализирует списки ошибок, warnings и skips."""
        self.issues: list[str] = []
        self.skipped: list[str] = []
        self.warnings: list[str] = []

    def pass_(self, name: str, detail: str = "") -> None:
        """Фиксирует успешную dry-run проверку."""
        suffix = f": {detail}" if detail else ""
        print(f"DRY-RUN PASS {name}{suffix}")

    def fail(self, name: str, detail: str) -> None:
        """Фиксирует проваленную dry-run проверку."""
        print(f"DRY-RUN FAIL {name}: {detail}")
        self.issues.append(f"{name}: {detail}")

    def warn(self, name: str, detail: str) -> None:
        """Фиксирует предупреждение dry-run без провала результата."""
        print(f"DRY-RUN WARN {name}: {detail}")
        self.warnings.append(f"{name}: {detail}")

    def skip(self, name: str, reason: str) -> None:
        """Фиксирует пропущенную dry-run проверку с причиной."""
        print(f"DRY-RUN SKIP {name}: {reason}")
        self.skipped.append(f"{name}: {reason}")

    def result(self) -> bool:
        """Печатает итог dry-run и возвращает True, если ошибок не было."""
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


def is_readable_systemctl_status_result(
    command: str, result: CommandResult
) -> bool:
    """Определяет допустимый результат `systemctl status` для проверки прав."""
    return is_bare_systemctl_status_command(command) and result.rc in {0, 3}


def check_command(reporter: Reporter, name: str, args: list[str]) -> bool:
    """Запускает локальную команду и записывает результат в Reporter."""
    result = run_command(args)
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_(name, output.splitlines()[0] if output else "")
        return True
    reporter.fail(name, output or f"rc={result.rc}")
    return False


def check_windows_command(reporter: Reporter, name: str, command: str) -> bool:
    """Запускает команду через cmd.exe и записывает результат в Reporter."""
    return check_command(reporter, name, ["cmd.exe", "/C", command])


def check_ssh_key_files(
    reporter: Reporter, env: dict[str, str], app_only: bool = False
) -> None:
    """Проверяет существование настроенных SSH key files для APP и DB."""
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
        reporter.skip(
            "SSH key", "not configured; using default ssh config/agent"
        )


def check_repo(reporter: Reporter, name: str, path_value: str) -> str:
    """Проверяет локальный Git-репозиторий и возвращает его origin URL."""
    path = Path(path_value)
    if not path.exists():
        reporter.fail(name, f"директория отсутствует: {path}")
        return ""
    if not (path / ".git").exists():
        reporter.fail(name, f"не Git-репозиторий: {path}")
        return ""
    origin = run_command(
        ["git", "-C", str(path), "remote", "get-url", "origin"]
    )
    if origin.rc != 0:
        reporter.fail(
            name, (origin.stderr or origin.stdout).strip() or "origin не задан"
        )
        return ""
    origin_url = origin.stdout.strip()
    reporter.pass_(name, origin_url)
    return origin_url


def check_backend_build_inputs(
    reporter: Reporter, env: dict[str, str]
) -> None:
    """Проверяет backend build config до запуска create_release.py."""
    try:
        build_env = prepare_build_env(env)
        source_repo = Path(
            require_value(build_env, "BACKEND_SOURCE_REPO_PATH")
        )
        app_root_dir = require_value(build_env, "BACKEND_APP_ROOT_DIR")
        settings_module = require_value(
            build_env, "BACKEND_DJANGO_SETTINGS_MODULE"
        )
        requirements_relative_path = require_value(
            build_env, "BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH"
        )
        venv_relative_path = require_value(
            build_env, "BACKEND_BUILD_VENV_RELATIVE_PATH"
        )
    except Exception as exc:
        reporter.fail("backend build config", str(exc))
        return

    app_root_path = source_repo / Path(app_root_dir)
    if app_root_path.is_dir():
        reporter.pass_(
            "backend app root", f"{app_root_dir} -> {app_root_path}"
        )
    else:
        reporter.fail(
            "backend app root",
            f"BACKEND_APP_ROOT_DIR={app_root_dir!r} не найден: "
            f"{app_root_path}. "
            "Задайте реальную директорию backend application root в .env.",
        )

    requirements_path = source_repo / Path(requirements_relative_path)
    if requirements_path.is_file():
        reporter.pass_("backend build requirements", str(requirements_path))
    else:
        reporter.fail(
            "backend build requirements",
            "BACKEND_BUILD_REQUIREMENTS_RELATIVE_PATH="
            f"{requirements_relative_path!r} не найден: {requirements_path}",
        )

    venv_activate_path = source_repo / Path(venv_relative_path)
    python_path = venv_activate_path.parent / "python.exe"
    if not python_path.is_file():
        reporter.skip(
            "backend Django settings import",
            f"venv python не найден: {python_path}; build создаст venv "
            "и установит requirements",
        )
        return

    import_code = (
        "import importlib, os, sys; "
        f"sys.path.insert(0, {str(app_root_path)!r}); "
        "os.environ.setdefault("
        f"'DJANGO_SETTINGS_MODULE', {settings_module!r}); "
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
        reporter.pass_(
            "backend Django settings import", output or settings_module
        )
    else:
        reporter.fail(
            "backend Django settings import",
            output
            or f"rc={result.rc}; проверьте BACKEND_APP_ROOT_DIR "
            "и BACKEND_DJANGO_SETTINGS_MODULE",
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
    """Проверяет, что insert-if-missing SQL только добавляет строки."""
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
    """Делит SQL-текст на statements с номером первой строки."""
    statements: list[tuple[str, int]] = []
    start = 0
    start_line = 1
    line = 1
    in_string = False
    index = 0
    while index < len(content):
        char = content[index]
        if char == "'":
            if (
                in_string
                and index + 1 < len(content)
                and content[index + 1] == "'"
            ):
                index += 1
            else:
                in_string = not in_string
        elif char == ";" and not in_string:
            raw_statement = content[start:index]
            statement = raw_statement.strip()
            if statement:
                leading_whitespace = raw_statement[
                    : len(raw_statement) - len(raw_statement.lstrip())
                ]
                statements.append(
                    (statement, start_line + leading_whitespace.count("\n"))
                )
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
    """Делит SQL CSV с учетом литералов и вложенных скобок."""
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
    """Итерирует tuples из VALUES и возвращает относительные строки."""
    depth = 0
    start: int | None = None
    line = 0
    tuple_line = 0
    in_string = False
    index = 0
    while index < len(values_sql):
        char = values_sql[index]
        if char == "'":
            if (
                in_string
                and index + 1 < len(values_sql)
                and values_sql[index + 1] == "'"
            ):
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
    """Преобразует SQL literal в значение для сравнения business keys."""
    value = value.strip()
    if value.upper() == "NULL":
        return None
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def normalize_sql_table(table: str) -> str:
    """Нормализует имя SQL-таблицы до lowercase без schema prefix."""
    parts = [part.strip('"').lower() for part in table.split(".")]
    return parts[-1]


def parse_insert_rows(content: str) -> list[SqlInsertRow]:
    """Извлекает INSERT rows из SQL-текста для дальнейшей validation."""
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
        columns = tuple(
            column.strip().strip('"').lower()
            for column in split_sql_csv(match.group(2))
        )
        values_line_offset = statement[: match.start(3)].count("\n")
        values_sql = re.split(
            r"\bON\s+CONFLICT\b|\bRETURNING\b",
            match.group(3),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        for tuple_sql, tuple_line in iter_values_tuples(values_sql):
            values = tuple(
                parse_sql_literal(value) for value in split_sql_csv(tuple_sql)
            )
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


def find_catalog_business_key_conflicts(
    path: Path, relative_path: Path
) -> list[SqlValidationProblem]:
    """Ищет конфликтующие catalog INSERT rows с одинаковым business key."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    grouped_rows: dict[
        tuple[str, tuple[str, ...]], dict[tuple[str | None, ...], SqlInsertRow]
    ] = {}
    problems: list[SqlValidationProblem] = []

    for row in parse_insert_rows(content):
        business_keys = CATALOG_BUSINESS_KEYS.get(row.table, ())
        if not business_keys:
            continue
        row_by_column = dict(zip(row.columns, row.values))
        for business_key in business_keys:
            if not all(
                column in row_by_column for column in business_key.columns
            ):
                continue
            key_values = tuple(
                row_by_column[column] for column in business_key.columns
            )
            if business_key.ignore_blank and any(
                value in (None, "") for value in key_values
            ):
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
            previous_id = (
                previous.values[id_index] if id_index is not None else "?"
            )
            current_id = row.values[id_index] if id_index is not None else "?"
            problems.append(
                SqlValidationProblem(
                    path=relative_path,
                    rule="catalog business key duplicate",
                    detail=(
                        f"{row.table} key "
                        f"{business_key.columns}={key_values!r} "
                        "conflicts at lines "
                        f"{previous.line} and {row.line} "
                        f"(id {previous_id!r} vs {current_id!r})"
                    ),
                )
            )

    return problems


def non_idempotent_data_insert_scripts(source_repo: Path) -> list[Path]:
    """Находит full-state data INSERT SQL без повторяемой стратегии."""
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


def validate_backend_data_insert_sql(
    source_repo: Path,
) -> list[SqlValidationProblem]:
    """Запускает полный набор validation rules для backend data INSERT SQL."""
    scripts_root = source_repo / DATABASE_SCRIPTS_PREFIX
    problems = [
        SqlValidationProblem(
            path=path,
            rule="full-state idempotency",
            detail=(
                "INSERT script must use ON CONFLICT, TRUNCATE, MERGE, "
                "or DROP"
            ),
        )
        for path in non_idempotent_data_insert_scripts(source_repo)
    ]

    for directory in DATA_SQL_INSERT_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=False):
            relative_path = path.relative_to(source_repo)
            problems.extend(
                find_catalog_business_key_conflicts(path, relative_path)
            )

    for directory in DATA_SQL_MIXED_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=True):
            relative_path = path.relative_to(source_repo)
            problems.extend(
                find_catalog_business_key_conflicts(path, relative_path)
            )

    for directory in DATA_SQL_INSERT_IF_MISSING_DIRS:
        root = scripts_root / directory
        for path in iter_sql_files(root, include_insert_only=True):
            relative_path = path.relative_to(source_repo)
            if not is_insert_if_missing_idempotent(path):
                problems.append(
                    SqlValidationProblem(
                        path=relative_path,
                        rule="insert-if-missing idempotency",
                        detail=(
                            "insert_new_objects SQL must not TRUNCATE "
                            "and must use ON CONFLICT DO NOTHING"
                        ),
                    )
                )
            problems.extend(
                find_catalog_business_key_conflicts(path, relative_path)
            )

    return sorted(
        problems,
        key=lambda problem: (
            problem.path.as_posix(),
            problem.rule,
            problem.detail,
        ),
    )


def check_backend_data_insert_idempotency(
    reporter: Reporter, env: dict[str, str]
) -> None:
    """Проверяет idempotency data INSERT SQL до build."""
    source_repo = Path(require_value(env, "BACKEND_SOURCE_REPO_PATH"))
    scripts_root = source_repo / DATABASE_SCRIPTS_PREFIX
    if not scripts_root.is_dir():
        reporter.skip(
            "backend data INSERT idempotency",
            f"директория не найдена: {scripts_root}",
        )
        return

    problems = validate_backend_data_insert_sql(source_repo)
    if not problems:
        reporter.pass_(
            "backend data INSERT idempotency",
            "все INSERT-скрипты прошли validation rules",
        )
        return

    shown = [
        f"{problem.path.as_posix()}: {problem.rule}: {problem.detail}"
        for problem in problems[:20]
    ]
    suffix = (
        ""
        if len(problems) <= len(shown)
        else f"\n... и еще {len(problems) - len(shown)}"
    )
    reporter.fail(
        "backend data INSERT idempotency",
        f"найдено {len(problems)} SQL validation problem(s):\n"
        + "\n".join(shown)
        + suffix,
    )


def check_origin_network(
    reporter: Reporter, name: str, origin_url: str
) -> None:
    """Проверяет сетевую доступность HTTP(S) origin URL репозитория."""
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


def runtime_local_path(path_value: object) -> Path:
    """Преобразует runtime path в абсолютный локальный путь внутри ROOT."""
    path = Path(str(path_value)).expanduser()
    if path.is_absolute():
        return path
    return ROOT / path


def check_maintenance_stub_archive(reporter: Reporter, runtime: dict) -> None:
    """Проверяет наличие локального архива maintenance stub."""
    if not runtime.get("maintenance_stub_enabled", True):
        reporter.skip("maintenance stub archive", "disabled")
        return
    path = runtime_local_path(
        runtime.get(
            "maintenance_stub_archive_path", DEFAULT_MAINTENANCE_STUB_ARCHIVE
        )
    )
    if path.is_file():
        reporter.pass_("maintenance stub archive", str(path))
    else:
        reporter.fail("maintenance stub archive", f"not found: {path}")


def check_ssh_runtime(
    reporter: Reporter, env: dict[str, str], app_only: bool = False
) -> dict[str, bool]:
    """Проверяет SSH-доступ и базовые утилиты на APP и DB VM."""
    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    result = {"app": False, "db": False}

    app = ssh_command(
        env,
        app_user,
        app_host,
        "echo ok && command -v bash tar python find rm grep >/dev/null "
        "&& tar --help | grep -q -- '--strip-components'",
        "APP",
    )
    if app.rc == 0:
        reporter.pass_("app VM SSH/runtime", app.stdout.strip())
        result["app"] = True
    else:
        reporter.fail(
            "app VM SSH/runtime",
            (app.stderr or app.stdout).strip() or f"rc={app.rc}",
        )
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
        reporter.fail(
            "DB VM SSH/psql", (db.stderr or db.stdout).strip() or f"rc={db.rc}"
        )
        reporter.skip("DB SQL checks", "DB VM SSH/psql недоступен")
    return result


def check_db_psql_login(
    reporter: Reporter, env: dict[str, str], runtime: dict
) -> None:
    """Проверяет, что DB VM может подключиться к PostgreSQL через psql."""
    db_user = require_value(env, "DB_VM_USER")
    db_host = require_value(env, "DB_VM_HOST")
    psql_base, mask = db_psql_base_command(env, runtime)
    result = ssh_command(
        env,
        db_user,
        db_host,
        f"{psql_base} --command='SELECT 1;'",
        "DB",
        timeout=30,
        mask=mask,
    )
    output = (result.stdout or result.stderr).strip()
    if result.rc == 0:
        reporter.pass_(
            "DB psql login", output.splitlines()[0] if output else "SELECT 1"
        )
    else:
        for secret in mask:
            if secret:
                output = output.replace(secret, "***")
        reporter.fail("DB psql login", output or f"rc={result.rc}")


def check_outlook_email_config(reporter: Reporter, runtime: dict) -> None:
    """Проверяет runtime-настройки и COM-доступность Outlook email."""
    if not runtime.get("outlook_email_enabled", False):
        reporter.skip(
            "Outlook email", "отключено в windows_pipeline.local.json"
        )
        return

    recipients = normalize_email_list(
        runtime.get("outlook_email_recipients", [])
    )
    if recipients:
        reporter.pass_("Outlook email recipients", ", ".join(recipients))
    else:
        reporter.fail(
            "Outlook email recipients", "задайте outlook_email_recipients"
        )

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
        reporter.pass_(
            "Outlook email templates", "шаблоны темы и тела корректны"
        )
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
            "$ErrorActionPreference='Stop'; "
            "$outlook = New-Object -ComObject Outlook.Application; 'ok'",
        ],
    )


def derive_service_permission_check(command: str) -> str:
    """Строит permission-check команду для systemctl service step."""
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

    for index, token in enumerate(tokens[1:], start=1):
        if token in SYSTEMCTL_ACTIONS and token != "status":
            options = tokens[1:index]
            targets = tokens[index + 1 :]
            if not targets:
                return ""
            parts = ["systemctl", *options, "--dry-run", token, *targets]
            return " ".join(sh_quote(part) for part in parts)
    return ""


def sudo_list_command(command: str) -> str:
    """Преобразует sudo-команду в `sudo -n -l` проверку разрешений."""
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
    """Проверяет, начинается ли команда с sudo после shell-разбора."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    return bool(tokens and tokens[0] == "sudo")


def check_service_permissions(
    reporter: Reporter, env: dict[str, str], runtime: dict
) -> None:
    """Проверяет права APP VM пользователя на выполнение service_steps."""
    if not runtime.get("service_permission_checks_enabled", True):
        reporter.skip("service permission checks", "disabled")
        return

    steps = runtime.get("service_steps", [])
    if not steps:
        reporter.skip("service permission checks", "service_steps empty")
        return

    app_user = require_value(env, "APP_VM_USER")
    app_host = require_value(env, "APP_VM_HOST")
    if any(
        is_sudo_command(
            str(
                step.get("permission_check_command") or step.get("command", "")
            ).strip()
        )
        for step in steps
    ):
        sudo_list_result = ssh_command(
            env, app_user, app_host, "sudo -n -l", "APP", timeout=30
        )
        sudo_list_output = (
            sudo_list_result.stdout or sudo_list_result.stderr
        ).strip()
        if sudo_list_result.rc == 0:
            reporter.pass_(
                "sudo allowed commands",
                sudo_list_output.splitlines()[0]
                if sudo_list_output
                else "sudo -n -l",
            )
        else:
            reporter.fail(
                "sudo allowed commands",
                sudo_list_output or f"rc={sudo_list_result.rc}",
            )

    for index, step in enumerate(steps, start=1):
        label = step.get("name") or f"service step #{index}"
        command = str(step.get("command", "")).strip()
        check_command_text = str(
            step.get("permission_check_command", "")
        ).strip()
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
            sudo_result = ssh_command(
                env, app_user, app_host, sudo_check, "APP", timeout=30
            )
            sudo_output = (sudo_result.stdout or sudo_result.stderr).strip()
            if sudo_result.rc == 0:
                reporter.pass_(
                    f"sudo permission {label}",
                    sudo_output.splitlines()[0] if sudo_output else sudo_check,
                )
                continue
            else:
                reporter.fail(
                    f"sudo permission {label}",
                    sudo_output or f"rc={sudo_result.rc}",
                )
                continue

        result = ssh_command(
            env, app_user, app_host, check_command_text, "APP", timeout=30
        )
        output = (result.stdout or result.stderr).strip()
        if result.rc == 0 or is_readable_systemctl_status_result(
            check_command_text, result
        ):
            detail = output.splitlines()[0] if output else check_command_text
            if derived_check:
                detail = (
                    f"{detail} (systemctl --dry-run; "
                    "authorization not guaranteed)"
                )
            if result.rc != 0:
                detail = f"{detail} (status readable; unit may be inactive)"
            reporter.pass_(f"service permission {label}", detail)
        else:
            reporter.fail(
                f"service permission {label}", output or f"rc={result.rc}"
            )


def check_remote_directory(
    reporter: Reporter,
    env: dict[str, str],
    name: str,
    path_value: str,
) -> None:
    """Проверяет существование и rwx-доступность APP каталога."""
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
        'stat -c "target %A %a owner=%U(%u) group=%G(%g) %n" '
        '"$path" 2>&1 || true; '
        'echo "parent permissions:"; '
        'namei -l "$path" 2>&1 || true; '
        "if command -v getfacl >/dev/null 2>&1; then "
        'echo "target ACL:"; '
        'getfacl -p "$path" 2>&1 || true; '
        "fi; "
        'if [ ! -e "$path" ]; then '
        'echo "missing path or parent directory is not searchable"; '
        'parent=$(dirname "$path"); '
        'stat -c "parent %A %a owner=%U(%u) group=%G(%g) %n" '
        '"$parent" 2>&1 || true; '
        "exit 10; "
        "fi; "
        'if [ ! -d "$path" ]; then '
        'echo "path exists but is not a directory"; '
        'stat -c "target %A %a owner=%U(%u) group=%G(%g) %n" '
        '"$path" 2>&1 || true; '
        "exit 11; "
        "fi; "
        'if [ ! -r "$path" ] || [ ! -w "$path" ] || [ ! -x "$path" ]; then '
        'echo "directory is not rwx for effective user/groups"; '
        'stat -c "target %A %a owner=%U(%u) group=%G(%g) %n" '
        '"$path" 2>&1 || true; '
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


def check_app_deploy_directories(
    reporter: Reporter, env: dict[str, str], runtime: dict
) -> None:
    """Проверяет удаленные каталоги для deploy application artifacts."""
    directories = [
        ("remote tmp root", require_value(env, "REMOTE_TMP_ROOT")),
        ("backend release path", require_value(env, "BACKEND_RELEASE_PATH")),
        ("frontend release path", require_value(env, "FRONTEND_RELEASE_PATH")),
        ("app workdir", require_value(env, "APP_WORKDIR")),
    ]
    if runtime.get("backup_enabled", False):
        directories.append(
            (
                "backup root base",
                env.get("BACKUP_ROOT_BASE", "/tmp/simple-deploy-backups"),
            )
        )

    for name, path in directories:
        check_remote_directory(reporter, env, name, path)


def check_app_manage_py(reporter: Reporter, env: dict[str, str]) -> None:
    """Проверяет доступность manage.py относительно APP_WORKDIR на APP VM."""
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
        reporter.fail(
            "app manage.py path",
            output
            or f"not found/readable from APP_WORKDIR: "
            f"{app_workdir}/{manage_py}",
        )


def check_http(
    reporter: Reporter, env: dict[str, str], validate_certs: bool
) -> None:
    """Проверяет доступность DEV HTTPS endpoint-а."""
    url = f"https://{require_value(env, 'DEV_DOMAIN')}/"
    context = None if validate_certs else ssl._create_unverified_context()
    try:
        with request.urlopen(
            url, timeout=DEFAULT_TIMEOUT, context=context
        ) as response:
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


__all__ = [
    "Reporter",
    "is_readable_systemctl_status_result",
    "check_command",
    "check_windows_command",
    "check_ssh_key_files",
    "check_repo",
    "check_backend_build_inputs",
    "is_data_insert_idempotent",
    "is_insert_if_missing_idempotent",
    "iter_sql_files",
    "split_sql_statements",
    "split_sql_csv",
    "iter_values_tuples",
    "parse_sql_literal",
    "normalize_sql_table",
    "parse_insert_rows",
    "find_catalog_business_key_conflicts",
    "non_idempotent_data_insert_scripts",
    "validate_backend_data_insert_sql",
    "check_backend_data_insert_idempotency",
    "check_origin_network",
    "runtime_local_path",
    "check_maintenance_stub_archive",
    "check_ssh_runtime",
    "check_db_psql_login",
    "check_outlook_email_config",
    "derive_service_permission_check",
    "sudo_list_command",
    "is_sudo_command",
    "check_service_permissions",
    "check_remote_directory",
    "check_app_deploy_directories",
    "check_app_manage_py",
    "check_http",
    "CATALOG_BUSINESS_KEYS",
    "DATABASE_SCRIPTS_PREFIX",
    "DATA_SQL_INSERT_DIRS",
    "DATA_SQL_INSERT_IF_MISSING_DIRS",
    "DATA_SQL_MIXED_DIRS",
    "SqlBusinessKey",
    "SqlInsertRow",
    "SqlValidationProblem",
]
