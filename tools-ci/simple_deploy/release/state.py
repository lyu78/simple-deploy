"""Локальное состояние релизов и контуров в SQLite.

Модуль хранит операционную историю simple-deploy: какие релизы были собраны,
какой backend commit считается последним успешно примененным на каждом контуре
(``dev``, ``test``, ``prod``), и какие попытки применения завершились успехом
или ошибкой. Упавшие сборки хранятся отдельно от ``releases``, чтобы таблица
    релизов оставалась журналом только успешно собранных manifest-файлов.

SQLite используется как локальный журнал рабочей машины. Он не заменяет
``release_manifest.json``: manifest остается переносимым описанием конкретного
релиза, а SQLite отвечает за текущее локальное представление состояния
контуров. Поэтому база лежит в ``local_state/`` и не коммитится в Git.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable


CONTOURS = ("dev", "test", "prod")
JOB_STATUSES = ("queued", "running", "success", "failed", "cancelled")
REQUEST_STATUSES = ("draft", "submitted", "approved", "applied", "failed", "cancelled")


@dataclass(frozen=True)
class ContourState:
    """Снимок baseline одного deploy-контура.

    Запись отражает последний релиз и backend commit, которые оператор или
    deploy-процесс уже считает успешно примененными на контуре. Именно эта
    запись используется builder-ом как baseline для следующего offline SQL
    Git range.
    """

    contour: str
    last_success_release: str
    last_success_backend_commit: str
    updated_at: str


@dataclass(frozen=True)
class JobRecord:
    """Снимок локальной долгой операции.

    Запись хранится в таблице ``local_jobs`` и описывает состояние операции,
    которую web/API или CLI может запускать асинхронно: тип, контур, версию
    релиза, payload, путь к логу и итоговый статус. Сама запись не выполняет
    процесс, а только фиксирует его жизненный цикл.
    """

    id: int
    kind: str
    contour: str
    build_version: str
    status: str
    payload_json: str
    log_path: str
    error: str
    created_at: str
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class ExternalRequest:
    """Снимок внешней заявки на продвижение релиза.

    Запись предназначена для TEST/PROD, где применение релиза может проходить
    через ручной или внешний процесс. Она хранит связь build version с внешним
    идентификатором заявки и ее статусом, но не двигает baseline контура сама.
    """

    id: int
    contour: str
    build_version: str
    request_type: str
    status: str
    external_id: str
    payload_json: str
    error: str
    created_at: str
    updated_at: str


def default_state_db_path() -> Path:
    """Возвращает путь к локальной SQLite-базе состояния релизов.

    Переменная ``SIMPLE_DEPLOY_STATE_DB`` имеет приоритет для тестов и
    операторских переопределений. Если она не задана, источником истины считается
    стандартная база ``local_state/simple_deploy.sqlite3`` в корне репозитория.
    """
    configured = os.environ.get("SIMPLE_DEPLOY_STATE_DB", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "local_state" / "simple_deploy.sqlite3"


def utc_now() -> str:
    """Возвращает текущий UTC timestamp для записей локального журнала.

    Формат одинаков для всех таблиц слоя состояния: ISO-временная метка с точностью до
    секунд и суффиксом ``Z``. Функция не обращается к базе и нужна только для
    единообразной сериализации времени.
    """
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def validate_contour(contour: str) -> str:
    """Нормализует и валидирует имя deploy-контура.

    На вход принимается пользовательская или runtime-строка. Возвращаемое
    значение всегда lower-case и входит в ``CONTOURS``; неизвестные контуры
    считаются ошибкой конфигурации или API-запроса.
    """
    normalized = contour.strip().lower()
    if normalized not in CONTOURS:
        raise ValueError(f"Unknown contour: {contour}. Expected one of: {', '.join(CONTOURS)}")
    return normalized


def connect_state_db(path: Path | None = None) -> sqlite3.Connection:
    """Открывает SQLite-соединение и гарантирует наличие схемы.

    Если путь не передан, используется ``default_state_db_path``. Функция
    создает родительскую директорию, включает ``sqlite3.Row`` для доступа по
    именам колонок и вызывает ``ensure_schema`` перед возвратом соединения.
    """
    db_path = path or default_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Создает или обновляет базовую схему локального журнала.

    Функция идемпотентна: она создает таблицы и индексы через
    ``create table/index if not exists`` и не удаляет существующие данные.
    Здесь фиксируется формат SQLite как локального источника состояния
    релизов, попыток, заданий и внешних заявок.
    """
    connection.executescript(
        """
        create table if not exists contour_state (
            contour text primary key,
            last_success_release text not null,
            last_success_backend_commit text not null,
            updated_at text not null
        );

        create table if not exists releases (
            build_version text primary key,
            backend_commit text not null,
            frontend_commit text,
            artifacts_json text not null,
            created_at text not null
        );

        create table if not exists build_attempts (
            id integer primary key autoincrement,
            build_version text not null,
            status text not null,
            backend_commit text,
            frontend_commit text,
            error text,
            started_at text not null,
            finished_at text not null
        );

        create table if not exists deployment_attempts (
            id integer primary key autoincrement,
            contour text not null,
            build_version text not null,
            backend_commit text,
            status text not null,
            error text,
            started_at text not null,
            finished_at text not null
        );

        create table if not exists local_jobs (
            id integer primary key autoincrement,
            kind text not null,
            contour text not null,
            build_version text not null,
            status text not null,
            payload_json text not null,
            log_path text not null,
            error text not null,
            created_at text not null,
            started_at text not null,
            finished_at text not null
        );

        create index if not exists idx_local_jobs_status_created
            on local_jobs(status, created_at);

        create index if not exists idx_local_jobs_contour_build
            on local_jobs(contour, build_version);

        create table if not exists external_requests (
            id integer primary key autoincrement,
            contour text not null,
            build_version text not null,
            request_type text not null,
            status text not null,
            external_id text not null,
            payload_json text not null,
            error text not null,
            created_at text not null,
            updated_at text not null
        );

        create index if not exists idx_external_requests_contour_build
            on external_requests(contour, build_version);

        create index if not exists idx_external_requests_status_updated
            on external_requests(status, updated_at);
        """
    )
    connection.commit()


def validate_status(status: str, allowed: Iterable[str]) -> str:
    """Нормализует и валидирует статус для конкретного набора значений.

    Вызывающий код передает разрешенный набор статусов, потому что попытки
    сборки, задания и внешние заявки имеют разные жизненные циклы. Функция
    возвращает статус в нижнем регистре или падает до записи некорректного
    значения в SQLite.
    """
    normalized = status.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unknown status: {status}. Expected one of: {', '.join(sorted(allowed))}")
    return normalized


def get_contour_state(connection: sqlite3.Connection, contour: str) -> ContourState | None:
    """Читает baseline одного контура из SQLite.

    Возвращает ``None``, если baseline еще не задан. Функция только читает
    таблицу ``contour_state`` и не двигает baseline; изменение выполняется
    через ``upsert_contour_state``.
    """
    contour = validate_contour(contour)
    row = connection.execute(
        """
        select contour, last_success_release, last_success_backend_commit, updated_at
        from contour_state
        where contour = ?
        """,
        (contour,),
    ).fetchone()
    if not row:
        return None
    return ContourState(
        contour=row["contour"],
        last_success_release=row["last_success_release"],
        last_success_backend_commit=row["last_success_backend_commit"],
        updated_at=row["updated_at"],
    )


def all_contour_states(connection: sqlite3.Connection) -> dict[str, ContourState | None]:
    """Возвращает baseline-состояние всех поддерживаемых контуров.

    Словарь всегда содержит ключи из ``CONTOURS``. Значение ``None`` означает,
    что для конкретного контура baseline еще отсутствует в локальной SQLite
    базе.
    """
    return {contour: get_contour_state(connection, contour) for contour in CONTOURS}


def upsert_contour_state(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    backend_commit: str,
) -> None:
    """Создает или обновляет baseline успешного применения релиза.

    Эта функция двигает baseline контура: после ее выполнения следующий build
    будет считать указанный backend commit уже примененным на этом контуре.
    Вызывать ее можно только после подтвержденного успешного deploy или явной
    ручной фиксации оператором.
    """
    contour = validate_contour(contour)
    connection.execute(
        """
        insert into contour_state (
            contour,
            last_success_release,
            last_success_backend_commit,
            updated_at
        )
        values (?, ?, ?, ?)
        on conflict(contour) do update set
            last_success_release = excluded.last_success_release,
            last_success_backend_commit = excluded.last_success_backend_commit,
            updated_at = excluded.updated_at
        """,
        (contour, build_version, backend_commit, utc_now()),
    )
    connection.commit()


def record_release(
    connection: sqlite3.Connection,
    build_version: str,
    backend_commit: str,
    frontend_commit: str | None,
    artifacts: dict,
) -> None:
    """Записывает метаданные успешно собранного релиза в SQLite.

    Таблица ``releases`` является журналом артефактов сборки с manifest и не
    означает, что релиз применен на каком-либо контуре. Функция не двигает
    baseline; это делает только ``upsert_contour_state`` после успешного
    применения.
    """
    connection.execute(
        """
        insert into releases (
            build_version,
            backend_commit,
            frontend_commit,
            artifacts_json,
            created_at
        )
        values (?, ?, ?, ?, ?)
        on conflict(build_version) do update set
            backend_commit = excluded.backend_commit,
            frontend_commit = excluded.frontend_commit,
            artifacts_json = excluded.artifacts_json,
            created_at = excluded.created_at
        """,
        (
            build_version,
            backend_commit,
            frontend_commit,
            json.dumps(artifacts, ensure_ascii=False, sort_keys=True),
            utc_now(),
        ),
    )
    connection.commit()


def record_build_attempt_started(
    connection: sqlite3.Connection,
    build_version: str,
    backend_commit: str = "",
    frontend_commit: str = "",
) -> int:
    """Создает запись о начале попытки сборки релиза.

    Функция пишет статус ``started`` в ``build_attempts`` и возвращает id
    попытки для последующего завершения. Она не создает запись в ``releases``:
    успешный релиз фиксируется отдельно после создания manifest.
    """
    now = utc_now()
    cursor = connection.execute(
        """
        insert into build_attempts (
            build_version,
            status,
            backend_commit,
            frontend_commit,
            error,
            started_at,
            finished_at
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (build_version, "started", backend_commit, frontend_commit, "", now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def record_build_attempt_finished(
    connection: sqlite3.Connection,
    attempt_id: int,
    status: str,
    backend_commit: str = "",
    frontend_commit: str = "",
    error: str = "",
) -> None:
    """Фиксирует итог ранее начатой попытки сборки.

    Допустимы только статусы ``success`` и ``failed``. Функция обновляет журнал
    попыток сборки и не меняет таблицу ``releases`` или baseline контуров.
    """
    status = validate_status(status, {"success", "failed"})
    connection.execute(
        """
        update build_attempts
        set
            status = ?,
            backend_commit = ?,
            frontend_commit = ?,
            error = ?,
            finished_at = ?
        where id = ?
        """,
        (status, backend_commit, frontend_commit, error, utc_now(), attempt_id),
    )
    connection.commit()


def record_attempt(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    backend_commit: str,
    status: str,
    error: str = "",
) -> None:
    """Добавляет запись о попытке применения релиза на контур.

    Это журнал результатов deploy/mark, а не источник baseline сам по себе.
    Даже запись со статусом ``success`` не двигает baseline автоматически:
    вызывающий процесс должен отдельно вызвать ``upsert_contour_state`` в
    точке, где успешное применение считается подтвержденным.
    """
    contour = validate_contour(contour)
    now = utc_now()
    connection.execute(
        """
        insert into deployment_attempts (
            contour,
            build_version,
            backend_commit,
            status,
            error,
            started_at,
            finished_at
        )
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (contour, build_version, backend_commit, status, error, now, now),
    )
    connection.commit()


def missing_baselines(connection: sqlite3.Connection, contours: Iterable[str] = CONTOURS) -> list[str]:
    """Возвращает список контуров без заданного baseline.

    Builder использует такую проверку перед offline SQL generation, потому что
    Git range для schema SQL невозможно построить без исходного commit по
    каждому требуемому контуру.
    """
    missing = []
    for contour in contours:
        if get_contour_state(connection, contour) is None:
            missing.append(contour)
    return missing


def _json_payload(payload: dict | None) -> str:
    """Сериализует payload записи слоя состояния в JSON.

    ``None`` трактуется как пустой объект, чтобы в SQLite не появлялись пустые
    строки с неоднозначным смыслом. Сортировка ключей делает значение
    стабильным для тестов и чтения.
    """
    return json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    """Преобразует строку ``local_jobs`` в ``JobRecord``.

    Функция централизует маппинг колонок SQLite в dataclass-модель, чтобы API и тесты
    получали один и тот же тип независимо от конкретного select-запроса.
    """
    return JobRecord(
        id=int(row["id"]),
        kind=row["kind"],
        contour=row["contour"],
        build_version=row["build_version"],
        status=row["status"],
        payload_json=row["payload_json"],
        log_path=row["log_path"],
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _external_request_from_row(row: sqlite3.Row) -> ExternalRequest:
    """Преобразует строку ``external_requests`` в ``ExternalRequest``.

    Маппер не валидирует бизнес-правила повторно: предполагается, что данные
    уже прошли через функции создания или обновления записи.
    """
    return ExternalRequest(
        id=int(row["id"]),
        contour=row["contour"],
        build_version=row["build_version"],
        request_type=row["request_type"],
        status=row["status"],
        external_id=row["external_id"],
        payload_json=row["payload_json"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _dict_from_row(row: sqlite3.Row) -> dict:
    """Преобразует произвольную SQLite-строку в словарь.

    Используется для таблиц, где сейчас не введены отдельные dataclass-модели.
    Имена колонок сохраняются без переименования, чтобы API отражал текущий
    формат локальной базы.
    """
    return {key: row[key] for key in row.keys()}


def list_releases(connection: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Возвращает последние успешно собранные релизы.

    Данные читаются из таблицы ``releases`` и отражают только релизы, для
    которых builder записал manifest. Порядок сортировки ориентирован на
    свежие записи; baseline контуров здесь не учитывается.
    """
    rows = connection.execute(
        """
        select *
        from releases
        order by created_at desc, build_version desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [_dict_from_row(row) for row in rows]


def list_build_attempts(connection: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Возвращает последние попытки сборки релиза.

    Функция читает журнал ``build_attempts`` и не объединяет его с таблицей
    ``releases``. Это позволяет видеть как успешные, так и упавшие сборки.
    """
    rows = connection.execute(
        """
        select *
        from build_attempts
        order by id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [_dict_from_row(row) for row in rows]


def list_deployment_attempts(
    connection: sqlite3.Connection,
    contour: str = "",
    limit: int = 50,
) -> list[dict]:
    """Возвращает последние попытки применения релиза.

    При переданном ``contour`` список фильтруется по одному контуру, иначе
    возвращается общий журнал. Функция не вычисляет текущий baseline, а только
    читает историю попыток из ``deployment_attempts``.
    """
    if contour:
        contour = validate_contour(contour)
        rows = connection.execute(
            """
            select *
            from deployment_attempts
            where contour = ?
            order by id desc
            limit ?
            """,
            (contour, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select *
            from deployment_attempts
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [_dict_from_row(row) for row in rows]


def create_job(
    connection: sqlite3.Connection,
    kind: str,
    contour: str = "",
    build_version: str = "",
    payload: dict | None = None,
    log_path: str = "",
) -> int:
    """Создает запись локальной долгой операции в статусе ``queued``.

    Запись попадает в ``local_jobs`` со статусом ``queued`` и может быть позже
    переведена в ``running`` или терминальный статус. Функция только фиксирует
    намерение выполнить работу; исполнитель процесса здесь не запускается.
    """
    kind = kind.strip()
    if not kind:
        raise ValueError("Job kind must be non-empty")
    normalized_contour = validate_contour(contour) if contour else ""
    now = utc_now()
    cursor = connection.execute(
        """
        insert into local_jobs (
            kind,
            contour,
            build_version,
            status,
            payload_json,
            log_path,
            error,
            created_at,
            started_at,
            finished_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (kind, normalized_contour, build_version, "queued", _json_payload(payload), log_path, "", now, "", ""),
    )
    connection.commit()
    return int(cursor.lastrowid)


def mark_job_started(connection: sqlite3.Connection, job_id: int, log_path: str = "") -> None:
    """Помечает локальное задание как запущенное.

    Функция обновляет статус на ``running`` и время старта. Если передан
    ``log_path``, он становится источником пути к логу для UI/API; пустое
    значение сохраняет уже записанный путь.
    """
    connection.execute(
        """
        update local_jobs
        set status = ?, log_path = coalesce(nullif(?, ''), log_path), started_at = ?
        where id = ?
        """,
        ("running", log_path, utc_now(), job_id),
    )
    connection.commit()


def mark_job_finished(connection: sqlite3.Connection, job_id: int, status: str, error: str = "") -> None:
    """Помечает локальное задание терминальным статусом.

    Допустимы статусы ``success``, ``failed`` и ``cancelled``. Функция пишет
    итоговую ошибку и время завершения, но не выполняет компенсационные
    действия процесса.
    """
    status = validate_status(status, {"success", "failed", "cancelled"})
    connection.execute(
        """
        update local_jobs
        set status = ?, error = ?, finished_at = ?
        where id = ?
        """,
        (status, error, utc_now(), job_id),
    )
    connection.commit()


def get_job(connection: sqlite3.Connection, job_id: int) -> JobRecord | None:
    """Возвращает локальное задание по id.

    ``None`` означает, что записи с таким id нет в текущей SQLite-базе. Функция
    только читает ``local_jobs`` и не меняет статус задания.
    """
    row = connection.execute(
        """
        select *
        from local_jobs
        where id = ?
        """,
        (job_id,),
    ).fetchone()
    return _job_from_row(row) if row else None


def list_jobs(connection: sqlite3.Connection, limit: int = 50) -> list[JobRecord]:
    """Возвращает последние локальные задания.

    Список сортируется по id в обратном порядке, что соответствует порядку
    создания записей. Функция используется web/API панелью как источник истории
    долгих операций только для чтения.
    """
    rows = connection.execute(
        """
        select *
        from local_jobs
        order by id desc
        limit ?
        """,
        (limit,),
    ).fetchall()
    return [_job_from_row(row) for row in rows]


def create_external_request(
    connection: sqlite3.Connection,
    contour: str,
    build_version: str,
    request_type: str,
    external_id: str = "",
    payload: dict | None = None,
    status: str = "draft",
) -> int:
    """Создает запись внешней заявки для TEST/PROD.

    Контур ``dev`` запрещен, потому что DEV применяется локально управляемым
    deploy-процессом. Функция пишет заявку в SQLite, но не отправляет ее во
    внешнюю систему и не меняет baseline контура.
    """
    contour = validate_contour(contour)
    if contour == "dev":
        raise ValueError("External release requests are only supported for test/prod contours")
    request_type = request_type.strip()
    if not request_type:
        raise ValueError("External request type must be non-empty")
    status = validate_status(status, REQUEST_STATUSES)
    now = utc_now()
    cursor = connection.execute(
        """
        insert into external_requests (
            contour,
            build_version,
            request_type,
            status,
            external_id,
            payload_json,
            error,
            created_at,
            updated_at
        )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (contour, build_version, request_type, status, external_id, _json_payload(payload), "", now, now),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_external_request_status(
    connection: sqlite3.Connection,
    request_id: int,
    status: str,
    error: str = "",
    external_id: str | None = None,
) -> None:
    """Обновляет статус внешней заявки TEST/PROD.

    Функция валидирует статус, обновляет ошибку и при необходимости внешний id.
    Она не интерпретирует ``applied`` как успешное применение релиза: baseline
    должен двигаться отдельной ручной фиксацией результата.
    """
    status = validate_status(status, REQUEST_STATUSES)
    if external_id is None:
        connection.execute(
            """
            update external_requests
            set status = ?, error = ?, updated_at = ?
            where id = ?
            """,
            (status, error, utc_now(), request_id),
        )
    else:
        connection.execute(
            """
            update external_requests
            set status = ?, external_id = ?, error = ?, updated_at = ?
            where id = ?
            """,
            (status, external_id, error, utc_now(), request_id),
        )
    connection.commit()


def get_external_request(connection: sqlite3.Connection, request_id: int) -> ExternalRequest | None:
    """Возвращает внешнюю заявку по id.

    ``None`` означает отсутствие записи в локальной SQLite-базе. Функция не
    обращается к внешнему трекеру заявок и показывает только локально
    зафиксированное состояние.
    """
    row = connection.execute(
        """
        select *
        from external_requests
        where id = ?
        """,
        (request_id,),
    ).fetchone()
    return _external_request_from_row(row) if row else None


def list_external_requests(
    connection: sqlite3.Connection,
    contour: str = "",
    limit: int = 50,
) -> list[ExternalRequest]:
    """Возвращает последние внешние заявки TEST/PROD.

    При переданном ``contour`` список фильтруется по контуру, иначе читается
    общий журнал. Источником истины является локальная таблица
    ``external_requests``; внешняя система здесь не опрашивается.
    """
    if contour:
        contour = validate_contour(contour)
        rows = connection.execute(
            """
            select *
            from external_requests
            where contour = ?
            order by id desc
            limit ?
            """,
            (contour, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            select *
            from external_requests
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [_external_request_from_row(row) for row in rows]


__all__ = [
    "CONTOURS",
    "JOB_STATUSES",
    "REQUEST_STATUSES",
    "ContourState",
    "ExternalRequest",
    "JobRecord",
    "all_contour_states",
    "connect_state_db",
    "create_external_request",
    "create_job",
    "default_state_db_path",
    "ensure_schema",
    "get_contour_state",
    "get_external_request",
    "get_job",
    "list_build_attempts",
    "list_deployment_attempts",
    "list_external_requests",
    "list_jobs",
    "list_releases",
    "mark_job_finished",
    "mark_job_started",
    "missing_baselines",
    "record_attempt",
    "record_build_attempt_finished",
    "record_build_attempt_started",
    "record_release",
    "update_external_request_status",
    "upsert_contour_state",
    "utc_now",
    "validate_contour",
    "validate_status",
]
