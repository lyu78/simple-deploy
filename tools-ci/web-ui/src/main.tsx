import React from "react";
import ReactDOM from "react-dom/client";
import {
  Activity,
  ArrowLeft,
  Ban,
  FileText,
  ListFilter,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Server
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

type BuildOption = {
  build_version: string;
  backend_commit: string;
  frontend_commit: string;
  created_at: string;
  build_status: string;
  source: string;
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

type WorkerHeartbeat = {
  worker_id: string;
  status: string;
  current_job_id: number | null;
  message: string;
  updated_at: string;
};

type WorkerHealth = {
  status: string;
  heartbeat: WorkerHeartbeat | null;
  queued_jobs: number;
  running_jobs: number;
  stale_after_seconds: number;
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
  error: string;
  timeout: string;
  latest: boolean;
  includeSetDefaultSql: boolean;
  skipDataSqlArtifacts: boolean;
  appOnly: boolean;
};

type JobStatusFilter = "all" | JobStatus;
type JobKindFilter = "all" | JobKind;
type PollStatus = "idle" | "polling" | "ok" | "failed";
type StreamStatus = "connecting" | "open" | "closed" | "failed";

type PollState = {
  status: PollStatus;
  label: string;
  lastOkAt: string;
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

function jobKindOptionLabel(kind: JobKind, contour: Contour): string {
  if (kind === "pipeline") {
    return `Pipeline [dry-run -> build -> deploy ${contour}]`;
  }
  return jobKindLabels[kind];
}

const defaultForm: JobFormState = {
  kind: "deploy",
  contour: "dev",
  buildVersion: "",
  error: "",
  timeout: "3600",
  latest: true,
  includeSetDefaultSql: false,
  skipDataSqlArtifacts: false,
  appOnly: false
};

const DASHBOARD_REFRESH_INTERVAL_MS = 3000;

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
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
      build_version: form.buildVersion.trim()
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

function useDashboardData() {
  const [snapshot, setSnapshot] = React.useState<StateSnapshot | null>(null);
  const [worker, setWorker] = React.useState<WorkerHealth | null>(null);
  const [buildOptions, setBuildOptions] = React.useState<BuildOption[]>([]);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [pollState, setPollState] = React.useState<PollState>({
    status: "idle",
    label: "waiting",
    lastOkAt: ""
  });

  const load = React.useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError("");
    }
    setPollState((current) => ({
      ...current,
      status: "polling",
      label: "/api/state + /api/worker + /api/build-options"
    }));
    try {
      const [nextSnapshot, nextWorker, nextBuildOptions] = await Promise.all([
        apiJson<StateSnapshot>("/api/state"),
        apiJson<WorkerHealth>("/api/worker"),
        apiJson<BuildOption[]>("/api/build-options")
      ]);
      setSnapshot(nextSnapshot);
      setWorker(nextWorker);
      setBuildOptions(nextBuildOptions);
      setError("");
      setPollState({
        status: "ok",
        label: "/api/state + /api/worker + /api/build-options",
        lastOkAt: new Date().toLocaleTimeString()
      });
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      setError(message);
      setPollState((current) => ({
        ...current,
        status: "failed",
        label: message
      }));
    } finally {
      if (!options?.silent) {
        setLoading(false);
      }
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    const timerId = window.setInterval(() => {
      void load({ silent: true });
    }, DASHBOARD_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timerId);
  }, [load]);

  React.useEffect(() => {
    function reloadWhenVisible() {
      if (document.visibilityState === "visible") {
        void load({ silent: true });
      }
    }

    document.addEventListener("visibilitychange", reloadWhenVisible);
    window.addEventListener("focus", reloadWhenVisible);
    return () => {
      document.removeEventListener("visibilitychange", reloadWhenVisible);
      window.removeEventListener("focus", reloadWhenVisible);
    };
  }, [load]);

  return { snapshot, worker, buildOptions, error, loading, pollState, load };
}

function App() {
  const jobMatch = window.location.pathname.match(/^\/jobs\/(\d+)$/);
  if (jobMatch) {
    return <JobLogPage jobId={Number(jobMatch[1])} />;
  }
  return <Dashboard />;
}

function Dashboard() {
  const { snapshot, worker, buildOptions, error, loading, pollState, load } = useDashboardData();
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
        <div className="topbar-actions">
          <PollIndicator
            label="Dashboard poll"
            status={pollState.status}
            detail={pollState.lastOkAt || pollState.label}
          />
          <button className="icon-button" type="button" onClick={() => void load()} title="Refresh">
            <RefreshCw size={18} />
          </button>
        </div>
      </header>

      {error ? <div className="alert">{error}</div> : null}
      {loading && !snapshot ? <div className="loading">Loading registry state...</div> : null}

      {snapshot ? (
        <main className="workspace">
          <section className="band">
            <SectionHeader title="Create local job" icon={<Plus size={18} />} />
            <JobCreateForm
              form={form}
              buildOptions={buildOptions}
              setForm={setForm}
              onSubmit={createJob}
              submitting={submitting}
              error={submitError}
            />
          </section>
          <section className="band">
            <SectionHeader title="Worker" icon={<Server size={18} />} />
            <WorkerPanel worker={worker} />
          </section>
          <section className="band">
            <SectionHeader title="Contours" icon={<Activity size={18} />} />
            <ContourGrid contours={snapshot.contours} />
          </section>
          <section className="band">
            <SectionHeader title="Jobs" icon={<Play size={18} />} />
            <JobsSection jobs={snapshot.jobs} onUpdate={updateJob} />
          </section>
          <DataTables snapshot={snapshot} />
        </main>
      ) : null}
    </div>
  );
}

function PollIndicator({
  label,
  status,
  detail
}: {
  label: string;
  status: PollStatus | StreamStatus;
  detail?: string;
}) {
  const title = detail ? `${label}: ${status} (${detail})` : `${label}: ${status}`;
  return (
    <span className={`poll-indicator poll-${status}`} title={title} aria-label={title}>
      <span className="poll-dot" />
      <span className="poll-label">{label}</span>
    </span>
  );
}

function SectionHeader({
  title,
  icon,
  action
}: {
  title: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="section-header">
      <div className="section-title">
        <span>{icon}</span>
        <h2>{title}</h2>
      </div>
      {action ? <div className="section-action">{action}</div> : null}
    </div>
  );
}

function JobCreateForm({
  form,
  buildOptions,
  setForm,
  onSubmit,
  submitting,
  error
}: {
  form: JobFormState;
  buildOptions: BuildOption[];
  setForm: React.Dispatch<React.SetStateAction<JobFormState>>;
  onSubmit: (event: React.FormEvent) => void;
  submitting: boolean;
  error: string;
}) {
  const needsContour = ["deploy", "pipeline", "set_baseline", "mark_applied", "mark_failed"].includes(form.kind);
  const needsBuildVersion = ["deploy", "set_baseline", "mark_applied", "mark_failed"].includes(form.kind) && !(form.kind === "deploy" && form.latest);
  const needsTimeout = ["build", "pipeline"].includes(form.kind);
  const selectedBuild = buildOptions.find((option) => option.build_version === form.buildVersion) ?? null;
  const submitDisabled = submitting || (needsBuildVersion && !selectedBuild) || (form.kind === "mark_failed" && !form.error.trim());

  React.useEffect(() => {
    if (!needsBuildVersion || form.buildVersion || !buildOptions.length) {
      return;
    }
    setForm((current) => ({ ...current, buildVersion: buildOptions[0].build_version }));
  }, [buildOptions, form.buildVersion, needsBuildVersion, setForm]);

  return (
    <form className="job-form" onSubmit={onSubmit}>
      <label>
        Kind
        <select value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.target.value as JobKind }))}>
          {(Object.keys(jobKindLabels) as JobKind[]).map((kind) => (
            <option value={kind} key={kind}>
              {jobKindOptionLabel(kind, form.contour)}
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
          <select
            value={form.buildVersion}
            disabled={!buildOptions.length}
            onChange={(event) => setForm((current) => ({ ...current, buildVersion: event.target.value }))}
          >
            {!buildOptions.length ? <option value="">No successful builds</option> : null}
            {buildOptions.map((option) => (
              <option value={option.build_version} key={option.build_version}>
                {option.build_version}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {needsBuildVersion ? (
        <div className="readonly-field">
          <span>Backend commit</span>
          <strong>{selectedBuild?.backend_commit || "select build version"}</strong>
        </div>
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
      <button className="primary-button" disabled={submitDisabled} type="submit">
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

function WorkerPanel({ worker }: { worker: WorkerHealth | null }) {
  if (!worker) {
    return <p className="empty">Worker state unavailable</p>;
  }
  const heartbeat = worker.heartbeat;
  return (
    <div className="worker-grid">
      <div className="metric-tile">
        <span>Status</span>
        <strong><Status value={worker.status} /></strong>
        <small>{heartbeat?.message || "no heartbeat"}</small>
      </div>
      <div className="metric-tile">
        <span>Queue</span>
        <strong>{worker.queued_jobs}</strong>
        <small>queued jobs</small>
      </div>
      <div className="metric-tile">
        <span>Running</span>
        <strong>{worker.running_jobs}</strong>
        <small>{heartbeat?.current_job_id ? `job ${heartbeat.current_job_id}` : "no active job"}</small>
      </div>
      <div className="metric-tile">
        <span>Last seen</span>
        <strong>{heartbeat?.updated_at || "never"}</strong>
        <small>{worker.stale_after_seconds}s stale threshold</small>
      </div>
    </div>
  );
}

function JobsSection({ jobs, onUpdate }: { jobs: Job[]; onUpdate: (jobId: number, status: "cancelled" | "queued") => Promise<void> }) {
  const [statusFilter, setStatusFilter] = React.useState<JobStatusFilter>("all");
  const [kindFilter, setKindFilter] = React.useState<JobKindFilter>("all");
  const [query, setQuery] = React.useState("");

  const filteredJobs = React.useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return jobs.filter((job) => {
      if (statusFilter !== "all" && job.status !== statusFilter) return false;
      if (kindFilter !== "all" && job.kind !== kindFilter) return false;
      if (!normalizedQuery) return true;
      return [
        String(job.id),
        job.kind,
        job.contour,
        job.build_version,
        job.status,
        job.error
      ].some((value) => value.toLowerCase().includes(normalizedQuery));
    });
  }, [jobs, statusFilter, kindFilter, query]);

  return (
    <>
      <div className="table-toolbar">
        <span className="toolbar-icon"><ListFilter size={16} /></span>
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as JobStatusFilter)}>
            <option value="all">all</option>
            <option value="queued">queued</option>
            <option value="running">running</option>
            <option value="success">success</option>
            <option value="failed">failed</option>
            <option value="cancelled">cancelled</option>
          </select>
        </label>
        <label>
          Kind
          <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value as JobKindFilter)}>
            <option value="all">all</option>
            {(Object.keys(jobKindLabels) as JobKind[]).map((kind) => (
              <option value={kind} key={kind}>{jobKindLabels[kind]}</option>
            ))}
          </select>
        </label>
        <label className="toolbar-search">
          Search
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        <span className="toolbar-count">{filteredJobs.length} / {jobs.length}</span>
      </div>
      <JobsTable jobs={filteredJobs} onUpdate={onUpdate} />
    </>
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

function prettyPayload(payloadJson: string): string {
  try {
    return JSON.stringify(JSON.parse(payloadJson || "{}"), null, 2);
  } catch {
    return payloadJson || "{}";
  }
}

function JobDetail({
  job,
  onUpdate
}: {
  job: Job | null;
  onUpdate: (status: "cancelled" | "queued") => Promise<void>;
}) {
  if (!job) {
    return <p className="empty">Loading job...</p>;
  }
  const fields = [
    ["Kind", jobKindLabels[job.kind]],
    ["Contour", job.contour || "-"],
    ["Build version", job.build_version || "-"],
    ["Created", job.created_at || "-"],
    ["Started", job.started_at || "-"],
    ["Finished", job.finished_at || "-"],
    ["Log path", job.log_path || "-"]
  ];
  return (
    <div className="job-detail">
      <div className="job-detail-header">
        <Status value={job.status} />
        <div className="row-actions">
          {job.status === "queued" ? (
            <button className="icon-button danger" type="button" title="Cancel" onClick={() => void onUpdate("cancelled")}>
              <Ban size={16} />
            </button>
          ) : null}
          {job.status === "failed" || job.status === "cancelled" ? (
            <button className="icon-button" type="button" title="Requeue" onClick={() => void onUpdate("queued")}>
              <RotateCcw size={16} />
            </button>
          ) : null}
        </div>
      </div>
      <div className="job-detail-grid">
        {fields.map(([label, value]) => (
          <div className="detail-cell" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      {job.error ? <div className="alert">{job.error}</div> : null}
      <pre className="payload-view">{prettyPayload(job.payload_json)}</pre>
    </div>
  );
}

function JobLogPage({ jobId }: { jobId: number }) {
  const [job, setJob] = React.useState<Job | null>(null);
  const [log, setLog] = React.useState("");
  const [error, setError] = React.useState("");
  const [streamStatus, setStreamStatus] = React.useState<StreamStatus>("connecting");
  const [streamRevision, setStreamRevision] = React.useState(0);
  const logRef = React.useRef<HTMLPreElement | null>(null);

  const restartStream = React.useCallback(() => {
    setError("");
    setLog("");
    setStreamRevision((current) => current + 1);
  }, []);

  React.useEffect(() => {
    let closed = false;
    setError("");
    setLog("");
    setStreamStatus("connecting");
    apiJson<Job>(`/api/jobs/${jobId}`)
      .then((nextJob) => {
        if (!closed) setJob(nextJob);
      })
      .catch((exc) => {
        if (!closed) setError(exc instanceof Error ? exc.message : String(exc));
      });
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/jobs/${jobId}`);
    socket.addEventListener("open", () => {
      if (!closed) setStreamStatus("open");
    });
    socket.addEventListener("message", (event) => {
      if (closed) return;
      const message = JSON.parse(event.data) as { type: string; text?: string; status?: JobStatus; job?: Job; message?: string };
      if (message.type === "snapshot" && message.job) setJob(message.job);
      if ((message.type === "status" || message.type === "done") && message.status) {
        setJob((current) => current ? { ...current, status: message.status as JobStatus } : current);
      }
      if (message.type === "done") {
        void apiJson<Job>(`/api/jobs/${jobId}`)
          .then((nextJob) => {
            if (!closed) setJob(nextJob);
          })
          .catch((exc) => {
            if (!closed) setError(exc instanceof Error ? exc.message : String(exc));
          });
      }
      if (message.type === "log" && message.text) setLog((current) => current + message.text);
      if (message.type === "error" && message.message) setError(message.message);
    });
    socket.addEventListener("error", () => {
      setStreamStatus("failed");
      setError("WebSocket connection failed");
    });
    socket.addEventListener("close", () => {
      if (!closed) setStreamStatus((current) => current === "failed" ? current : "closed");
    });
    return () => {
      closed = true;
      socket.close();
    };
  }, [jobId, streamRevision]);

  React.useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [log]);

  async function updateJob(status: "cancelled" | "queued") {
    setError("");
    try {
      const updated = await apiJson<Job>(`/api/jobs/${jobId}`, {
        method: "PATCH",
        body: JSON.stringify({ status })
      });
      setJob(updated);
      restartStream();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  return (
    <div className="app-shell job-log-shell">
      <header className="topbar">
        <div>
          <h1>Job {jobId}</h1>
          <p>{job ? `${jobKindLabels[job.kind]} / ${job.status}` : "Loading job log"}</p>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" type="button" onClick={restartStream} title="Refresh job">
            <RefreshCw size={18} />
          </button>
          <a className="icon-link" href="/" title="Dashboard">
            <ArrowLeft size={18} />
          </a>
        </div>
      </header>
      {error ? <div className="alert">{error}</div> : null}
      <main className="workspace job-log-workspace">
        <section className="band job-detail-section">
          <SectionHeader title="Job detail" icon={<Activity size={18} />} />
          <JobDetail job={job} onUpdate={updateJob} />
        </section>
        <section className="band live-log-section">
          <SectionHeader
            title="Live log"
            icon={<FileText size={18} />}
            action={
              <PollIndicator
                label="Log stream"
                status={streamStatus}
                detail={`/ws/jobs/${jobId}`}
              />
            }
          />
          <pre className="log-view" ref={logRef}>{log || "Waiting for log output..."}</pre>
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
