"""
Web/API поверхность над локальным registry state.

Модуль предоставляет FastAPI-приложение и HTML dashboard для просмотра той же
SQLite-базы, которую используют CLI и builder. Read projections собираются в
``simple_deploy.registry.queries``; здесь остаются HTTP routes, DTO conversion
и HTML rendering. Write endpoints создают local job resource, но не выполняют
долгие build/deploy операции внутри HTTP-запроса.
"""

from __future__ import annotations

import asyncio
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from simple_deploy.dto.state import (
    dto_dump,
    ExternalRequestDto,
    JobDto,
    ReleaseDto,
    StateSnapshotDto,
)
from simple_deploy.jobs.runner import REQUEST_MODELS, create_job_for_request
from simple_deploy.models.state import StateSnapshotReadModel
from simple_deploy.registry.commands import (
    cancel_local_job,
    requeue_local_job,
)
from simple_deploy.registry import queries as _registry_queries
from simple_deploy.types.job import JobKindEnum
from simple_deploy.types.status import JobStatusEnum

_external_request_read_models_from_state = (
    _registry_queries.external_request_read_models_from_state
)
_job_read_models_from_state = _registry_queries.job_read_models_from_state
_job_read_model_from_state = _registry_queries.job_read_model_from_state
_release_read_models_from_state = (
    _registry_queries.release_read_models_from_state
)
_state_snapshot_read_model = _registry_queries.state_snapshot_read_model

app = FastAPI(title="simple-deploy", version="0.1.0")
WEB_UI_DIST = Path(__file__).resolve().parents[2] / "web-ui" / "dist"
WEB_UI_INDEX = WEB_UI_DIST / "index.html"
TERMINAL_JOB_STATUSES = {"success", "failed", "cancelled"}

app.mount(
    "/assets",
    StaticFiles(directory=WEB_UI_DIST / "assets", check_dir=False),
    name="web-ui-assets",
)


class JobCreateRequest(BaseModel):
    """HTTP payload создания queued local job."""

    model_config = ConfigDict(extra="forbid")

    kind: JobKindEnum
    payload: dict[str, object] = Field(default_factory=dict)


class JobUpdateRequest(BaseModel):
    """HTTP payload изменения lifecycle state local job."""

    model_config = ConfigDict(extra="forbid")

    status: JobStatusEnum


def state_snapshot_model(limit: int = 50) -> StateSnapshotReadModel:
    """
    Возвращает внутреннюю модель чтения снимка состояния для старых импортов.
    """
    return _state_snapshot_read_model(limit=limit)


def state_snapshot_dto(limit: int = 50) -> StateSnapshotDto:
    """Преобразует внутренний снимок состояния во внешний DTO."""
    return StateSnapshotDto.model_validate(
        _state_snapshot_read_model(limit=limit)
    )


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
        for release in _release_read_models_from_state(limit=limit)
    ]


@app.get("/api/jobs", response_model=list[JobDto])
def api_jobs(limit: int = 50) -> list[JobDto]:
    """Возвращает последние локальные задания из SQLite."""
    return [
        JobDto.model_validate(job)
        for job in _job_read_models_from_state(limit=limit)
    ]


@app.get("/api/jobs/{job_id}", response_model=JobDto)
def api_job(job_id: int) -> JobDto:
    """Возвращает одну local job по id."""
    job = _job_read_model_from_state(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Local job not found: id={job_id}"
        )
    return JobDto.model_validate(job)


@app.post("/api/jobs", response_model=JobDto, status_code=201)
def api_create_job(request: JobCreateRequest) -> JobDto:
    """Создает queued local job из HTTP payload без выполнения use case."""
    request_model = REQUEST_MODELS[request.kind]
    application_request = request_model.model_validate(request.payload)
    job = create_job_for_request(application_request)
    return JobDto.model_validate(job)


@app.patch("/api/jobs/{job_id}", response_model=JobDto)
def api_update_job(job_id: int, request: JobUpdateRequest) -> JobDto:
    """Изменяет lifecycle status local job допустимым transition-ом."""
    try:
        if request.status == JobStatusEnum.CANCELLED:
            result = cancel_local_job(job_id)
        elif request.status == JobStatusEnum.QUEUED:
            result = requeue_local_job(job_id)
        else:
            raise ValueError(
                "Unsupported local job status transition target: "
                f"{request.status.value}"
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobDto.model_validate(result.job)


def _tail_text_file(path: str, offset: int) -> tuple[str, int]:
    """Reads new UTF-8 text from a log file starting at byte offset."""
    if not path:
        return "", offset
    log_path = Path(path)
    if not log_path.exists() or not log_path.is_file():
        return "", offset
    with log_path.open("rb") as log_file:
        log_file.seek(offset)
        data = log_file.read()
        next_offset = log_file.tell()
    return data.decode("utf-8", errors="replace"), next_offset


@app.websocket("/ws/jobs/{job_id}")
async def ws_job_logs(
    websocket: WebSocket,
    job_id: int,
    poll_interval: float = 0.5,
) -> None:
    """Streams job status and log file deltas over WebSocket."""
    await websocket.accept()
    job = _registry_queries.job_read_model_from_state(job_id)
    if job is None:
        await websocket.send_json(
            {"type": "error", "message": f"job not found: {job_id}"}
        )
        await websocket.close()
        return

    await websocket.send_json(
        {
            "type": "snapshot",
            "job": dto_dump(JobDto.model_validate(job)),
        }
    )
    offset = 0
    last_status = job.status.value
    interval = max(0.1, poll_interval)

    while True:
        job = _registry_queries.job_read_model_from_state(job_id)
        if job is None:
            await websocket.send_json(
                {"type": "error", "message": f"job not found: {job_id}"}
            )
            await websocket.close()
            return

        text, offset = _tail_text_file(job.log_path, offset)
        if text:
            await websocket.send_json(
                {"type": "log", "text": text, "offset": offset}
            )

        status = job.status.value
        if status != last_status:
            await websocket.send_json({"type": "status", "status": status})
            last_status = status

        if status in TERMINAL_JOB_STATUSES:
            await websocket.send_json({"type": "done", "status": status})
            await websocket.close()
            return

        await asyncio.sleep(interval)


@app.get("/api/requests", response_model=list[ExternalRequestDto])
def api_requests(limit: int = 50) -> list[ExternalRequestDto]:
    """Возвращает последние внешние заявки TEST/PROD."""
    return [
        ExternalRequestDto.model_validate(request)
        for request in _external_request_read_models_from_state(limit=limit)
    ]


@app.get("/", response_class=HTMLResponse, response_model=None)
def dashboard() -> Response:
    """Возвращает React-панель для локального оператора."""
    if WEB_UI_INDEX.is_file():
        return FileResponse(WEB_UI_INDEX)
    return HTMLResponse(render_dashboard(state_snapshot(limit=20)))


@app.get("/jobs/{job_id}", response_class=HTMLResponse, response_model=None)
def job_log_page(job_id: int) -> Response:
    """Возвращает React-страницу live log одной local job."""
    job = _job_read_model_from_state(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail=f"Local job not found: id={job_id}"
        )
    if WEB_UI_INDEX.is_file():
        return FileResponse(WEB_UI_INDEX)
    return HTMLResponse(
        render_job_log_page(dto_dump(JobDto.model_validate(job)))
    )


def render_dashboard(snapshot: dict) -> str:
    """Рендерит полный HTML-документ панели из готового снимка."""
    release_columns = [
        "build_version",
        "build_status",
        "backend_commit",
        "frontend_commit",
    ]
    build_attempt_columns = [
        "id",
        "build_version",
        "status",
        "started_at",
        "finished_at",
        "error",
    ]
    deployment_attempt_columns = [
        "id",
        "contour",
        "build_version",
        "status",
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
    build_attempts_html = render_table(
        "Build attempts",
        snapshot["build_attempts"],
        build_attempt_columns,
    )
    deploy_attempts_html = render_table(
        "Deploy attempts",
        snapshot["deployment_attempts"],
        deployment_attempt_columns,
    )
    external_requests_html = render_table(
        "External requests",
        snapshot["external_requests"],
        external_request_columns,
    )
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
    .actions {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    button, .button-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 28px;
      padding: 4px 9px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: #fff;
      color: var(--fg);
      font: inherit;
      text-decoration: none;
      cursor: pointer;
    }}
    button.danger {{
      border-color: #f3b4ad;
      color: var(--danger);
    }}
    button:disabled {{
      color: var(--muted);
      cursor: default;
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
        <span class="pill">registry v1</span>
        <a href="/api/state">/api/state</a>
      </div>
    </div>
  </header>
  <main>
    {render_contours(snapshot["contours"])}
    {render_table("Releases", snapshot["releases"], release_columns)}
    {build_attempts_html}
    {deploy_attempts_html}
    {render_jobs_table(snapshot["jobs"])}
    {external_requests_html}
  </main>
  <script>
    async function updateJobStatus(jobId, status) {{
      const response = await fetch(`/api/jobs/${{jobId}}`, {{
        method: "PATCH",
        headers: {{"content-type": "application/json"}},
        body: JSON.stringify({{status}})
      }});
      if (response.ok) {{
        window.location.reload();
        return;
      }}
      const text = await response.text();
      window.alert(text || `Job update failed: ${{response.status}}`);
    }}
    document.addEventListener("click", (event) => {{
      const button = event.target.closest("[data-job-status]");
      if (!button) {{
        return;
      }}
      updateJobStatus(button.dataset.jobId, button.dataset.jobStatus);
    }});
  </script>
</body>
</html>"""


def render_job_log_page(job: dict) -> str:
    """Рендерит HTML-страницу live log одной local job."""
    job_id = int(job["id"])
    title = f"Job {job_id}"
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} - simple-deploy</title>
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
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0; }}
    main {{ display: grid; gap: 16px; padding: 22px 28px 32px; }}
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
    pre {{
      min-height: 420px;
      margin: 0;
      padding: 14px;
      overflow: auto;
      border: 1px solid var(--line);
      background: #101820;
      color: #e8edf2;
      white-space: pre-wrap;
      font: 13px/1.45 Consolas, "Courier New", monospace;
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
      <h1>{escape(title)}</h1>
      <div class="meta">
        <span class="pill" id="status">{escape(str(job["status"]))}</span>
        <span>{escape(str(job["kind"]))}</span>
        <a href="/">Dashboard</a>
        <a href="/api/jobs/{job_id}">/api/jobs/{job_id}</a>
      </div>
    </div>
  </header>
  <main>
    <pre id="log"></pre>
  </main>
  <script>
    const log = document.getElementById("log");
    const status = document.getElementById("status");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(
      `${{protocol}}//${{window.location.host}}/ws/jobs/{job_id}`
    );
    socket.addEventListener("message", (event) => {{
      const message = JSON.parse(event.data);
      if (message.type === "snapshot" && message.job) {{
        status.textContent = message.job.status;
      }}
      if (message.type === "status" || message.type === "done") {{
        status.textContent = message.status;
      }}
      if (message.type === "log") {{
        log.textContent += message.text;
        log.scrollTop = log.scrollHeight;
      }}
      if (message.type === "error") {{
        log.textContent += message.message + "\\n";
      }}
    }});
  </script>
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
                    release_ref["build_version"]
                    if release_ref
                    else state["last_success_release"]
                )
                if state
                else "",
                "last_success_build_status": release_ref.get(
                    "build_status", ""
                )
                if release_ref
                else "",
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


def render_job_actions(row: dict) -> str:
    """Рендерит REST lifecycle actions для одной job."""
    job_id = int(row["id"])
    status = str(row.get("status", ""))
    actions = [
        f'<a class="button-link" href="/jobs/{job_id}">Log</a>',
    ]
    if status == "queued":
        actions.append(
            '<button class="danger" type="button" '
            f'data-job-id="{job_id}" data-job-status="cancelled">'
            "Cancel</button>"
        )
    if status in {"failed", "cancelled"}:
        actions.append(
            '<button type="button" '
            f'data-job-id="{job_id}" data-job-status="queued">'
            "Requeue</button>"
        )
    return '<div class="actions">' + "".join(actions) + "</div>"


def render_jobs_table(rows: list[dict]) -> str:
    """Рендерит таблицу jobs с operator actions."""
    columns = [
        "id",
        "kind",
        "contour",
        "build_version",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "error",
        "actions",
    ]
    if not rows:
        return """<section><h2>Jobs</h2><p class="empty">No records</p></section>"""
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            if column == "actions":
                cells.append(f"<td>{render_job_actions(row)}</td>")
                continue
            value = "" if row.get(column) is None else str(row.get(column, ""))
            css_class = ' class="error"' if column == "error" and value else ""
            cells.append(f"<td{css_class}>{escape(value)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<section><h2>Jobs</h2><div class="table-wrap">'
        f"<table><thead><tr>{head}</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
    )


def render_table(title: str, rows: list[dict], columns: list[str]) -> str:
    """Рендерит одну HTML-таблицу панели."""
    if not rows:
        return (
            f"<section><h2>{escape(title)}</h2>"
            """<p class="empty">No records</p></section>"""
        )
    head = "".join(f"<th>{escape(column)}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cells = []
        for column in columns:
            value = "" if row.get(column) is None else str(row.get(column, ""))
            css_class = ' class="error"' if column == "error" and value else ""
            cells.append(f"<td{css_class}>{escape(value)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f'<section><h2>{escape(title)}</h2><div class="table-wrap">'
        f"<table><thead><tr>{head}</tr></thead><tbody>"
        + "".join(body_rows)
        + "</tbody></table></div></section>"
    )
