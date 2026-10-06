// design.md §6.5 / §6.6 / §7 — under 900 px: JOBS / LISTEN / WORKERS / LOG. Browse and audition only.
import { useEffect, useMemo, useState } from "react";
import { Btn, Chip, Led, SegProgress, Seg, SevenSeg, Waveform } from "../components/ui";
import { WorkerCard, elapsed } from "../screens/Jobs";
import { PlayIcon, useAB } from "../screens/AB";
import { api, type Job } from "../lib/api";
import { peaks } from "../lib/audio";
import { clock, tuneRatio, tuneStr } from "../lib/format";
import { resync, useLive } from "../lib/live";
import { navigate, useLocation } from "../lib/router";
import "./mobile.css";

const TABS = [
  { to: "/jobs", l: "JOBS" },
  { to: "/listen", l: "LISTEN" },
  { to: "/workers", l: "WORKERS" },
  { to: "/log", l: "LOG" },
];
const TICKS: Record<string, [number, string][]> = {
  sp: [[0, "ROLE"], [3, "CAP"], [6, "ENV"], [9, "OUT"]],
  mpc: [[0, "IN"], [2, "CODEC"], [4, "OUT"]],
};

export default function Mobile() {
  const { path } = useLocation();
  const tab = TABS.findIndex((t) => t.to === path || (t.to === "/listen" && path === "/ab"));
  const active = tab < 0 ? 0 : tab;
  const { connected } = useLive();
  return (
    <div className="m">
      <header className="m-head">
        <span className="m-logo">1260</span>
        <span className="m-title">{TABS[active].l}</span>
        <span className="m-net">
          <span className="mono lo">tailnet</span>
          <Led on={connected} sm />
        </span>
      </header>
      <main className="m-main">
        {active === 0 && <MJobs />}
        {active === 1 && <MListen />}
        {active === 2 && <MWorkers />}
        {active === 3 && <MLog />}
      </main>
      <nav className="m-tabs">
        {TABS.map((t, i) => (
          <a
            key={t.to}
            href={t.to}
            aria-current={i === active ? "page" : undefined}
            onClick={(e) => {
              e.preventDefault();
              navigate(t.to);
            }}
          >
            <span>{t.l}</span>
            <Led on={i === active} sm />
          </a>
        ))}
      </nav>
    </div>
  );
}

function Kpi({ label, value, of, bad }: { label: string; value: number; of?: number; bad?: boolean }) {
  return (
    <div className={`m-kpi ${bad && value > 0 ? "bad" : ""}`}>
      <span className="label">{label}</span>
      <span className="m-kpi-v">
        <SevenSeg text={String(value).padStart(of != null ? 1 : 2, "0")} h={24} fail={bad && value > 0} />
        {of != null && <span className="micro">/{of}</span>}
      </span>
    </div>
  );
}

function JobCard({ j }: { j: Job }) {
  const [trace, setTrace] = useState(false);
  const failed = j.state === "failed";
  const cur = j.stages.find((s) => s.state === "running") ?? j.stages.find((s) => s.state === "failed") ?? null;
  const pct = cur ? Math.round(cur.progress * 100) : 0;
  const n = j.stages.length;
  const errLine = j.error?.split("\n").filter(Boolean).pop() ?? "";
  return (
    <div className={`m-card ${failed ? "fail" : ""}`}>
      <div className="m-card-top">
        <span className="mono lo">{j.short}</span>
        <span className="mono hi m-name">{j.sample_name}</span>
        <Chip state={j.state} />
      </div>
      <div className="m-card-sub">
        <span className="meta">{failed ? `${errLine.split(":")[0]} @ ${cur ? stageLabel(cur.ordinal, cur.name) : "—"}` : `${j.preset_name} · tune ${tuneStr(j.tune)}`}</span>
        <span className="meta">{elapsed(j)}s</span>
      </div>
      <div className="m-card-stage">
        <span>{failed ? "FAIL " : ""}{cur ? stageLabel(cur.ordinal, cur.name) : j.state === "queued" ? "QUEUED" : "—"}</span>
        {!failed && <span className="mono">{pct}%</span>}
      </div>
      <SegProgress stages={j.stages} />
      <div className="m-ticks">
        {(TICKS[j.path ?? "sp"] ?? []).map(([k, l]) => (
          <span key={l} className="micro" style={{ left: `${((k + 0.5) / n) * 100}%` }}>{l}</span>
        ))}
      </div>
      {failed && (
        <>
          <div className="two" style={{ marginTop: 6 }}>
            <Btn kind="primary" h={34} w="100%" onClick={() => api.retry(j.id).then(resync)}>RETRY</Btn>
            <Btn h={34} w="100%" onClick={() => setTrace(!trace)}>TRACE</Btn>
          </div>
          {trace && <pre className="m-trace">{j.error}</pre>}
        </>
      )}
    </div>
  );
}

function stageLabel(ordinal: number, name: string) {
  return `${String(ordinal + 1).padStart(2, "0")} ${name.toUpperCase().replace("_", " ")}`;
}

function MJobs() {
  const { snap } = useLive();
  const jobs = snap?.jobs ?? [];
  const live = jobs.filter((j) => j.state === "running" || j.state === "failed").slice(0, 6);
  const queued = jobs.filter((j) => j.state === "queued");
  const workers = snap?.workers.filter((w) => w.state !== "stopped") ?? [];
  return (
    <>
      <div className="m-kpis">
        <Kpi label="Q" value={snap?.queue ?? 0} />
        <Kpi label="RUN" value={snap?.counts.running ?? 0} />
        <Kpi label="WRK" value={workers.filter((w) => w.state !== "lost").length} of={workers.length} />
        <Kpi label="FAIL" value={snap?.counts_24h.failed ?? 0} bad />
      </div>
      {live.map((j) => <JobCard key={j.id} j={j} />)}
      {!live.length && <div className="empty">Nothing running. Render from CHAIN on the desktop.</div>}
      <div className="m-sect">
        <span className="label lo">QUEUED</span>
        <div className="rule" />
      </div>
      {queued.map((j) => (
        <div key={j.id} className="m-q">
          <span className="mono lo">{j.short}</span>
          <span className="mono hi">{j.sample_name}</span>
          <span className="micro">{j.preset_name}</span>
        </div>
      ))}
      {!queued.length && <div className="empty">empty</div>}
    </>
  );
}

function MListen() {
  const { snap } = useLive();
  const { query } = useLocation();
  const done = (snap?.jobs ?? []).filter((j) => j.state === "succeeded" && j.output_name);
  const job = done.find((j) => j.id === query.get("j")) ?? done[0] ?? null;
  const pairJob = done.find((j) => j.path !== job?.path && j.sample_id !== job?.sample_id) ?? null;
  const siblings = done.filter((j) => j.sample_id === job?.sample_id);
  const [pairOn, setPairOn] = useState(false);
  const [side, setSide] = useState<"A" | "B">("B");
  const [loop, setLoop] = useState(true);
  const [match, setMatch] = useState(false);
  const [table, setTable] = useState("measured");
  const [outRate, setOutRate] = useState<number | null>(null);
  const { player, layers, err } = useAB(job, pairJob, pairOn);

  useEffect(() => {
    if (!job) return;
    api
      .jobParams(job.id)
      .then((p) => {
        setTable(p?.params?.tune?.table ?? "measured");
        const r = p?.params?.output?.rate;
        setOutRate(r === "native" ? (job.path === "sp" ? 26041.67 : 40000) : (r ?? null));
      })
      .catch(() => {});
  }, [job?.id]);
  useEffect(() => player.setSide(side), [side]);
  useEffect(() => player.setLoop(loop), [loop]);
  useEffect(() => player.setMatch(match), [match]);

  const pkA = useMemo(() => (layers ? peaks(layers.main.a, 400) : null), [layers]);
  const pkB = useMemo(() => (layers ? peaks(layers.main.b, 400) : null), [layers]);
  if (!job) return <div className="empty">No render yet. Render from CHAIN on the desktop.</div>;

  const dur = player.duration();
  const pos = player.position();
  const stem = (job.output_name ?? "").replace(/\.wav$/, "");
  const cut = stem.indexOf("__");
  const tune = job.tune ?? 0;
  const ratio = job.path === "sp" ? tuneRatio(tune, table) : 2 ** (tune / 12);
  const sr = outRate;

  return (
    <>
      <div className="m-file">
        <div>
          <div className="mono hi" style={{ fontSize: 13 }}>{cut > 0 ? stem.slice(0, cut) : stem}</div>
          <div className="mono" style={{ fontSize: 11, color: "var(--tx-md)" }}>{cut > 0 ? `${stem.slice(cut)}.wav` : ".wav"}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="micro">{job.short}</div>
          <div className="micro">24b · {sr ? `${+(sr / 1000).toFixed(2)}k` : "—"}</div>
        </div>
      </div>
      <div className="row" style={{ gap: 10 }}>
        <Seg h={24} size={11} style={{ width: 150 }} value={pairOn ? "pair" : "solo"} onChange={(v) => setPairOn(v === "pair" && !!pairJob)} items={[{ value: "solo", label: "SOLO" }, { value: "pair", label: "PAIR" }]} />
        <span className="micro" style={{ marginLeft: "auto", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {pairJob ? `+ ${pairJob.path === "mpc" ? "B" : "A"} ${pairJob.sample_name?.replace(/\.\w+$/, "")}` : "no pair render"}
        </span>
      </div>
      <div className="lcd" style={{ padding: 3 }}>
        <Waveform a={side === "A" ? pkB : pkA} b={side === "A" ? pkA : pkB} colorA="#2a3138" colorB={side === "A" ? "#88919b" : "#6c97be"} height={124} head={dur ? pos / dur : null} onSeek={(f) => player.seek(f * dur)} />
      </div>
      <div className="row" style={{ justifyContent: "space-between", marginTop: -4 }}>
        <span className="meta">{pos.toFixed(3)}</span>
        <span className="meta">{dur.toFixed(3)} s</span>
      </div>
      {err && <div className="err-line">{err}</div>}
      <div className="ab m-ab">
        <button aria-pressed={side === "A"} onClick={() => setSide("A")}>
          <span className="stencil">A</span>
          <span className="label" style={{ color: "inherit", fontSize: 10 }}>SOURCE</span>
        </button>
        <button aria-pressed={side === "B"} onClick={() => setSide("B")}>
          <span className="stencil">B</span>
          <span className="label" style={{ color: "inherit", fontSize: 10 }}>RENDER</span>
        </button>
      </div>
      <div className="micro" style={{ textAlign: "center", marginTop: -4 }}>tap to flip · position is kept</div>
      <div className="m-play">
        <button className="m-pbtn" onClick={() => (player.playing ? player.stop() : player.play())} disabled={!layers} aria-label={player.playing ? "pause" : "play"}>
          <PlayIcon playing={player.playing} />
        </button>
        <div className="m-tune">
          <div className="lcd m-tune-lcd">
            <SevenSeg text={tuneStr(tune)} h={22} />
            <span className="label lo">TUNE</span>
            <span className="mono ac" style={{ marginLeft: "auto", fontSize: 10.5 }}>
              {job.path === "sp" ? (table === "measured" ? "MEAS" : "ET") : "ST"} ×{ratio.toFixed(4)}
            </span>
          </div>
          <div className="m-tune-row">
            <Btn kind={loop ? "primary" : "normal"} h={30} w={80} size={11} onClick={() => setLoop(!loop)}>LOOP</Btn>
            <Btn kind={match ? "primary" : "normal"} h={30} w="100%" size={11} onClick={() => setMatch(!match)}>MATCH RMS</Btn>
          </div>
        </div>
      </div>
      <div className="m-sect">
        <span className="label lo">RENDERS · {job.sample_name?.replace(/\.\w+$/, "").toUpperCase()}</span>
        <div className="rule" />
      </div>
      {siblings.map((j) => (
        <button key={j.id} className={`m-render ${j.id === job.id ? "sel" : ""}`} onClick={() => navigate(`/listen?j=${j.id}`)}>
          <span className="m-ricon">
            <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><path d="M2 1 L11 6 L2 11 Z" fill="currentColor" /></svg>
          </span>
          <span>
            <span className="mono hi" style={{ display: "block", fontSize: 12 }}>tune {tuneStr(j.tune)}</span>
            <span className="micro">{j.preset_name}</span>
          </span>
          <span className="meta" style={{ marginLeft: "auto" }}>{elapsed(j)}s</span>
        </button>
      ))}
    </>
  );
}

function MWorkers() {
  const { snap } = useLive();
  const workers = snap?.workers.filter((w) => w.state !== "stopped") ?? [];
  const running = snap?.jobs.filter((j) => j.state === "running") ?? [];
  return (
    <>
      {workers.map((w) => <WorkerCard key={w.id} w={w} job={running.find((j) => j.worker_id === w.id)} />)}
      {!workers.length && <div className="empty">No worker has checked in.</div>}
    </>
  );
}

function MLog() {
  const { snap } = useLive();
  const [level, setLevel] = useState<"INFO" | "ERR">("INFO");
  const log = (snap?.log ?? []).filter((l) => level === "INFO" || l.level === "ERR").slice().reverse();
  return (
    <>
      <div className="row">
        <span className="label lo">LEVEL</span>
        <Seg h={24} mono size={10.5} style={{ width: 110 }} value={level} onChange={setLevel} items={[{ value: "INFO", label: "INFO" }, { value: "ERR", label: "ERR" }]} />
      </div>
      <div className="m-log">
        {log.map((l) => (
          <div key={l.id} className={l.level}>
            <span className="t">{clock(l.ts)}</span>
            <span className="lv">{l.level}</span>
            <span className={`src ${/^[0-9a-f]{4}$/.test(l.source) ? "job" : ""}`}>{l.source}</span>
            <span className="msg">{l.message}</span>
          </div>
        ))}
      </div>
    </>
  );
}
