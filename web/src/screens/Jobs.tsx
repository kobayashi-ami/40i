// design.md §6.3 JOBS
import { useEffect, useMemo, useRef, useState } from "react";
import { Frame } from "../components/Frame";
import { Btn, Chip, Lcd, Led, Panel, Seg, SegProgress, SevenSeg, Toggle } from "../components/ui";
import { api, type Job, type Worker } from "../lib/api";
import { clock, tuneStr } from "../lib/format";
import { resync, useLive } from "../lib/live";
import { navigate, useLocation } from "../lib/router";
import "./screens.css";

export function elapsed(j: Job): string {
  if (!j.started_at) return "—";
  const end = j.finished_at ? new Date(j.finished_at).getTime() : Date.now();
  return ((end - new Date(j.started_at).getTime()) / 1000).toFixed(2);
}

export function percentile(xs: number[], p: number) {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
}

function Kpi({ label, value, bad }: { label: string; value: number; bad?: boolean }) {
  return (
    <Panel c={8} screws={false} bodyStyle={{ padding: "14px 16px 16px", gap: 10 }}>
      <span className="label" style={{ letterSpacing: "0.2em" }}>
        {label}
      </span>
      <Lcd className={bad && value > 0 ? "lcd-bad" : ""} style={{ height: 50, display: "flex", justifyContent: "flex-end", alignItems: "center", padding: "0 12px" }}>
        <SevenSeg text={String(value).padStart(3, " ")} h={34} fail={bad && value > 0} />
      </Lcd>
    </Panel>
  );
}

export function WorkerCard({ w, job }: { w: Worker; job?: Job }) {
  const lost = w.state === "lost";
  const frac = Math.max(0, 1 - w.heartbeat_age_s / 15);
  return (
    <div className={`wcard ${lost ? "lost" : ""}`}>
      <div className="wtop">
        <Led on={!lost && w.state !== "stopped"} />
        <span className="mono hi" style={{ fontSize: 13, fontWeight: 500 }}>
          {w.id}
        </span>
        <span style={{ marginLeft: "auto" }}>
          <Chip state={lost ? "lost" : w.state === "busy" ? "running" : w.state === "stopped" ? "cancelled" : "idle"} />
        </span>
      </div>
      <div className="wrow">
        <span className="label lo">HEARTBEAT</span>
        <span className={`hb ${lost ? "dead" : ""}`}>
          <b style={{ width: `${frac * 100}%` }} />
        </span>
        <span className={`mono ${lost ? "" : "hi"}`} style={{ color: lost ? "var(--fail)" : undefined }}>
          {w.heartbeat_age_s.toFixed(1)}s
        </span>
      </div>
      <div className="wrow">
        <span className="label lo">JOB</span>
        <span className="mono achi">{job ? `${job.short} · ${String((job.stages.find((s) => s.state === "running")?.ordinal ?? 0) + 1).padStart(2, "0")} ${(job.stages.find((s) => s.state === "running")?.name ?? "").toUpperCase()}` : "—"}</span>
      </div>
      <div className="wrow">
        <span className="label lo">VER</span>
        <span className="meta">
          {w.version} · pid {w.id.split(":").pop()}
        </span>
      </div>
    </div>
  );
}

export default function Jobs() {
  const { snap, connected } = useLive();
  const { query } = useLocation();
  const [follow, setFollow] = useState(true);
  const [level, setLevel] = useState<"INFO" | "ERR">("INFO");
  const [busy, setBusy] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const jobs = snap?.jobs ?? [];
  const selected = jobs.find((j) => j.id === query.get("j")) ?? jobs.find((j) => j.state === "failed") ?? jobs[0] ?? null;
  const durations = useMemo(
    () => jobs.filter((j) => j.state === "succeeded" && j.started_at && j.finished_at).map((j) => (new Date(j.finished_at!).getTime() - new Date(j.started_at!).getTime()) / 1000),
    [jobs],
  );
  const log = (snap?.log ?? []).filter((l) => level === "INFO" || l.level === "ERR");

  useEffect(() => {
    if (follow && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log.length, follow]);

  async function act(kind: "retry" | "cancel", id: string) {
    setBusy(kind);
    try {
      const r = kind === "retry" ? await api.retry(id) : await api.cancel(id);
      if (kind === "retry" && "id" in r) navigate(`/jobs?j=${(r as any).id}`);
      resync();
    } finally {
      setBusy(null);
    }
  }

  const c24 = snap?.counts_24h ?? {};
  const running = jobs.filter((j) => j.state === "running");
  return (
    <Frame active={2} context={`live · sse · ${connected ? "connected" : "reconnecting"}`}>
      <div className="jobs">
        <div className="kpis">
          <Kpi label="QUEUE" value={snap?.queue ?? 0} />
          <Kpi label="RUNNING" value={snap?.counts.running ?? 0} />
          <Kpi label="DONE 24H" value={c24.succeeded ?? 0} />
          <Kpi label="FAILED 24H" value={c24.failed ?? 0} bad />
          <Panel c={8} screws={false} bodyStyle={{ padding: "14px 16px", gap: 10 }}>
            <span className="label" style={{ letterSpacing: "0.2em" }}>
              THROUGHPUT
            </span>
            <span className="v" style={{ fontSize: 13 }}>
              {percentile(durations, 50)?.toFixed(2) ?? "—"} s / job&nbsp;&nbsp;(p50)
            </span>
            <span className="meta lo">
              {percentile(durations, 95)?.toFixed(2) ?? "—"} s / job (p95) · 1 s drum &lt; 1 s
            </span>
          </Panel>
        </div>

        <Panel title="WORKERS" idx="W" className="area-w">
          {(snap?.workers ?? []).filter((w) => w.state !== "stopped").map((w) => (
            <WorkerCard key={w.id} w={w} job={running.find((j) => j.worker_id === w.id)} />
          ))}
          {!snap?.workers.some((w) => w.state !== "stopped") && <div className="empty">No worker has checked in. Start one with `make dev` or `make up`.</div>}
        </Panel>

        <Panel title="QUEUE / HISTORY" idx="J" tone="bg1" className="area-j" bodyStyle={{ padding: "8px 8px 12px", overflow: "auto" }}>
          <table className="tbl">
            <colgroup>
              <col style={{ width: 46 }} />
              <col />
              <col style={{ width: 118 }} />
              <col style={{ width: 52 }} />
              <col style={{ width: 196 }} />
              <col style={{ width: 52 }} />
            </colgroup>
            <thead>
              <tr>
                <th>ID</th>
                <th>SAMPLE</th>
                <th>PRESET</th>
                <th>ST</th>
                <th>STAGES</th>
                <th style={{ textAlign: "right" }}>SEC</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => {
                const dim = j.state === "succeeded" || j.state === "cancelled";
                const on = j.id === selected?.id;
                return (
                  <tr key={j.id} style={{ height: 30 }} className={`${on ? "sel" : ""} ${on && j.state === "failed" ? "bad" : ""} ${dim ? "dim" : ""}`} onClick={() => navigate(`/jobs?j=${j.id}`)}>
                    <td className="meta">{j.short}</td>
                    <td className={dim ? "" : "hi"}>{j.sample_name ?? "—"}</td>
                    <td className="meta">{j.preset_name}</td>
                    <td>
                      <Chip state={j.state} />
                    </td>
                    <td>
                      <div style={{ width: j.stages.length === 10 ? 180 : 88 }}>
                        <SegProgress stages={j.stages} dim={dim} />
                      </div>
                    </td>
                    <td className="meta" style={{ textAlign: "right" }}>
                      {elapsed(j)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!jobs.length && <div className="empty">No jobs yet. Render something from CHAIN.</div>}
        </Panel>

        <Panel title={selected ? `JOB ${selected.short}` : "JOB"} idx="→" className="area-d" aside={selected && <Chip state={selected.state} />}>
          {selected ? (
            <>
              <div>
                <div className="mono hi" style={{ fontSize: 12, fontWeight: 500 }}>
                  {selected.sample_name}
                </div>
                <div className="micro">
                  {selected.preset_name} v{selected.preset_version} · tune {tuneStr(selected.tune)}
                  {selected.worker_id ? ` · ${selected.worker_id}` : ""}
                  {selected.created_by ? ` · ${selected.created_by}` : ""}
                </div>
              </div>
              <div className="stagelist">
                {selected.stages.map((s) => (
                  <div key={s.ordinal} className={s.state}>
                    <span>
                      {String(s.ordinal + 1).padStart(2, "0")} {s.name.toUpperCase().replace("_", "-")}
                    </span>
                    <span>{s.duration_s != null ? s.duration_s.toFixed(3) : "—"}</span>
                    <span className="st">{s.state === "succeeded" ? "OK" : s.state === "failed" ? "FAIL" : s.state === "running" ? `${Math.round(s.progress * 100)}%` : s.state === "cancelled" ? "CXL" : ""}</span>
                  </div>
                ))}
              </div>
              {selected.error && (
                <>
                  <span className="label">TRACEBACK</span>
                  <Lcd className="trace">
                    {selected.error.split("\n").map((l, i) => (
                      <div key={i} className={/^\w*(Error|Exception)/.test(l) ? "bad" : ""}>
                        {l || " "}
                      </div>
                    ))}
                  </Lcd>
                </>
              )}
              <div className="micro">
                attempt {selected.attempts}/3 · retry re-enqueues to stream
                {selected.result_sha256 ? ` · sha ${selected.result_sha256.slice(0, 8)}` : ""}
              </div>
              <div className="three" style={{ marginTop: "auto" }}>
                <Btn kind={busy === "retry" ? "running" : "primary"} h={40} w="100%" disabled={!(selected.state === "failed" || selected.state === "cancelled")} onClick={() => act("retry", selected.id)}>
                  RETRY
                </Btn>
                <Btn h={40} w="100%" disabled={!(selected.state === "queued" || selected.state === "running")} onClick={() => act("cancel", selected.id)}>
                  CANCEL
                </Btn>
                <Btn h={40} w="100%" disabled={selected.state !== "succeeded"} onClick={() => navigate(`/ab?j=${selected.id}`)}>
                  A/B
                </Btn>
              </div>
            </>
          ) : (
            <div className="empty">Select a job.</div>
          )}
        </Panel>

        <Panel
          title="LOG TAIL"
          idx="L"
          tone="bg1"
          className="area-l"
          bodyStyle={{ padding: "6px 4px 10px" }}
          aside={
            <span className="row" style={{ gap: 8 }}>
              <span className="label">FOLLOW</span>
              <Toggle on={follow} onChange={setFollow} label="follow log" />
              <span className="label lo">LEVEL</span>
              <Seg h={18} mono size={9.5} style={{ width: 72 }} value={level} onChange={setLevel} items={[{ value: "INFO", label: "INFO" }, { value: "ERR", label: "ERR" }]} />
            </span>
          }
        >
          <div className="log" ref={logRef}>
            {log.map((l) => (
              <div key={l.id} className={l.level}>
                <span className="t">{clock(l.ts)}</span>
                <span className="lv">{l.level}</span>
                <span className={`src ${/^[0-9a-f]{4}$/.test(l.source) ? "job" : ""}`}>{l.source.length > 8 ? l.source.slice(0, 8) : l.source}</span>
                <span className="msg">{l.message}</span>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </Frame>
  );
}
