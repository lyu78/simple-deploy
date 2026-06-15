"""Web/API поверхность только для чтения над локальным состоянием релизов.

Модуль предоставляет FastAPI-приложение для просмотра той же SQLite-базы,
которую используют CLI и builder. Текущий v1 слой ничего не запускает и не
меняет состояние релизов.
"""

from __future__ import annotations

from contextlib import closing
from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from simple_deploy.dto.state import (
    ExternalRequestDto,
    JobDto,
    ReleaseDto,
    StateSnapshotDto,
    dto_dump,
)
from simple_deploy.models.state import (
    BuildAttemptReadModel,
    ContourStateReadModel,
    DeploymentAttemptReadModel,
    ExternalRequestReadModel,
    JobReadModel,
    ReleaseBundleReadModel,
    ReleaseReadModel,
    ReleaseReferenceReadModel,
    StateSnapshotReadModel,
)
from simple_deploy.release.state import (
    all_contour_states,
    connect_state_db,
    list_build_attempts,
    list_deployment_attempts,
    list_external_requests,
    list_jobs,
    list_releases,
)


app = FastAPI(title="simple-deploy", version="0.1.0")


def bounded_limit(limit: int) -> int:
    """Ограничивает пользовательский ``limit`` безопасным диапазоном."""
    return max(1, min(limit, 200))


def release_sort_key(release: ReleaseReadModel) -> tuple[str, str]:
    """Возвращает ключ сортировки ресурса релиза для API."""
    timestamps = [attempt.finished_at for attempt in release.build_attempts]
    timestamps.extend(attempt.finished_at for attempt in release.deployment_attempts)
    timestamps.extend(request.updated_at for request in release.external_requests)
    if release.bundle is not None:
        timestamps.append(release.bundle.created_at)
    return (max(timestamps, default=""), release.build_version)


def release_read_models(
    bundles: list[ReleaseBundleReadModel],
    build_attempts: list[BuildAttemptReadModel],
    deployment_attempts: list[DeploymentAttemptReadModel],
    external_requests: list[ExternalRequestReadModel],
    *,
    limit: int,
) -> list[ReleaseReadModel]:
    """Собирает ресурсные модели чтения релизов поверх строк состояния."""
    records: dict[str, dict] = {}

    def ensure(build_version: str) -> dict:
        return records.setdefault(
            build_version,
            {
                "bundle": None,
                "build_attempts": [],
                "deployment_attempts": [],
                "external_requests": [],
            },
        )

    for bundle in bundles:
        ensure(bundle.build_version)["bundle"] = bundle
    for attempt in build_attempts:
        ensure(attempt.build_version)["build_attempts"].append(attempt)
    for attempt in deployment_attempts:
        ensure(attempt.build_version)["deployment_attempts"].append(attempt)
    for request in external_requests:
        ensure(request.build_version)["external_requests"].append(request)

    releases = []
    for build_version, record in records.items():
        bundle = record["bundle"]
        attempts = sorted(record["build_attempts"], key=lambda attempt: attempt.id, reverse=True)
        latest_attempt = attempts[0] if attempts else None
        if bundle is not None:
            build_status = "success"
            backend_commit = bundle.backend_commit
            frontend_commit = bundle.frontend_commit
        elif latest_attempt is not None:
            build_status = latest_attempt.status
            backend_commit = latest_attempt.backend_commit
            frontend_commit = latest_attempt.frontend_commit
        else:
            build_status = None
            backend_commit = None
            frontend_commit = None
        releases.append(
            ReleaseReadModel(
                build_version=build_version,
                build_status=build_status,
                backend_commit=backend_commit,
                frontend_commit=frontend_commit,
                bundle=bundle,
                build_attempts=attempts,
                deployment_attempts=sorted(
                    record["deployment_attempts"],
                    key=lambda attempt: attempt.id,
                    reverse=True,
                ),
                external_requests=sorted(
                    record["external_requests"],
                    key=lambda request: request.id,
                    reverse=True,
                ),
            )
        )

    return sorted(releases, key=release_sort_key, reverse=True)[:limit]


def release_read_models_from_state(limit: int = 50) -> list[ReleaseReadModel]:
    """Читает базу состояния и возвращает ресурсные модели чтения релизов."""
    limit = bounded_limit(limit)
    with closing(connect_state_db()) as connection:
        bundles = [
            ReleaseBundleReadModel.model_validate(record)
            for record in list_releases(connection, limit=limit)
        ]
        build_attempts = [
            BuildAttemptReadModel.model_validate(record)
            for record in list_build_attempts(connection, limit=limit)
        ]
        deployment_attempts = [
            DeploymentAttemptReadModel.model_validate(record)
            for record in list_deployment_attempts(connection, limit=limit)
        ]
        external_requests = [
            ExternalRequestReadModel.model_validate(request)
            for request in list_external_requests(connection, limit=limit)
        ]

    return release_read_models(
        bundles,
        build_attempts,
        deployment_attempts,
        external_requests,
        limit=limit,
    )


def release_reference_read_model(release: ReleaseReadModel) -> ReleaseReferenceReadModel:
    """Строит компактную ссылку на ресурс релиза для вложенных проекций."""
    return ReleaseReferenceReadModel(
        build_version=release.build_version,
        build_status=release.build_status,
        backend_commit=release.backend_commit,
        frontend_commit=release.frontend_commit,
    )


def contour_state_read_models(
    contour_states: dict,
    releases: list[ReleaseReadModel],
) -> dict[str, ContourStateReadModel | None]:
    """Обогащает состояния контуров ссылками на ресурсы релизов."""
    release_refs = {
        release.build_version: release_reference_read_model(release)
        for release in releases
    }
    contours: dict[str, ContourStateReadModel | None] = {}
    for contour, state in contour_states.items():
        if state is None:
            contours[contour] = None
            continue
        model = ContourStateReadModel.model_validate(state)
        release_ref = release_refs.get(model.last_success_release)
        if release_ref is None:
            release_ref = ReleaseReferenceReadModel(
                build_version=model.last_success_release,
                build_status="success",
                backend_commit=model.last_success_backend_commit,
            )
        contours[contour] = model.model_copy(
            update={"last_success_release_ref": release_ref}
        )
    return contours


def state_snapshot_read_model(limit: int = 50) -> StateSnapshotReadModel:
    """Собирает внутреннюю модель чтения локального состояния релизов."""
    limit = bounded_limit(limit)
    with closing(connect_state_db()) as connection:
        contour_states = all_contour_states(connection)
        bundles = [
            ReleaseBundleReadModel.model_validate(record)
            for record in list_releases(connection, limit=limit)
        ]
        build_attempts = [
            BuildAttemptReadModel.model_validate(record)
            for record in list_build_attempts(connection, limit=limit)
        ]
        deployment_attempts = [
            DeploymentAttemptReadModel.model_validate(record)
            for record in list_deployment_attempts(connection, limit=limit)
        ]
        external_requests = [
            ExternalRequestReadModel.model_validate(request)
            for request in list_external_requests(connection, limit=limit)
        ]
        releases = release_read_models(
            bundles,
            build_attempts,
            deployment_attempts,
            external_requests,
            limit=limit,
        )
        return StateSnapshotReadModel(
            contours=contour_state_read_models(contour_states, releases),
            releases=releases,
            build_attempts=build_attempts,
            deployment_attempts=deployment_attempts,
            jobs=[
                JobReadModel.model_validate(job)
                for job in list_jobs(connection, limit=limit)
            ],
            external_requests=external_requests,
        )


def state_snapshot_model(limit: int = 50) -> StateSnapshotReadModel:
    """Возвращает внутреннюю модель чтения снимка состояния для старых импортов."""
    return state_snapshot_read_model(limit=limit)


def state_snapshot_dto(limit: int = 50) -> StateSnapshotDto:
    """Преобразует внутренний снимок состояния во внешний DTO."""

    return StateSnapshotDto.model_validate(state_snapshot_read_model(limit=limit))


def state_snapshot(limit: int = 50) -> dict:
    """Возвращает JSON-совместимый словарь снимка состояния."""
    return dto_dump(state_snapshot_dto(limit=limit))


@app.get("/api/health")
def health() -> dict:
    """Возвращает статус самого web/API процесса."""
    return {"status": "ok"}


@app.get("/api/state", response_model=StateSnapshotDto)
def api_state(limit: int = 50) -> StateSnapshotDto:
    """Возвращает агрегированный JSON-снимок состояния релизов."""
    return state_snapshot_dto(limit=limit)


@app.get("/api/releases", response_model=list[ReleaseDto])
def api_releases(limit: int = 50) -> list[ReleaseDto]:
    """Возвращает ресурсные представления релизов."""
    return [
        ReleaseDto.model_validate(release)
        for release in release_read_models_from_state(limit=limit)
    ]


@app.get("/api/jobs", response_model=list[JobDto])
def api_jobs(limit: int = 50) -> list[JobDto]:
    """Возвращает последние локальные задания из SQLite."""
    with closing(connect_state_db()) as connection:
        return [
            JobDto.model_validate(JobReadModel.model_validate(job))
            for job in list_jobs(connection, limit=bounded_limit(limit))
        ]


@app.get("/api/requests", response_model=list[ExternalRequestDto])
def api_requests(limit: int = 50) -> list[ExternalRequestDto]:
    """Возвращает последние внешние заявки TEST/PROD."""
    with closing(connect_state_db()) as connection:
        return [
            ExternalRequestDto.model_validate(ExternalRequestReadModel.model_validate(request))
            for request in list_external_requests(connection, limit=bounded_limit(limit))
        ]


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Возвращает HTML-панель для локального оператора."""
    return render_dashboard(state_snapshot(limit=20))


def render_dashboard(snapshot: dict) -> str:
    """Рендерит полный HTML-документ панели из готового снимка."""
    release_columns = ["build_version", "build_status", "backend_commit", "frontend_commit"]
    build_attempt_columns = ["id", "build_version", "status", "started_at", "finished_at", "error"]
    deployment_attempt_columns = ["id", "contour", "build_version", "status", "started_at", "finished_at", "error"]
    job_columns = [
        "id",
        "kind",
        "contour",
        "build_version",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "error",
    ]
    external_request_columns = [
        "id",
        "contour",
        "build_version",
        "request_type",
        "status",
        "external_id",
        "updated_at",
        "error",
    ]
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>simple-deploy</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --fg: #17202a;
      --muted: #657282;
      --line: #d8dde5;
      --surface: #ffffff;
      --accent: #0f766e;
      --danger: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font: 14px/1.45 Arial, sans-serif;
    }}
    header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      padding: 20px 28px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }}
    h1, h2 {{ margin: 0; font-weight: 700; letter-spacing: 0; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 16px; }}
    main {{
      display: grid;
      gap: 18px;
      padding: 22px 28px 32px;
    }}
    section {{
      min-width: 0;
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
    }}
    .pill {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 9px;
      background: #fff;
    }}
    .table-wrap {{
      margin-top: 8px;
      overflow: auto;
      border: 1px solid var(--line);
      background: var(--surface);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      background: #fbfcfd;
    }}
    td.error {{
      color: var(--danger);
      white-space: normal;
      min-width: 220px;
    }}
    .empty {{
      margin: 8px 0 0;
      color: var(--muted);
    }}
    a {{ color: var(--accent); }}
    @media (max-width: 760px) {{
      header {{ align-items: start; flex-direction: column; padding: 16px; }}
      main {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>simple-deploy</h1>
      <div class="meta">
        <span class="pill">только чтение v1</span>
        <a href="/api/state">/api/state</a>
      </div>
    </div>
  </header>
  <main>
    {render_contours(snapshot["contours"])}
    {render_table("Releases", snapshot["releases"], release_columns)}
    {render_table("Build attempts", snapshot["build_attempts"], build_attempt_columns)}
    {render_table("Deploy attempts", snapshot["deployment_attempts"], deployment_attempt_columns)}
    {render_table("Jobs", snapshot["jobs"], job_columns)}
    {render_table("External requests", snapshot["external_requests"], external_request_columns)}
  </main>
</body>
</html>"""


def render_contours(contours: dict) -> str:
    """Рендерит таблицу состояний контуров."""
    rows = []
    for contour, state in contours.items():
        release_ref = state.get("last_success_release_ref") if state else None
        rows.append(
            {
                "contour": contour,
                "last_success_release": (
                    release_ref["build_version"] if release_ref else state["last_success_release"]
                )
                if state
                else "",
                "last_success_build_status": release_ref.get("build_status", "") if release_ref else "",
                "last_success_backend_commit": (
                    release_ref["backend_commit"]
                    if release_ref
                    else state["last_success_backend_commit"]
                )
                if state
                else "",
                "updated_at": state["updated_at"] if state else "",
            }
        )
    return render_table(
        "Contours",
        rows,
        [
            "contour",
            "last_success_release",
            "last_success_build_status",
            "last_success_backend_commit",
            "updated_at",
        ],
    )


def render_table(title: str, rows: list[dict], columns: list[str]) -> str:
    """Рендерит одну HTML-таблицу панели."""
    if not rows:
        return f"<section><h2>{escape(title)}</h2><p class=\"empty\">No records</p></section>"
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = "" if row.get(column) is None else str(row.get(column, ""))
            css_class = " class=\"error\"" if column == "error" and value else ""
            cells.append(f"<td{css_class}>{escape(value)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<section><h2>{escape(title)}</h2><div class=\"table-wrap\">"
        f"<table><thead><tr>{head}</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
    )
