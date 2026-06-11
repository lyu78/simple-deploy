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
    ReleaseRecordDto,
    StateSnapshotDto,
    dto_dump,
)
from simple_deploy.models.state import (
    BuildAttemptModel,
    ContourStateModel,
    DeploymentAttemptModel,
    ExternalRequestModel,
    JobModel,
    ReleaseRecordModel,
    StateSnapshotModel,
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


def state_snapshot_model(limit: int = 50) -> StateSnapshotModel:
    """Собирает внутреннюю модель чтения локального состояния релизов."""
    limit = bounded_limit(limit)
    with closing(connect_state_db()) as connection:
        contour_states = all_contour_states(connection)
        return StateSnapshotModel(
            contours={
                contour: ContourStateModel.model_validate(state) if state is not None else None
                for contour, state in contour_states.items()
            },
            releases=[
                ReleaseRecordModel.model_validate(record)
                for record in list_releases(connection, limit=limit)
            ],
            build_attempts=[
                BuildAttemptModel.model_validate(record)
                for record in list_build_attempts(connection, limit=limit)
            ],
            deployment_attempts=[
                DeploymentAttemptModel.model_validate(record)
                for record in list_deployment_attempts(connection, limit=limit)
            ],
            jobs=[
                JobModel.model_validate(job)
                for job in list_jobs(connection, limit=limit)
            ],
            external_requests=[
                ExternalRequestModel.model_validate(request)
                for request in list_external_requests(connection, limit=limit)
            ],
        )


def state_snapshot_dto(limit: int = 50) -> StateSnapshotDto:
    """Преобразует внутренний снимок состояния во внешний DTO."""

    return StateSnapshotDto.model_validate(state_snapshot_model(limit=limit))


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


@app.get("/api/releases", response_model=list[ReleaseRecordDto])
def api_releases(limit: int = 50) -> list[ReleaseRecordDto]:
    """Возвращает последние успешно собранные релизы из SQLite."""
    with closing(connect_state_db()) as connection:
        return [
            ReleaseRecordDto.model_validate(ReleaseRecordModel.model_validate(record))
            for record in list_releases(connection, limit=bounded_limit(limit))
        ]


@app.get("/api/jobs", response_model=list[JobDto])
def api_jobs(limit: int = 50) -> list[JobDto]:
    """Возвращает последние локальные задания из SQLite."""
    with closing(connect_state_db()) as connection:
        return [
            JobDto.model_validate(JobModel.model_validate(job))
            for job in list_jobs(connection, limit=bounded_limit(limit))
        ]


@app.get("/api/requests", response_model=list[ExternalRequestDto])
def api_requests(limit: int = 50) -> list[ExternalRequestDto]:
    """Возвращает последние внешние заявки TEST/PROD."""
    with closing(connect_state_db()) as connection:
        return [
            ExternalRequestDto.model_validate(ExternalRequestModel.model_validate(request))
            for request in list_external_requests(connection, limit=bounded_limit(limit))
        ]


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Возвращает HTML-панель для локального оператора."""
    return render_dashboard(state_snapshot(limit=20))


def render_dashboard(snapshot: dict) -> str:
    """Рендерит полный HTML-документ панели из готового снимка."""
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
        <span class="pill">read-only v1</span>
        <a href="/api/state">/api/state</a>
      </div>
    </div>
  </header>
  <main>
    {render_contours(snapshot["contours"])}
    {render_table("Releases", snapshot["releases"], ["build_version", "backend_commit", "frontend_commit", "created_at"])}
    {render_table("Build attempts", snapshot["build_attempts"], ["id", "build_version", "status", "started_at", "finished_at", "error"])}
    {render_table("Deploy attempts", snapshot["deployment_attempts"], ["id", "contour", "build_version", "status", "started_at", "finished_at", "error"])}
    {render_table("Jobs", snapshot["jobs"], ["id", "kind", "contour", "build_version", "status", "created_at", "started_at", "finished_at", "error"])}
    {render_table("External requests", snapshot["external_requests"], ["id", "contour", "build_version", "request_type", "status", "external_id", "updated_at", "error"])}
  </main>
</body>
</html>"""


def render_contours(contours: dict) -> str:
    """Рендерит таблицу состояний контуров."""
    rows = []
    for contour, state in contours.items():
        rows.append(
            {
                "contour": contour,
                "last_success_release": state["last_success_release"] if state else "",
                "last_success_backend_commit": state["last_success_backend_commit"] if state else "",
                "updated_at": state["updated_at"] if state else "",
            }
        )
    return render_table(
        "Contours",
        rows,
        ["contour", "last_success_release", "last_success_backend_commit", "updated_at"],
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
