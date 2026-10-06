// design.md §6.4 A/B
import { useEffect, useMemo, useRef, useState } from "react";
import { Frame } from "../components/Frame";
import { Lcd, Panel, Seg, SevenSeg, Toggle, Waveform } from "../components/ui";
import { api, urls, type Job, type Params } from "../lib/api";
import { ABPlayer, loadBuffer, metrics, peaks, type Layer, type Metrics } from "../lib/audio";
import { tuneStr } from "../lib/format";
import { useLive } from "../lib/live";
import { useLocation } from "../lib/router";
import "./screens.css";

export function useAB(main: Job | null, pair: Job | null, pairOn: boolean) {
  const player = useRef(new ABPlayer()).current;
  const [layers, setLayers] = useState<{ main: Layer; pair: Layer | null } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [, tick] = useState(0);
  useEffect(() => {
    let live = true;
    setErr(null);
    if (!main) return setLayers(null);
    const want = [loadBuffer(urls.sampleAudio(main.sample_id)), loadBuffer(urls.jobWav(main.id))];
    if (pair) want.push(loadBuffer(urls.sampleAudio(pair.sample_id)), loadBuffer(urls.jobWav(pair.id)));
    Promise.all(want)
      .then((b) => live && setLayers({ main: { a: b[0], b: b[1] }, pair: pair ? { a: b[2], b: b[3] } : null }))
      .catch((e) => live && setErr(String(e.message ?? e)));
    return () => {
      live = false;
    };
  }, [main?.id, pair?.id]);
  useEffect(() => {
    if (layers) player.setLayers(pairOn && layers.pair ? [layers.main, layers.pair] : [layers.main]);
  }, [layers, pairOn]);
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      tick((n) => n + 1);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    player.onEnd = () => tick((n) => n + 1);
    return () => {
      cancelAnimationFrame(raf);
      player.stop();
    };
  }, []);
  return { player, layers, err };
}

export function PlayIcon({ playing }: { playing: boolean }) {
  return playing ? (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden>
      <rect x="4" y="3" width="4.5" height="14" fill="currentColor" />
      <rect x="11.5" y="3" width="4.5" height="14" fill="currentColor" />
    </svg>
  ) : (
    <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden>
      <path d="M5 3 L17 10 L5 17 Z" fill="currentColor" />
    </svg>
  );
}

const fmt = (v: number, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : "—");

export default function AB() {
  const { snap } = useLive();
  const { query } = useLocation();
  const done = (snap?.jobs ?? []).filter((j) => j.state === "succeeded" && j.output_name);
  const job = done.find((j) => j.id === query.get("j")) ?? done[0] ?? null;
  const pairJob = done.find((j) => j.path !== job?.path && j.sample_id !== job?.sample_id) ?? null;
  const [pairOn, setPairOn] = useState(false);
  const [side, setSide] = useState<"A" | "B">("B");
  const [loop, setLoop] = useState(true);
  const [match, setMatch] = useState(false);
  const [params, setParams] = useState<Params | null>(null);
  const [srcRate, setSrcRate] = useState<number | null>(null);
  const { player, layers, err } = useAB(job, pairJob, pairOn);

  useEffect(() => {
    if (!job) return;
    api.jobParams(job.id).then(setParams).catch(() => setParams(null));
    api.samples().then((all) => setSrcRate(all.find((s) => s.id === job.sample_id)?.sample_rate ?? null)).catch(() => {});
  }, [job?.id]);
  useEffect(() => player.setSide(side), [side]);
  useEffect(() => player.setLoop(loop), [loop]);
  useEffect(() => player.setMatch(match), [match]);

  const pkA = useMemo(() => (layers ? peaks(layers.main.a, 1000) : null), [layers]);
  const pkB = useMemo(() => (layers ? peaks(layers.main.b, 1000) : null), [layers]);
  const mA: Metrics | null = useMemo(() => (layers ? metrics(layers.main.a) : null), [layers]);
  const mB: Metrics | null = useMemo(() => (layers ? metrics(layers.main.b) : null), [layers]);
  const dur = player.duration();
  const pos = player.position();
  const rateB = params?.params?.output?.rate ?? 48000;
  const fmaxB = (rateB as number) / 2;
  const levels = params?.info?.adc_levels_used ?? params?.info?.codec_levels_used;

  const rows: [string, string, string, string][] = mA && mB
    ? [
        ["PEAK", fmt(mA.peak), fmt(mB.peak), signed(mB.peak - mA.peak)],
        ["RMS", fmt(mA.rms), fmt(mB.rms), signed(mB.rms - mA.rms)],
        ["CREST", fmt(mA.crest), fmt(mB.crest), signed(mB.crest - mA.crest)],
        ["CENTROID", `${(mA.centroid / 1000).toFixed(2)}k`, `${(mB.centroid / 1000).toFixed(2)}k`, `${signed((mB.centroid - mA.centroid) / 1000, 2)}k`],
        [">13K E", fmt(mA.hf), fmt(mB.hf), signed(mB.hf - mA.hf)],
        ["LEVELS", "—", levels ? String(levels) : "—", job?.path === "sp" ? "/4096" : ""],
        ["LEN", mA.len.toFixed(3), mB.len.toFixed(3), `${signed((mB.len - mA.len) * 1000, 0)}ms`],
      ]
    : [];

  const p = params?.params ?? {};
  const json = job?.path === "sp"
    ? [
        "{",
        `  "path": "sp",`,
        `  "capture": ${p.capture?.on ? p.capture.speed?.toFixed(3) : 1},`,
        `  "adc": {`,
        `    "sr": "${p.adc?.native_sr}",`,
        `    "bits": ${p.adc?.bits},`,
        `    "aa": "${p.adc?.aa}" @ ${p.adc?.aa_fc}  // HYP`,
        `  },`,
        `  "tune": ${p.tune?.st}, "${p.tune?.table}"  // HYP`,
        `  "dac": "${p.dac?.hold}",`,
        `  "analog": {"route": "${p.analog?.route}", "ch": ${p.analog?.ch}}`,
        "}",
      ]
    : [
        "{",
        `  "path": "mpc",`,
        `  "emph": ${p.input?.emph} +${p.input?.emph_db} dB  // HYP`,
        `  "codec": "${p.codec?.curve}"  // HYP`,
        `  "tune": ${p.tune?.st}, "${p.tune?.interp}"  // HYP`,
        `  "out": ${p.output?.rate}`,
        "}",
      ];

  const stem = job?.output_name?.replace(/\.wav$/, "") ?? "";
  return (
    <Frame active={3} context={job ? `${job.sample_name} · ${job.preset_name} · tune ${tuneStr(job.tune)}` : "no render yet"}>
      <div className="abscr">
        <Panel c={10} screws={false} className="transport" bodyStyle={{ padding: "14px 18px", flexDirection: "row", alignItems: "center", gap: 18 }}>
          <div className="ab" style={{ width: 128, height: 44 }}>
            <button aria-pressed={side === "A"} onClick={() => setSide("A")}>
              <span className="stencil">A</span>
            </button>
            <button aria-pressed={side === "B"} onClick={() => setSide("B")}>
              <span className="stencil">B</span>
            </button>
          </div>
          <div style={{ display: "grid", gap: 6 }}>
            <span className={`label ${side === "A" ? "hi" : "lo"}`}>DRY</span>
            <span className={`label ${side === "B" ? "ac" : "lo"}`}>WET</span>
          </div>
          <button className="tbtn" onClick={() => (player.playing ? player.stop() : player.play())} disabled={!layers} aria-label={player.playing ? "pause" : "play"}>
            <PlayIcon playing={player.playing} />
          </button>
          <button className="tbtn" onClick={() => { player.stop(); player.seek(0); }} disabled={!layers} aria-label="stop">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><rect x="2" y="2" width="12" height="12" fill="currentColor" /></svg>
          </button>
          <button className={`tbtn ${loop ? "on" : ""}`} onClick={() => setLoop(!loop)} aria-pressed={loop}>
            <span className="label" style={{ color: "inherit" }}>LOOP</span>
          </button>
          <Lcd style={{ width: 176, height: 44, display: "flex", alignItems: "center", padding: "0 12px", gap: 8 }}>
            <SevenSeg text={pos.toFixed(3)} h={26} gap={5} />
            <span className="micro" style={{ marginLeft: "auto" }}>s</span>
          </Lcd>
          <div style={{ display: "grid", gap: 6 }}>
            <span className="label">LEVEL MATCH</span>
            <span className="row" style={{ gap: 8 }}>
              <Toggle on={match} onChange={setMatch} label="level match" />
              <span className="meta hi">{mA && mB ? `RMS ${fmt(Math.min(mA.rms, mB.rms))} dB` : "—"}</span>
            </span>
          </div>
          <div className="meters">
            {[["A", mA], ["B", mB]].map(([lab, m]) => (
              <div key={lab as string}>
                <span className={`label ${lab === "A" ? "lo" : "ac"}`}>{lab as string}</span>
                <span className="cells">
                  {Array.from({ length: 32 }, (_, k) => {
                    const v = m ? Math.max(0, 1 + (m as Metrics).rms / 48) : 0;
                    const on = k / 32 < v;
                    return <i key={k} className={on ? (lab === "A" ? "a" : k > 25 ? "hot" : "b") : ""} />;
                  })}
                </span>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gap: 6, justifyItems: "end" }}>
            <span className="meta">PEAK {mA ? fmt(mA.peak) : "—"}</span>
            <span className="meta ac">PEAK {mB ? fmt(mB.peak) : "—"}</span>
          </div>
        </Panel>

        <Panel title="WAVEFORM" idx="1" tone="bg1" className="area-wave" aside={
          <span className="row" style={{ gap: 10 }}>
            <span className="micro">{pairJob ? `+ ${pairJob.path === "mpc" ? "B" : "A"} ${pairJob.sample_name}` : "no pair render"}</span>
            <Seg h={18} size={10} style={{ width: 120 }} value={pairOn ? "pair" : "solo"} onChange={(v) => setPairOn(v === "pair" && !!pairJob)} items={[{ value: "solo", label: "SOLO" }, { value: "pair", label: "PAIR" }]} />
          </span>
        }>
          <Lcd style={{ padding: 4 }}>
            <Waveform a={pkA} b={pkB} height={144} head={dur ? pos / dur : null} onSeek={(f) => player.seek(f * dur)} />
          </Lcd>
          <div className="ruler">
            {Array.from({ length: 9 }, (_, k) => (
              <span key={k} className="micro">{((dur * k) / 8).toFixed(2)}</span>
            ))}
          </div>
          {err && <div className="err-line">{err}</div>}
        </Panel>

        {(["A", "B"] as const).map((s, i) => (
          <Panel key={s} title={`SPECTRUM ${s} · ${s === "A" ? "SOURCE" : "RENDER"}`} idx={String(i + 2)} tone="bg1" className={`area-s${s}`} aside={<span className="micro">{s === "A" ? `${+((srcRate ?? 0) / 1000).toFixed(2)}k in` : `${rateB === "native" ? "native" : `${(rateB as number) / 1000}k`} out`}</span>}>
            {job ? (
              <div className="spec">
                <div className="axis">
                  {[24, 20, 16, 12, 8, 4, 0].map((f) => {
                    const fmax = s === "A" ? (srcRate ?? 48000) / 2000 : fmaxB / 1000;
                    return f <= fmax ? (
                      <span key={f} className="micro" style={{ top: `${(1 - f / fmax) * 100}%` }}>{f}k</span>
                    ) : null;
                  })}
                </div>
                <Lcd style={{ position: "relative", flex: 1 }}>
                  <img src={s === "A" ? urls.sampleSpectro(job.sample_id) : urls.jobPng(job.id)} alt={`spectrogram ${s}`} />
                  {s === "B" && job.path === "sp" && rateB !== "native" && (
                    <>
                      <i className="nyq" style={{ top: `${(1 - 13020.8 / fmaxB) * 100}%` }} />
                      <span className="nyq-l micro achi" style={{ top: `calc(${(1 - 13020.8 / fmaxB) * 100}% - 16px)` }}>13.02k&nbsp;&nbsp;NYQ 26.04k</span>
                      <span className="img-l label ac" style={{ height: `${(1 - 13020.8 / fmaxB) * 100}%` }}>ZOH IMAGES</span>
                    </>
                  )}
                </Lcd>
              </div>
            ) : (
              <div className="empty">Render something from CHAIN, then compare it here.</div>
            )}
          </Panel>
        ))}

        <Panel title="DELTA" idx="Δ" className="area-d">
          <table className="delta">
            <thead>
              <tr>
                <th />
                <th className="lo">A</th>
                <th className="ac">B</th>
                <th>Δ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r[0]}>
                  <td className="label">{r[0]}</td>
                  <td className="lo">{r[1]}</td>
                  <td className="achi">{r[2]}</td>
                  <td className="hi">{r[3]}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="rule" />
          <span className="label lo">PARAMS.JSON</span>
          <Lcd className="json">
            {json.map((l, i) => (
              <div key={i} className={l.includes("HYP") ? "lo" : ""}>{l}</div>
            ))}
          </Lcd>
          <span className="label lo">FILES</span>
          {job && (
            <div className="files">
              <a href={urls.jobWav(job.id)} download={job.output_name ?? undefined}>{short(stem, ".wav")}</a>
              <span className="micro">{job.result_sha256?.slice(0, 4)}</span>
              <a href={urls.jobPng(job.id)} download>{short(stem, "__spectro.png")}</a>
              <span className="micro">png</span>
              <a href={urls.jobJson(job.id)} download>{short(stem, "__params.json")}</a>
              <span className="micro">json</span>
            </div>
          )}
          <a
            className="btn primary"
            style={{ height: 36, marginTop: "auto", display: "block" }}
            href={job ? urls.jobWav(job.id) : undefined}
            download={job?.output_name ?? undefined}
            draggable
            onDragStart={(e) => {
              if (!job) return;
              // Chrome: drag straight to Finder / a DAW as a file
              e.dataTransfer.setData("DownloadURL", `audio/wav:${job.output_name}:${location.origin}${urls.jobWav(job.id)}`);
            }}
          >
            <span>DRAG OUT</span>
          </a>
        </Panel>
      </div>
    </Frame>
  );
}

function signed(v: number, d = 1) {
  if (!Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(d)}`;
}
function short(stem: string, suffix: string) {
  const s = stem + suffix;
  return s.length > 27 ? `${s.slice(0, 11)}…${s.slice(-15)}` : s;
}
