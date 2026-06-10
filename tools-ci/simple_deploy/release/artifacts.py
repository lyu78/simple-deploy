"""Примитивы артефактов релиза и их локальный резолвинг.

Модуль описывает файлы, которые уже лежат в директории собранного релиза, и
строит для них локальные и удаленные пути. Источником истины здесь является
директория релиза и runtime-конфигурация оператора; модуль не создает архивы,
не меняет SQLite-состояние и не выполняет загрузку или распаковку на VM.
"""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
from pathlib import Path

from simple_deploy.release.state import validate_contour


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAINTENANCE_STUB_ARCHIVE = "tools-ci/maintenance_stub/maintenance_stub.tar.gz"


@dataclass
class Artifact:
    """Описание прикладного артефакта для загрузки и распаковки на app VM.

    ``local_path`` указывает на архив в директории релиза, ``remote_archive`` -
    на временный путь загрузки на VM, а ``extract_path`` - на целевой каталог,
    который будет очищен и заполнен на этапе deploy.
    """

    name: str
    local_path: Path
    remote_archive: str
    extract_path: str


@dataclass
class DbSqlArtifact:
    """Описание SQL-артефакта, который будет применяться на DB VM.

    Помимо локального архива и удаленного каталога распаковки запись хранит
    директорию и glob-шаблон entrypoint-файла внутри архива. Это позволяет
    deploy-процессу проверить, что в архиве ровно один ожидаемый SQL или shell
    runner.
    """

    name: str
    local_path: Path
    remote_archive: str
    remote_extract_path: str
    entrypoint_dir: str
    entrypoint_pattern: str


def require_value(env: dict[str, str], name: str) -> str:
    """Возвращает обязательное значение runtime-окружения.

    Функция принимает словарь окружения, нормализует значение через ``strip`` и
    падает с явной ошибкой, если переменная отсутствует или пуста. Она не читает
    ``os.environ`` напрямую: источником истины остается уже собранный runtime
    env, переданный вызывающим процессом.
    """
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная: {name}")
    return value


def runtime_local_path(path_value: object) -> Path:
    """Преобразует настройку локального пути в абсолютный ``Path``.

    Абсолютные пути возвращаются как есть, а относительные считаются
    относительно корня репозитория simple-deploy. Функция не проверяет
    существование файла: это делает конкретный резолвер, которому известен
    смысл артефакта.
    """
    path = Path(str(path_value)).expanduser()
    if path.is_absolute():
        return path
    return ROOT / path


def resolve_artifacts(env: dict[str, str], build_version: str, release_dir: Path) -> list[Artifact]:
    """Находит backend/frontend архивы для deploy приложения.

    Функция принимает runtime env, версию релиза и директорию релиза, затем
    ищет архивы по текущим контрактным шаблонам имен. Возвращаемые записи
    содержат локальные пути и удаленные target paths, но сама функция не
    загружает файлы и не меняет состояние релиза.
    """
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


def resolve_db_schema_artifact(
    env: dict[str, str],
    build_version: str,
    release_dir: Path,
    contour: str = "dev",
) -> DbSqlArtifact:
    """Находит schema SQL-архив для выбранного контура.

    Источником истины является директория релиза, где builder уже создал
    контурный schema-архив по Git range из baseline до текущего backend commit.
    Функция валидирует имя контура и строит удаленные пути для DB VM, но не
    проверяет реальное состояние базы данных.
    """
    contour = validate_contour(contour)
    print(f"RESOLVE DB schema artifact in: {release_dir}", flush=True)
    if not release_dir.is_dir():
        raise RuntimeError(f"Директория релиза не существует: {release_dir}")

    pattern = f"db_schema_{contour}_r_{build_version}-c_*.tar.gz"
    matches = [path for path in release_dir.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern)]
    if not matches:
        raise RuntimeError(f"В {release_dir} не найден DB schema архив по шаблону {pattern}")

    newest = max(matches, key=lambda path: path.stat().st_mtime)
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    artifact = DbSqlArtifact(
        name=f"db_schema_{contour}",
        local_path=newest,
        remote_archive=f"{remote_dir}/db_schema_{contour}.tar.gz",
        remote_extract_path=f"{remote_dir}/db_schema_{contour}",
        entrypoint_dir=".",
        entrypoint_pattern=f"summary_sql_{contour}_*.sql",
    )
    print(
        f"RESOLVE DB schema artifact: {artifact.local_path.name} -> {artifact.remote_extract_path}",
        flush=True,
    )
    return artifact


def resolve_db_data_artifact(
    env: dict[str, str],
    build_version: str,
    release_dir: Path,
    kind: str,
) -> DbSqlArtifact:
    """Находит data SQL-архив заданного вида.

    Поддерживаются только виды, которые deploy-процесс умеет применять
    автоматически: ``insert`` и ``update_parallel``. Функция возвращает
    описание entrypoint-файла внутри архива и не выполняет SQL; фактическое
    применение остается ответственностью процесса deploy.
    """
    specs = {
        "insert": (
            "db_insert",
            f"db_insert_r_{build_version}-c_*.tar.gz",
            "db_insert.tar.gz",
            "db_insert",
            "run_all_insert_*.sql",
        ),
        "update_parallel": (
            "db_update_parallel",
            f"db_update_parallel_r_{build_version}-c_*.tar.gz",
            "db_update_parallel.tar.gz",
            "db_update_parallel",
            "run_all_update_parallel_*.sh",
        ),
    }
    if kind not in specs:
        raise RuntimeError(f"Unsupported DB data artifact kind: {kind}")
    if not release_dir.is_dir():
        raise RuntimeError(f"Release directory does not exist: {release_dir}")

    name, pattern, remote_archive_name, remote_extract_name, entrypoint_pattern = specs[kind]
    print(f"RESOLVE DB data artifact {name} in: {release_dir}", flush=True)
    matches = [path for path in release_dir.iterdir() if path.is_file() and fnmatch.fnmatch(path.name, pattern)]
    if not matches:
        raise RuntimeError(f"DB data artifact not found in {release_dir} by pattern {pattern}")

    newest = max(matches, key=lambda path: path.stat().st_mtime)
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    artifact = DbSqlArtifact(
        name=name,
        local_path=newest,
        remote_archive=f"{remote_dir}/{remote_archive_name}",
        remote_extract_path=f"{remote_dir}/{remote_extract_name}",
        entrypoint_dir=".",
        entrypoint_pattern=entrypoint_pattern,
    )
    print(
        f"RESOLVE DB data artifact {name}: {artifact.local_path.name} -> {artifact.remote_extract_path}",
        flush=True,
    )
    return artifact


def resolve_maintenance_stub_artifact(env: dict[str, str], runtime: dict, build_version: str) -> Artifact:
    """Создает описание архива maintenance stub для full deploy.

    Локальный путь берется из runtime-конфигурации или default-значения, а
    целевой каталог берется из ``FRONTEND_RELEASE_PATH``. Функция проверяет
    наличие локального архива, но не распаковывает его и не проверяет HTTP
    marker заглушки.
    """
    local_path = runtime_local_path(runtime.get("maintenance_stub_archive_path", DEFAULT_MAINTENANCE_STUB_ARCHIVE))
    if not local_path.is_file():
        raise RuntimeError(f"Maintenance stub archive not found: {local_path}")
    remote_dir = f"{require_value(env, 'REMOTE_TMP_ROOT').rstrip('/')}/{build_version}"
    artifact = Artifact(
        name="maintenance_stub",
        local_path=local_path,
        remote_archive=f"{remote_dir}/maintenance_stub.tar.gz",
        extract_path=require_value(env, "FRONTEND_RELEASE_PATH"),
    )
    print(f"RESOLVE maintenance stub: {artifact.local_path} -> {artifact.extract_path}", flush=True)
    return artifact


def require_artifact(artifacts: list[Artifact], name: str) -> Artifact:
    """Возвращает обязательный app-артефакт из уже разрешенного списка.

    Функция используется после ``resolve_artifacts``, когда deploy-процессу
    нужно явно получить архив backend или frontend. Отсутствие нужного
    артефакта считается ошибкой текущей директории релиза.
    """
    for artifact in artifacts:
        if artifact.name == name:
            return artifact
    raise RuntimeError(f"Resolved app artifact is missing: {name}")


__all__ = [
    "DEFAULT_MAINTENANCE_STUB_ARCHIVE",
    "Artifact",
    "DbSqlArtifact",
    "require_artifact",
    "require_value",
    "resolve_artifacts",
    "resolve_db_data_artifact",
    "resolve_db_schema_artifact",
    "resolve_maintenance_stub_artifact",
    "runtime_local_path",
]
