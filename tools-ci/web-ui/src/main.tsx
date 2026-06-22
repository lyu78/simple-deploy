import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  Ban,
  FileText,
  Play,
  Plus,
  RefreshCw,
  RotateCcw
} from "lucide-react";
import "./styles.css";

type JobKind =
  | "dry_run"
  | "build"
  | "deploy"
  | "pipeline"
  | "set_baseline"
  | "mark_applied"
  | "mark_failed";

type JobStatus = "queued" | "running" | "success" | "failed" | "cancelled";
type Contour = "dev" | "test" | "prod";

type ContourState = {
  contour: Contour;
  last_success_release: string;
  last_success_backend_commit: string;
  updated_at: string;
  last_success_release_ref?: {
    build_version: string;
    build_status: string;
    backend_commit: string;
    frontend_commit: string;
  } | null;
};

type Release = {
  build_version: string;
  build_status: string;
  backend_commit: string;
  frontend_commit: string;
};

type Attempt = {
  id: number;
  contour?: string;
  build_version: string;
  status: string;
  started_at: string;
  finished_at: string;
  error: string;
};

type Job = {
  id: number;
  kind: JobKind;
  contour: string;
  build_version: string;
  status: JobStatus;
  payload_json: string;
  log_path: string;
  error: string;
  created_at: string;
  started_at: string;
  finished_at: string;
};

type ExternalRequest = {
  id: number;
  contour: Contour;
  build_version: string;
  request_type: string;
  status: string;
  external_id: string;
  updated_at: string;
  error: string;
};

type StateSnapshot = {
  contours: Record<string, ContourState | null>;
  releases: Release[];
  build_attempts: Attempt[];
  deployment_attempts: Attempt[];
  jobs: Job[];
  external_requests: ExternalRequest[];
};

type JobFormState = {
  kind: JobKind;
  contour: Contour;
  buildVersion: string;
  backendCommit: string;
  error: string;
  timeout: string;
  latest: boolean;
  includeSetDefaultSql: boolean;
  skipDataSqlArtifacts: boolean;
  appOnly: boolean;
};

const jobKindLabels: Record<JobKind, string> = {
  dry_run: "Dry-run",
  build: "Build",
  deploy: "Deploy",
  pipeline: "Pipeline",
  set_baseline: "Set baseline",
  mark_applied: "Mark applied",
  mark_failed: "Mark failed"
};

const defaultForm: JobFormState = {
  kind: "deploy",
  contour: "dev",
  buildVersion: "",
  backendCommit: "",
  error: "",
  timeout: "3600",
  latest: true,
  includeSetDefaultSql: false,
  skipDataSqlArtifacts: false,
  appOnly: false
};

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function jobPayload(form: JobFormState): Record<string, unknown> {
  const timeout = Number.parseInt(form.timeout, 10) || 3600;
  if (form.kind === "dry_run") {
    return {
      skip_data_sql_artifacts: form.skipDataSqlArtifacts,
      app_only: form.appOnly
    };
  }
  if (form.kind === "build") {
    return {
      timeout,
      skip_data_sql_artifacts: form.skipDataSqlArtifacts
    };
  }
  if (form.kind === "deploy") {
    return {
      contour: form.contour,
      build_version: form.latest ? "" : form.buildVersion.trim(),
      latest: form.latest,
      include_set_default_sql: form.includeSetDefaultSql,
      app_only: form.appOnly
    };
  }
  if (form.kind === "pipeline") {
    return {
      timeout,
      contour: form.contour,
      include_set_default_sql: form.includeSetDefaultSql,
      skip_data_sql_artifacts: form.skipDataSqlArtifacts,
      app_only: form.appOnly
    };
  }
  if (form.kind === "set_baseline") {
    return {
      contour: form.contour,
      build_version: form.buildVersion.trim(),
      backend_commit: form.backendCommit.trim()
    };
  }
  if (form.kind === "mark_applied") {
    return {
      contour: form.contour,
      build_version: form.buildVersion.trim()
    };
  }
  return {
    contour: form.contour,
    build_version: form.buildVersion.trim(),
    error: form.error.trim()
  };
}

function useStateSnapshot() {
  const [snapshot, setSnapshot] = React.useState<StateSnapshot | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSnapshot(await apiJson<StateSnapshot>("/api/state"));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  return { snapshot, error, loading, load };
}

function App() {
  const jobMatch = window.location.pathname.match(/^\/jobs\/(\d+)$/);
  if (jobMatch) {
    return <JobLogPage jobId={Number(jobMatch[1])} />;
  }
  return <Dashboard />;
}

function Dashboard() {
  const { snapshot, error, loading, load } = useStateSnapshot();
  const [form, setForm] = React.useState<JobFormState>(defaultForm);
  const [submitError, setSubmitError] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  async function createJob(event: React.FormEvent) {
    event.preventDefault();
    setSubmitError("");
    setSubmitting(true);
    try {
      await apiJson<Job>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          kind: form.kind,
          payload: jobPayload(form)
        })
      });
      setForm((current) => ({ ...current, buildVersion: "", error: "" }));
      await load();
    } catch (exc) {
      setSubmitError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSubmitting(false);
    }
  }

  async function updateJob(jobId: number, status: "cancelled" | "queued") {
    await apiJson<Job>(`/api/jobs/${jobId}`, {
      method: "PATCH",
      body: JSON.stringify({ status })
    });
    await load();
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>simple-deploy</h1>
          <p>Release registry, local jobs and deploy operations</p>
        </div>
        <button className="icon-button" type="button" onClick={() => void load()} title="Refresh">
          <RefreshCw size={18} />
        </button>
      </header>

      {error ? <div className="alert">{error}</div> : null}
      {loading && !snapshot ? <div className="loading">Loading registry state...</div> : null}

      {snapshot ? (
        <main className="workspace">
          <section className="band">
            <SectionHeader title="Create local job" icon={<Plus size={18} />} />
            <JobCreateForm
              form={form}
              setForm={setForm}
              onSubmit={createJob}
              submitting={submitting}
              error={submitError}
            />
          </section>
          <section className="band">
            <SectionHeader title="Contours" icon={<Activity size={18} />} />
            <ContourGrid contours={snapshot.contours} />
          </section>
          <section className="band">
            <SectionHeader title="Jobs" icon={<Play size={18} />} />
            <JobsTable jobs={snapshot.jobs} onUpdate={updateJob} />
          </section>
          <DataTables snapshot={snapshot} />
        </main>
      ) : null}
    </div>
  );
}

function SectionHeader({ title, icon }: { title: string; icon: React.ReactNode }) {
  return (
    <div className="section-header">
      <span>{icon}</span>
      <h2>{title}</h2>
    </div>
  );
}

function JobCreateForm({
  form,
  setForm,
  onSubmit,
  submitting,
  error
}: {
  form: JobFormState;
  setForm: React.Dispatch<React.SetStateAction<JobFormState>>;
  onSubmit: (event: React.FormEvent) => void;
  submitting: boolean;
  error: string;
}) {
  const needsContour = ["deploy", "pipeline", "set_baseline", "mark_applied", "mark_failed"].includes(form.kind);
  const needsBuildVersion = ["deploy", "set_baseline", "mark_applied", "mark_failed"].includes(form.kind) && !(form.kind === "deploy" && form.latest);
  const needsTimeout = ["build", "pipeline"].includes(form.kind);

  return (
    <form className="job-form" onSubmit={onSubmit}>
      <label>
        Kind
        <select value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.target.value as JobKind }))}>
          {(Object.keys(jobKindLabels) as JobKind[]).map((kind) => (
            <option value={kind} key={kind}>
              {jobKindLabels[kind]}
            </option>
          ))}
        </select>
      </label>
      {needsContour ? (
        <label>
          Contour
          <select value={form.contour} onChange={(event) => setForm((current) => ({ ...current, contour: event.target.value as Contour }))}>
            <option value="dev">dev</option>
            <option value="test">test</option>
            <option value="prod">prod</option>
          </select>
        </label>
      ) : null}
      {form.kind === "deploy" ? (
        <label className="check-row">
          <input type="checkbox" checked={form.latest} onChange={(event) => setForm((current) => ({ ...current, latest: event.target.checked }))} />
          Latest release
        </label>
      ) : null}
      {needsBuildVersion ? (
        <label>
          Build version
          <input value={form.buildVersion} onChange={(event) => setForm((current) => ({ ...current, buildVersion: event.target.value }))} />
        </label>
      ) : null}
      {form.kind === "set_baseline" ? (
        <label>
          Backend commit
          <input value={form.backendCommit} onChange={(event) => setForm((current) => ({ ...current, backendCommit: event.target.value }))} />
        </label>
      ) : null}
      {form.kind === "mark_failed" ? (
        <label className="wide-field">
          Error
          <input required value={form.error} onChange={(event) => setForm((current) => ({ ...current, error: event.target.value }))} />
        </label>
      ) : null}
      {needsTimeout ? (
        <label>
          Timeout seconds
          <input type="number" min="1" value={form.timeout} onChange={(event) => setForm((current) => ({ ...current, timeout: event.target.value }))} />
        </label>
      ) : null}
      <div className="check-group">
        {["deploy", "pipeline"].includes(form.kind) ? (
          <label className="check-row">
            <input type="checkbox" checked={form.includeSetDefaultSql} onChange={(event) => setForm((current) => ({ ...current, includeSetDefaultSql: event.target.checked }))} />
            Include set_default SQL
          </label>
        ) : null}
        {["dry_run", "build", "pipeline"].includes(form.kind) ? (
          <label className="check-row">
            <input type="checkbox" checked={form.skipDataSqlArtifacts} onChange={(event) => setForm((current) => ({ ...current, skipDataSqlArtifacts: event.target.checked }))} />
            Skip data SQL artifacts
          </label>
        ) : null}
        {["dry_run", "deploy", "pipeline"].includes(form.kind) ? (
          <label className="check-row">
            <input type="checkbox" checked={form.appOnly} onChange={(event) => setForm((current) => ({ ...current, appOnly: event.target.checked }))} />
            App only
          </label>
        ) : null}
      </div>
      <button className="primary-button" disabled={submitting} type="submit">
        <Plus size={17} />
        Queue job
      </button>
      {error ? <div className="form-error">{error}</div> : null}
    </form>
  );
}

function ContourGrid({ contours }: { contours: StateSnapshot["contours"] }) {
  return (
    <div className="contour-grid">
      {Object.entries(contours).map(([name, state]) => (
        <div className="metric-tile" key={name}>
          <span>{name}</span>
          <strong>{state?.last_success_release || "not set"}</strong>
          <small>{state?.last_success_backend_commit || "no baseline"}</small>
        </div>
      ))}
    </div>
  );
}

function JobsTable({ jobs, onUpdate }: { jobs: Job[]; onUpdate: (jobId: number, status: "cancelled" | "queued") => Promise<void> }) {
  if (!jobs.length) {
    return <p className="empty">No jobs</p>;
  }
  return (
    <Table
      columns={["id", "kind", "contour", "build_version", "status", "created_at", "started_at", "finished_at", "error", "actions"]}
      rows={jobs}
      renderCell={(job, column) => {
        if (column === "status") return <Status value={job.status} />;
        if (column === "actions") {
          return (
            <div className="row-actions">
              <a className="icon-link" href={`/jobs/${job.id}`} title="Open log">
                <FileText size={16} />
              </a>
              {job.status === "queued" ? (
                <button className="icon-button danger" type="button" title="Cancel" onClick={() => void onUpdate(job.id, "cancelled")}>
                  <Ban size={16} />
                </button>
              ) : null}
              {job.status === "failed" || job.status === "cancelled" ? (
                <button className="icon-button" type="button" title="Requeue" onClick={() => void onUpdate(job.id, "queued")}>
                  <RotateCcw size={16} />
                </button>
              ) : null}
            </div>
          );
        }
        return String(job[column as keyof Job] ?? "");
      }}
    />
  );
}

function DataTables({ snapshot }: { snapshot: StateSnapshot }) {
  return (
    <>
      <section className="band">
        <SectionHeader title="Releases" icon={<FileText size={18} />} />
        <Table columns={["build_version", "build_status", "backend_commit", "frontend_commit"]} rows={snapshot.releases} />
      </section>
      <section className="band">
        <SectionHeader title="Build attempts" icon={<Activity size={18} />} />
        <Table columns={["id", "build_version", "status", "started_at", "finished_at", "error"]} rows={snapshot.build_attempts} />
      </section>
      <section className="band">
        <SectionHeader title="Deploy attempts" icon={<Activity size={18} />} />
        <Table columns={["id", "contour", "build_version", "status", "started_at", "finished_at", "error"]} rows={snapshot.deployment_attempts} />
      </section>
      <section className="band">
        <SectionHeader title="External requests" icon={<FileText size={18} />} />
        <Table columns={["id", "contour", "build_version", "request_type", "status", "external_id", "updated_at", "error"]} rows={snapshot.external_requests} />
      </section>
    </>
  );
}

function Table<T extends Record<string, unknown>>({
  columns,
  rows,
  renderCell
}: {
  columns: string[];
  rows: T[];
  renderCell?: (row: T, column: string) => React.ReactNode;
}) {
  if (!rows.length) {
    return <p className="empty">No records</p>;
  }
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id ?? row.build_version ?? index)}>
              {columns.map((column) => (
                <td className={column === "error" && row[column] ? "error-cell" : ""} key={column}>
                  {renderCell ? renderCell(row, column) : String(row[column] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`}>{value}</span>;
}

function JobLogPage({ jobId }: { jobId: number }) {
  const [job, setJob] = React.useState<Job | null>(null);
  const [log, setLog] = React.useState("");
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let closed = false;
    apiJson<Job>(`/api/jobs/${jobId}`).then(setJob).catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)));
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/jobs/${jobId}`);
    socket.addEventListener("message", (event) => {
      if (closed) return;
      const message = JSON.parse(event.data) as { type: string; text?: string; status?: JobStatus; job?: Job; message?: string };
      if (message.type === "snapshot" && message.job) setJob(message.job);
      if ((message.type === "status" || message.type === "done") && message.status) setJob((current) => current ? { ...current, status: message.status as JobStatus } : current);
      if (message.type === "log" && message.text) setLog((current) => current + message.text);
      if (message.type === "error" && message.message) setError(message.message);
    });
    socket.addEventListener("error", () => setError("WebSocket connection failed"));
    return () => {
      closed = true;
      socket.close();
    };
  }, [jobId]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>Job {jobId}</h1>
          <p>{job ? `${jobKindLabels[job.kind]} / ${job.status}` : "Loading job log"}</p>
        </div>
        <a className="icon-link" href="/" title="Dashboard">
          <Activity size={18} />
        </a>
      </header>
      {error ? <div className="alert">{error}</div> : null}
      <main className="workspace">
        <section className="band">
          <SectionHeader title="Live log" icon={<FileText size={18} />} />
          <pre className="log-view">{log || "Waiting for log output..."}</pre>
        </section>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
