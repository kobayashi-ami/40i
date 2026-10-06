// design.md §6.2 CHAIN — path A (10 stages), path B (5 stages), RENDER inspector.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Frame } from "../components/Frame";
import { Btn, ChainV, Field, Lcd, Panel, Seg, SevenSeg, Slider, Tag, Toggle } from "../components/ui";
import { api, type ParamSpec, type Params, type Preset, type Route, type Sample } from "../lib/api";
import { useLive } from "../lib/live";
import { getPath, outputName, paramHash, PRESET_FOR, setPath, tuneRatio, tuneStr } from "../lib/format";
import { navigate, useLocation } from "../lib/router";
import "./screens.css";

type Schema = Record<string, ParamSpec>;

function Stage(props: {
  n: string;
  name: string;
  cap?: string;
  jp?: string;
  on?: boolean;
  onToggle?: (v: boolean) => void;
  sel?: boolean;
  h?: number;
  children?: ReactNode;
  compact?: boolean;
}) {
  const on = props.on ?? true;
  return (
    <div className={`stage ${props.sel ? "sel" : ""} ${on ? "" : "off"} ${props.compact ? "compact" : ""}`} style={{ minHeight: props.h }}>
      <i className="node" />
      <div className="stage-in metal-bg2">
        <div className="stage-head">
          <span className="mono n">{props.n}</span>
          <span className="nm">{props.name}</span>
          {props.onToggle && <Toggle on={on} onChange={props.onToggle} label={`${props.name} on/off`} />}
          {props.jp ? <span className="jp cap">{props.jp}</span> : props.cap ? <span className="micro cap">{props.cap}</span> : null}
        </div>
        <div className="stage-params">{props.children}</div>
      </div>
    </div>
  );
}

export default function Chain() {
  const { query } = useLocation();
  const { snap } = useLive();
  const [samples, setSamples] = useState<Sample[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [schema, setSchema] = useState<Schema>({});
  const [presetId, setPresetId] = useState<Record<Route, string | null>>({ sp: null, mpc: null });
  const [params, setParams] = useState<Record<Route, Params | null>>({ sp: null, mpc: null });
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.samples().then(setSamples).catch(() => {});
    api.presets().then(setPresets).catch((e) => setError(e.message));
    api.schema().then(setSchema).catch(() => {});
  }, []);

  const sample = samples.find((s) => s.id === query.get("s")) ?? samples[0] ?? null;
  const route: Route = sample?.route ?? "sp";
  const latest = (name: string) =>
    presets.filter((p) => p.name === name).sort((a, b) => b.version - a.version)[0] ?? null;

  // choose default presets when the sample changes
  const lastSample = useRef<string | null>(null);
  useEffect(() => {
    if (!presets.length || !sample || lastSample.current === sample.id) return;
    lastSample.current = sample.id;
    const sp = latest(PRESET_FOR[sample.role ?? "other"]) ?? latest("sp_snare_hard");
    const mpc = latest(PRESET_FOR.mpc);
    setPresetId({ sp: sp?.id ?? null, mpc: mpc?.id ?? null });
    setParams({ sp: sp ? structuredClone(sp.params) : null, mpc: mpc ? structuredClone(mpc.params) : null });
  }, [presets, sample?.id]);

  const pA = params.sp;
  const pB = params.mpc;
  const presetOf = (r: Route) => presets.find((p) => p.id === presetId[r]) ?? null;
  const active = presetOf(route);
  const activeParams = params[route];
  const edited = active && activeParams ? paramHash(active.params) !== paramHash(activeParams) : false;
  const st = (r: Route) => (s: string) => schema[`${r}.${s}`]?.status ?? null;
  const sA = st("sp");
  const sB = st("mpc");
  const set = (r: Route, path: string, v: unknown) =>
    setParams((p) => ({ ...p, [r]: p[r] ? setPath(p[r]!, path, v) : p[r] }));
  const setA = (path: string, v: unknown) => set("sp", path, v);
  const setB = (path: string, v: unknown) => set("mpc", path, v);
  const g = (p: Params | null, path: string) => (p ? getPath(p, path) : undefined);

  const job = snap?.jobs.find((j) => j.id === jobId) ?? null;
  const rendering = !!job && (job.state === "queued" || job.state === "running");
  const tune = (g(activeParams, "tune.st") as number) ?? 0;
  const tuneMin = route === "sp" ? -8 : -12;
  const tuneMax = route === "sp" ? 7 : 6;
  const table = (g(pA, "tune.table") as string) ?? "measured";
  const ratio = route === "sp" ? tuneRatio(tune, table) : 2 ** (tune / 12);
  const outName = sample && active ? outputName(sample.name, active.name, tune) : "—";
  const rate = g(activeParams, "output.rate");

  async function render() {
    if (!sample || !active || !activeParams) return;
    setError(null);
    try {
      const r = await api.render(sample.id, active.id, activeParams);
      setJobId(r.id);
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function save(fork: boolean) {
    if (!active || !activeParams) return;
    const name = fork ? window.prompt("New preset name (a-z, 0-9, _ -)", `${active.name}_fork`) : active.name;
    if (!name) return;
    try {
      const p = await api.savePreset(name, route, activeParams);
      setPresets((all) => [...all, p]);
      setPresetId((ids) => ({ ...ids, [route]: p.id }));
    } catch (e: any) {
      setError(e.message);
    }
  }

  const choosePreset = (r: Route, id: string) => {
    const p = presets.find((x) => x.id === id);
    if (!p) return;
    setPresetId((ids) => ({ ...ids, [r]: id }));
    setParams((ps) => ({ ...ps, [r]: structuredClone(p.params) }));
  };

  // step pattern of the read pointer (first 10 increments)
  const steps = useMemo(() => {
    const r = tuneRatio(tune, table);
    return Array.from({ length: 8 }, (_, n) => Math.floor((n + 1) * r) - Math.floor(n * r)).join(" ");
  }, [tune, table]);

  const capSpeed = (g(pA, "capture.speed") as number) ?? 1;
  const capOn = !!g(pA, "capture.on");
  const shift = 12 * Math.log2(capSpeed);
  const analogRoute = g(pA, "analog.route") as string;
  const ch = g(pA, "analog.ch") as number;
  const filterOn = analogRoute !== "tip" && ch < 7;

  return (
    <Frame active={1} context={sample ? `${sample.name} → ${route === "sp" ? "A" : "B"} · preset ${active?.name ?? "—"} v${active?.version ?? ""}` : "no sample"}>
      <div className="chain">
        {/* ---------------------------------------------------- A: DRUM PATH */}
        <Panel tone="bg1" screws={false} bodyStyle={{ padding: "0 14px 14px" }}>
          <div className="path-head">
            <span className="stencil path-letter ac">A</span>
            <span className="path-name">DRUM PATH</span>
            <Tag s="VER" />
            <span className="micro" style={{ marginLeft: "auto" }}>
              12-BIT LINEAR · 26 041.67 Hz · DROP-SAMPLE
            </span>
          </div>
          <div className="rule" />
          {route !== "sp" && <div className="micro standby">STANDBY — sample routed to B</div>}
          {pA ? (
            <div className="stages">
              <ChainV height={2000} style={{ position: "absolute", left: 8, top: 0 }} />
              <Stage n="01" name="ROLE" cap="→ preset">
                <Field label="ROLE" style={{ gridColumn: "span 2" }}>
                  <Seg h={20} value={(g(pA, "role") as string) ?? "other"} onChange={(v) => setA("role", v)} items={["kick", "snare", "hat", "perc", "other"].map((r) => ({ value: r, label: r === "kick" ? "KCK" : r === "snare" ? "SNR" : r === "perc" ? "PRC" : r === "other" ? "OTH" : "HAT" }))} />
                </Field>
                <Field label="PRESET" style={{ gridColumn: "span 2" }}>
                  <select className="pick" value={presetId.sp ?? ""} onChange={(e) => choosePreset("sp", e.target.value)} aria-label="drum preset">
                    {presets.filter((p) => p.path === "sp").map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} v{p.version}
                      </option>
                    ))}
                  </select>
                </Field>
              </Stage>
              <Stage n="02" name="PRE-EQ" jp="ガン突き" on={g(pA, "pre_eq.on")} onToggle={(v) => setA("pre_eq.on", v)}>
                <Field label="TYPE" tag={sA("pre_eq.type")}>
                  <Seg h={20} value={g(pA, "pre_eq.type")} onChange={(v) => setA("pre_eq.type", v)} items={[{ value: "ls", label: "LS" }, { value: "pk", label: "PK" }, { value: "hs", label: "HS" }]} />
                </Field>
                <Field label="FREQ" val={fmtHz(g(pA, "pre_eq.freq"))}>
                  <Slider label="pre-eq freq" log min={20} max={16000} value={g(pA, "pre_eq.freq")} onChange={(v) => setA("pre_eq.freq", Math.round(v))} />
                </Field>
                <Field label="GAIN" val={fmtDb(g(pA, "pre_eq.gain_db"))}>
                  <Slider label="pre-eq gain" bipolar min={-24} max={24} step={0.5} value={g(pA, "pre_eq.gain_db")} onChange={(v) => setA("pre_eq.gain_db", v)} />
                </Field>
                <Field label="Q" val={(+g(pA, "pre_eq.q")).toFixed(2)}>
                  <Slider label="pre-eq q" log min={0.1} max={10} value={g(pA, "pre_eq.q")} onChange={(v) => setA("pre_eq.q", +v.toFixed(2))} />
                </Field>
              </Stage>
              <Stage n="03" name="DRIVE" jp="ちょい歪み" on={g(pA, "drive.on")} onToggle={(v) => setA("drive.on", v)}>
                <Field label="IN" val={fmtDb(g(pA, "drive.in_db"))}>
                  <Slider label="drive in" bipolar min={-24} max={36} step={0.5} value={g(pA, "drive.in_db")} onChange={(v) => setA("drive.in_db", v)} />
                </Field>
                <Field label="CURVE" tag={sA("drive.curve")}>
                  <Seg h={20} size={10} value={g(pA, "drive.curve")} onChange={(v) => setA("drive.curve", v)} items={[{ value: "tanh", label: "TANH" }, { value: "atan", label: "ATAN" }, { value: "cubic", label: "CUB" }]} />
                </Field>
                <Field label="MIX" val={`${Math.round(g(pA, "drive.mix") * 100)}%`}>
                  <Slider label="drive mix" min={0} max={1} step={0.01} value={g(pA, "drive.mix")} onChange={(v) => setA("drive.mix", v)} />
                </Field>
                <Field label="OUT" val={fmtDb(g(pA, "drive.out_db"))}>
                  <Slider label="drive out" bipolar min={-24} max={24} step={0.5} value={g(pA, "drive.out_db")} onChange={(v) => setA("drive.out_db", v)} />
                </Field>
              </Stage>
              <Stage n="04" name="CAPTURE" cap="pre-speed" on={capOn} onToggle={(v) => setA("capture.on", v)}>
                <Field label="SPEED">
                  <Seg h={20} mono size={10} value={Math.abs(capSpeed - 1) < 1e-6 ? 1 : Math.abs(capSpeed - 1.35) < 1e-3 ? 1.35 : -1} onChange={(v) => v > 0 && setA("capture.speed", v)} items={[{ value: 1, label: "×1" }, { value: 1.35, label: "45" }, { value: -1, label: "USR" }]} />
                </Field>
                <Lcd style={{ height: 36, display: "flex", alignItems: "center", padding: "0 10px" }}>
                  <SevenSeg text={capSpeed.toFixed(3)} h={20} gap={4} />
                </Lcd>
                <Field label="SHIFT">
                  <span className="v">{shift >= 0 ? "+" : ""}{shift.toFixed(2)} st</span>
                </Field>
                <Field label="LOCK TUNE">
                  <Toggle label="lock tune to capture" on={capOn && Math.round(-shift) === tune && tune !== 0} onChange={(v) => v && setA("tune.st", Math.max(-8, Math.round(-shift)))} />
                </Field>
              </Stage>
              <Stage n="05" name="ADC" cap="AA·SRC·12b·clip">
                <Field label="AA FC" tag={sA("adc.aa_fc")} val={fmtHz(g(pA, "adc.aa_fc"))} dim={g(pA, "adc.aa") === "off"}>
                  <Slider label="aa cutoff" min={6000} max={13020} step={10} dim={g(pA, "adc.aa") === "off"} value={g(pA, "adc.aa_fc")} onChange={(v) => setA("adc.aa_fc", v)} />
                </Field>
                <Field label="AA" tag={sA("adc.aa")}>
                  <Seg h={20} size={10} value={g(pA, "adc.aa")} onChange={(v) => setA("adc.aa", v)} items={[{ value: "ellip4", label: "ELL4" }, { value: "butter4", label: "BUT4" }, { value: "off", label: "OFF" }]} />
                </Field>
                <Field label="RATE" tag={sA("adc.native_sr")}>
                  <Seg h={20} mono size={10} value={g(pA, "adc.native_sr")} onChange={(v) => setA("adc.native_sr", v)} items={[{ value: "625000/24", label: "26041.67" }, { value: "26040", label: "26040" }]} />
                </Field>
                <Field label="BITS" tag={sA("adc.bits")}>
                  <span className="v">12 LIN</span>
                </Field>
                <div className="sub">
                  <span className="label lo">DITHER</span>
                  <Seg h={17} size={10} style={{ width: 90 }} value={g(pA, "adc.dither")} onChange={(v) => setA("adc.dither", v)} items={[{ value: "off", label: "OFF" }, { value: "tpdf", label: "TPDF" }]} />
                  <span className="label lo">CLIP</span>
                  <span className="meta">hard ±2048</span>
                  <span className="label lo">LEVELS</span>
                  <span className="meta">≤ 4096</span>
                </div>
              </Stage>
              <Stage n="06" name="TUNE" cap="drop-sample" sel={route === "sp"}>
                <Lcd style={{ height: 60, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <SevenSeg text={tuneStr(g(pA, "tune.st"))} h={44} />
                </Lcd>
                <Field label="RATIO" style={{ gridColumn: "span 2" }}>
                  <span className="mono achi" style={{ fontSize: 12 }}>
                    {table === "measured" ? "MEAS" : "ET"} ×{tuneRatio(g(pA, "tune.st"), table).toFixed(6)}&nbsp;&nbsp;
                    {(1200 * Math.log2(tuneRatio(g(pA, "tune.st"), table))).toFixed(1)}¢
                  </span>
                  <span className="micro">
                    ET ×{(2 ** (g(pA, "tune.st") / 12)).toFixed(6)} · step {steps}
                  </span>
                </Field>
                <Field label="TABLE" tag={sA("tune.table")}>
                  <Seg h={20} value={table} onChange={(v) => setA("tune.table", v)} items={[{ value: "equal_tempered", label: "ET" }, { value: "measured", label: "MEAS" }]} />
                  <span className="micro">range -8 … +7</span>
                </Field>
              </Stage>
              <Stage n="07" name="VOL ENV" cap="8-bit steps" on={g(pA, "vol_env.on")} onToggle={(v) => setA("vol_env.on", v)} compact>
                <Field label="DECAY" tag={sA("vol_env.decay_s")} val={`${(+g(pA, "vol_env.decay_s")).toFixed(2)} s`} dim={!g(pA, "vol_env.on")}>
                  <Slider label="env decay" log min={0.01} max={10} dim={!g(pA, "vol_env.on")} value={g(pA, "vol_env.decay_s")} onChange={(v) => setA("vol_env.decay_s", +v.toFixed(3))} />
                </Field>
                <Field label="STEPS" val="256" dim={!g(pA, "vol_env.on")} />
              </Stage>
              <Stage n="08" name="DAC" cap="zero-order hold" compact>
                <Field label="HOLD" tag={sA("dac.hold")}>
                  <Seg h={20} value={g(pA, "dac.hold")} onChange={(v) => setA("dac.hold", v)} items={[{ value: "zoh", label: "ZOH" }, { value: "linear", label: "LIN" }]} />
                </Field>
                <Field label="RECON" tag="HYP" val="OFF" dim>
                  <span className="micro">none on the box · see OUTPUT SRC</span>
                </Field>
              </Stage>
              <Stage n="09" name="ANALOG" cap="route · channel">
                <Field label="ROUTE" tag={sA("analog.route")} style={{ gridColumn: "span 2" }}>
                  <Seg h={20} size={10} value={analogRoute} onChange={(v) => setA("analog.route", v)} items={[{ value: "ring", label: "RING" }, { value: "tip", label: "TIP · THRU" }, { value: "mix", label: "MIX" }]} />
                </Field>
                <Field label="CH" style={{ gridColumn: "span 2" }}>
                  <Seg h={20} mono size={10} value={ch} onChange={(v) => setA("analog.ch", v)} items={[1, 2, 3, 4, 5, 6, 7, 8].map((c) => ({ value: c, label: String(c) }))} />
                </Field>
                <Field label="FC" tag={sA("analog.fc")} val={filterOn && ch <= 2 ? fmtHz(g(pA, "analog.fc")) : "—"} dim={!filterOn || ch > 2}>
                  <Slider label="ladder cutoff" log min={500} max={20000} dim={!filterOn || ch > 2} value={g(pA, "analog.fc")} onChange={(v) => setA("analog.fc", Math.round(v))} />
                </Field>
                <Field label="ENV" tag={sA("analog.env")} val={filterOn && ch <= 2 ? (+g(pA, "analog.env")).toFixed(2) : "—"} dim={!filterOn || ch > 2}>
                  <Slider label="ladder env" min={0} max={1} step={0.01} dim={!filterOn || ch > 2} value={g(pA, "analog.env")} onChange={(v) => setA("analog.env", v)} />
                </Field>
                <span className="micro" style={{ gridColumn: "span 2", alignSelf: "end" }}>
                  {analogRoute === "tip" ? "tip = unfiltered · owner rig" : ch <= 2 ? "1-2 LADDER (SSM2044 model)" : ch <= 6 ? "3-6 FIXED" : "7-8 THRU"}
                </span>
              </Stage>
              <Stage n="10" name="OUTPUT" cap={`→ ${rate === "native" ? "native" : `${(rate as number) / 1000}k`} · 24-bit`} compact>
                <Field label="RATE" tag={sA("output.rate")} style={{ gridColumn: "span 2" }}>
                  <Seg h={20} mono size={10} value={g(pA, "output.rate")} onChange={(v) => setA("output.rate", v)} items={[{ value: 48000, label: "48000" }, { value: 44100, label: "44100" }, { value: "native", label: "NATIVE" }]} />
                </Field>
                <Field label="SRC" tag={sA("output.src")} style={{ gridColumn: "span 2" }}>
                  <Seg h={20} size={10} value={g(pA, "output.src")} onChange={(v) => setA("output.src", v)} items={[{ value: "keep_zoh", label: "KEEP-ZOH" }, { value: "sinc", label: "SINC" }, { value: "linear", label: "LINEAR" }]} />
                </Field>
              </Stage>
            </div>
          ) : (
            <div className="empty">Loading presets…</div>
          )}
        </Panel>

        {/* ---------------------------------------------------- B: SAMPLE PATH */}
        <Panel tone="bg1" screws={false} bodyStyle={{ padding: "0 12px 12px" }}>
          <div className="path-head">
            <span className={`stencil path-letter ${route === "mpc" ? "ac" : ""}`}>B</span>
            <span className="path-name">SAMPLE PATH</span>
            <span className="micro" style={{ marginLeft: "auto" }}>
              12-BIT NL · 40 kHz
            </span>
          </div>
          <div className="rule" />
          {route !== "mpc" && <div className="micro standby">STANDBY — sample routed to A</div>}
          {pB ? (
            <div className="stages b">
              <ChainV height={2000} color="#22292f" style={{ position: "absolute", left: 6, top: 0 }} />
              <Stage n="01" name="INPUT" cap="pre-emph" on={g(pB, "input.emph")} onToggle={(v) => setB("input.emph", v)}>
                <Field label="GAIN" tag={sB("input.gain_db")} val={fmtDb(g(pB, "input.gain_db"))}>
                  <Slider label="input gain" bipolar min={-24} max={24} step={0.5} value={g(pB, "input.gain_db")} onChange={(v) => setB("input.gain_db", v)} />
                </Field>
                <Field label="EMPH" tag={sB("input.emph_db")} val={`+${g(pB, "input.emph_db")} dB`} dim={!g(pB, "input.emph")}>
                  <Slider label="pre-emphasis" min={0} max={12} step={0.5} dim={!g(pB, "input.emph")} value={g(pB, "input.emph_db")} onChange={(v) => setB("input.emph_db", v)} />
                </Field>
              </Stage>
              <Stage n="02" name="RESAMPLE" cap="→ 40 kHz">
                <Field label="RATE" tag="VER">
                  <span className="v">40000</span>
                </Field>
                <Field label="BAND" tag={sB("resample.band_hz")} val={fmtHz(g(pB, "resample.band_hz"))}>
                  <Slider label="band" min={10000} max={19999} step={10} value={g(pB, "resample.band_hz")} onChange={(v) => setB("resample.band_hz", v)} />
                </Field>
              </Stage>
              <Stage n="03" name="NL-12 CODEC" cap="16→12nl→16">
                <Field label="CURVE CANDIDATE" tag={sB("codec.curve")} style={{ gridColumn: "1 / -1" }}>
                  <Seg h={26} size={12} value={g(pB, "codec.curve")} onChange={(v) => setB("codec.curve", v)} items={[{ value: "pwl", label: "PWL" }, { value: "grng", label: "GAIN-RNG" }, { value: "mulaw", label: "MU-LAW" }]} />
                </Field>
                <Lcd style={{ height: 60 }}>
                  <CodecCurve curve={g(pB, "codec.curve")} />
                </Lcd>
                <Field label="BLOCK" tag={sB("codec.block")} val={String(g(pB, "codec.block"))} dim={g(pB, "codec.curve") !== "grng"}>
                  <Slider label="gain-ranging block" log min={4} max={1024} dim={g(pB, "codec.curve") !== "grng"} value={g(pB, "codec.block")} onChange={(v) => setB("codec.block", Math.round(v))} />
                  <span className="micro">A/B/C switchable · see docs</span>
                </Field>
              </Stage>
              <Stage n="04" name="TUNE" cap="-12 … +6" sel={route === "mpc"}>
                <Lcd style={{ height: 50, display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <SevenSeg text={tuneStr(g(pB, "tune.st"))} h={36} />
                </Lcd>
                <Field label="INTERP" tag={sB("tune.interp")}>
                  <Seg h={26} size={12} value={g(pB, "tune.interp")} onChange={(v) => setB("tune.interp", v)} items={[{ value: "none", label: "NONE" }, { value: "linear", label: "LINEAR" }]} />
                </Field>
              </Stage>
              <Stage n="05" name="DE-EMPH · DAC" cap="16b → out">
                <Field label="DE-EMPH" tag={sB("input.emph_db")} val={g(pB, "input.emph") ? `-${g(pB, "input.emph_db")} dB` : "OFF"} dim={!g(pB, "input.emph")} />
                <Field label="DAC">
                  <span className="v">16-bit</span>
                </Field>
                <Field label="OUT" style={{ gridColumn: "1 / -1" }}>
                  <Seg h={22} mono size={10} value={g(pB, "output.rate")} onChange={(v) => setB("output.rate", v)} items={[{ value: 48000, label: "48000" }, { value: 44100, label: "44100" }, { value: "native", label: "40000" }]} />
                </Field>
              </Stage>
            </div>
          ) : null}
        </Panel>

        {/* ---------------------------------------------------- RENDER */}
        <Panel title="RENDER" idx="R" bodyStyle={{ overflow: "hidden auto", gap: 10 }}>
          <Field label="PRESET" val={<span className="ac" style={{ fontSize: 10 }}>v{active?.version ?? "—"}{edited ? " · edited" : ""}</span>}>
            <select className="pick big" value={presetId[route] ?? ""} onChange={(e) => choosePreset(route, e.target.value)} aria-label="preset">
              {presets.filter((p) => p.path === route).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} v{p.version}
                </option>
              ))}
            </select>
          </Field>
          <div className="two">
            <Btn h={28} w="100%" size={12} onClick={() => save(false)} disabled={!edited}>
              SAVE
            </Btn>
            <Btn h={28} w="100%" size={12} onClick={() => save(true)}>
              FORK
            </Btn>
          </div>
          <div className="rule" />
          <div className="field-head">
            <span className="label" style={{ fontSize: 12, letterSpacing: "0.25em" }}>
              TUNE
            </span>
            <span className="micro" style={{ marginLeft: "auto" }}>
              semitones
            </span>
          </div>
          <Lcd style={{ height: 112, display: "grid", placeItems: "center", position: "relative" }}>
            <SevenSeg text={tuneStr(tune)} h={92} gap={18} />
            <span className="micro" style={{ position: "absolute", left: 10, bottom: 6 }}>
              {route === "sp" ? "A·06" : "B·04"}
            </span>
            <span className="micro ac" style={{ position: "absolute", right: 10, bottom: 6 }}>
              ×{ratio.toFixed(4)}
            </span>
          </Lcd>
          <div className="quick">
            <Btn h={30} w="100%" title="tune down" onClick={() => set(route, "tune.st", Math.max(tuneMin, tune - 1))}>
              −
            </Btn>
            <Seg
              h={30}
              mono
              size={13}
              value={tune}
              onChange={(v) => set(route, "tune.st", v)}
              items={[-3, -2, -1, 0, 1].map((v) => ({ value: v, label: tuneStr(v) }))}
            />
            <Btn h={30} w="100%" title="tune up" onClick={() => set(route, "tune.st", Math.min(tuneMax, tune + 1))}>
              +
            </Btn>
          </div>
          <div className="rule" />
          <div>
            <div className="label lo" style={{ marginBottom: 10 }}>
              OUTPUT
            </div>
            {splitName(outName).map((part, i, a) => (
              <div key={i} className={`mono ${i === a.length - 1 ? "achi" : "hi"}`} style={{ fontSize: 11, lineHeight: "16px" }}>
                {part}
              </div>
            ))}
            <div className="meta" style={{ marginTop: 8 }}>
              WAV 24-bit · {rate === "native" ? (route === "sp" ? "26.04 kHz" : "40 kHz") : `${(rate as number) / 1000} kHz`}
            </div>
          </div>
          <div>
            <div className="label lo" style={{ marginBottom: 8 }}>
              ATTACH
            </div>
            <div className="attach">
              <Toggle on label="spectrogram png" />
              <span className="label hi">SPECTROGRAM PNG</span>
              <Toggle on label="params json" />
              <span className="label hi">PARAMS JSON</span>
              <Toggle on={rate === "native"} label="native-rate wav" onChange={(v) => set(route, "output.rate", v ? "native" : 48000)} />
              <span className={`label ${rate === "native" ? "hi" : "lo"}`}>NATIVE-RATE WAV</span>
            </div>
          </div>
          <div className="rule" />
          <div>
            <div className="label lo" style={{ marginBottom: 8 }}>
              PARAM HASH
            </div>
            <div className="mono meta" style={{ fontSize: 11.5 }}>
              {activeParams ? paramHash(activeParams) : "—"}
            </div>
            <div className="micro">deterministic · seedless</div>
          </div>
          {error && <div className="err-line">{error}</div>}
          {job?.state === "succeeded" && (
            <button className="linkish" onClick={() => navigate(`/ab?j=${job.id}`)}>
              {job.output_name} → A/B
            </button>
          )}
          {job?.state === "failed" && <div className="err-line">render failed — see JOBS</div>}
          <div style={{ marginTop: "auto" }}>
            <Btn kind={rendering ? "running" : "primary"} h={56} w="100%" size={20} onClick={render} disabled={!sample || !active || rendering}>
              {rendering ? "RENDERING" : "RENDER"}
            </Btn>
          </div>
        </Panel>
      </div>
    </Frame>
  );
}

function fmtHz(v: number | undefined) {
  if (v == null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10000 ? 1 : 2)}k` : `${Math.round(v)}`;
}
function fmtDb(v: number | undefined) {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${(+v).toFixed(1)} dB`;
}
function splitName(n: string): string[] {
  const parts = n.split("__");
  return parts.map((p, i) => (i === 0 ? p : `__${p}`));
}

function CodecCurve({ curve }: { curve: string }) {
  const pts: string[] = [];
  for (let i = 0; i <= 80; i++) {
    const x = -1 + (2 * i) / 80;
    const a = Math.abs(x);
    let y: number;
    if (curve === "mulaw") y = Math.log1p(255 * a) / Math.log1p(255);
    else if (curve === "pwl") y = a < 1 / 128 ? a * 16 : Math.min(1, (Math.log2(a * 128) + 1) / 8);
    else y = a; // gain ranging keeps the shape linear, only the step changes per block
    pts.push(`${(i / 80) * 100},${50 - Math.sign(x) * y * 44}`);
  }
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: "100%", height: "100%", display: "block" }} aria-label={`${curve} transfer curve`}>
      <line x1="0" y1="50" x2="100" y2="50" stroke="#1a232c" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <polyline points={pts.join(" ")} fill="none" stroke="#6c97be" strokeWidth="1.3" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
