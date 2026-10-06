// Thin client for the FastAPI backend (same origin).

export type Role = "kick" | "snare" | "hat" | "perc" | "other";
export type Route = "sp" | "mpc";
export type JobState = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Sample {
  id: string;
  name: string;
  sha256: string;
  length_s: number | null;
  sample_rate: number | null;
  role: Role | null;
  route: Route;
  created_at: string;
  renders: number;
}

export interface Preset {
  id: string;
  name: string;
  path: Route;
  version: number;
  params: Params;
}

// Engine params are nested dicts (engine/params.py); kept loose on purpose.
export type Params = Record<string, any>;

export interface ParamSpec {
  status: "VER" | "HYP";
  note: string;
  candidates: unknown[] | null;
  lo: number | null;
  hi: number | null;
}

export interface Stage {
  ordinal: number;
  name: string;
  state: "pending" | "running" | "succeeded" | "failed" | "skipped" | "cancelled";
  progress: number;
  duration_s: number | null;
}

export interface Job {
  id: string;
  short: string;
  state: JobState;
  worker_id: string | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_by: string | null;
  stages: Stage[];
  sample_id: string;
  sample_name: string | null;
  preset_id: string;
  preset_name: string | null;
  preset_version: number | null;
  path: Route | null;
  tune: number | null;
  overrides: Params;
  output_name: string | null;
  result_sha256: string | null;
}

export interface Worker {
  id: string;
  hostname: string;
  state: "idle" | "busy" | "stopped" | "lost";
  last_heartbeat: string;
  heartbeat_age_s: number;
  version: string;
}

export interface LogLine {
  id: number;
  ts: string;
  level: "INFO" | "WARN" | "ERR";
  source: string;
  message: string;
  job_id: string | null;
}

export interface Snapshot {
  queue: number;
  counts: Partial<Record<JobState, number>>;
  counts_24h: Partial<Record<JobState, number>>;
  workers: Worker[];
  jobs: Job[];
  log: LogLine[];
  redis: boolean;
}

export interface Health {
  status: string;
  version: string;
  db: string;
  redis: string;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const b = await r.json();
      if (b?.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => req<Health>("/api/health"),
  snapshot: () => req<Snapshot>("/api/snapshot"),
  samples: () => req<Sample[]>("/api/samples"),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return req<{ samples: (Sample & { created: boolean })[]; errors: string[] }>("/api/samples", {
      method: "POST",
      body: fd,
    });
  },
  patchSample: (id: string, body: Partial<Pick<Sample, "role" | "route">>) =>
    req<Sample>(`/api/samples/${id}`, { ...json(body), method: "PATCH" }),
  deleteSample: (id: string) => req<{ deleted: string }>(`/api/samples/${id}`, { method: "DELETE" }),
  sampleInfo: (id: string) => req<{ channels: number; subtype: string; format: string; bytes: number }>(`/api/samples/${id}/info`),
  store: () => req<{ data_dir: string; bytes: number }>("/api/store"),
  peaks: (id: string, n: number) => req<[number, number][]>(`/api/samples/${id}/peaks?n=${n}`),
  renders: (id: string) => req<Job[]>(`/api/samples/${id}/renders`),
  presets: () => req<Preset[]>("/api/presets"),
  schema: () => req<Record<string, ParamSpec>>("/api/params/schema"),
  savePreset: (name: string, path: Route, params: Params) => req<Preset>("/api/presets", json({ name, path, params })),
  render: (sample_id: string, preset_id: string, overrides: Params) =>
    req<{ id: string; short: string }>("/api/jobs", json({ sample_id, preset_id, overrides })),
  cancel: (id: string) => req<{ state: string }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  retry: (id: string) => req<{ id: string }>(`/api/jobs/${id}/retry`, { method: "POST" }),
  jobParams: (id: string) => req<Params>(`/api/jobs/${id}/params`),
};

export const urls = {
  sampleAudio: (id: string) => `/api/samples/${id}/audio`,
  sampleSpectro: (id: string) => `/api/samples/${id}/spectro.png`,
  jobWav: (id: string) => `/api/jobs/${id}/files/wav`,
  jobPng: (id: string) => `/api/jobs/${id}/files/png`,
  jobJson: (id: string) => `/api/jobs/${id}/files/json`,
};
