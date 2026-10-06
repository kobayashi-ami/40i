// design.md §11: every part from 06_components.png, rendered by the real components, to compare with the sheet.
// Not a screen (no nav entry): open /parts directly.
import { useState } from "react";
import { Btn, ChainV, Chip, Lcd, Led, Panel, Seg, SegProgress, SevenSeg, Slider, Tag, Toggle } from "../components/ui";
import type { Stage } from "../lib/api";
import "./screens.css";

const TOKENS = ["bg0", "bg1", "bg2", "bg3", "bg4", "line", "line2", "metal", "tx-hi", "tx-md", "tx-lo", "tx-xlo", "ac-xlo", "ac-lo", "ac-md", "ac", "ac-hi", "seg-off", "fail-bg", "fail"];
const stages = (done: number, run?: number, fail?: number): Stage[] =>
  Array.from({ length: 10 }, (_, i) => ({
    ordinal: i,
    name: "s",
    state: i < done ? "succeeded" : i === fail ? "failed" : i === run ? "running" : "pending",
    progress: i === run ? 0.6 : i < done ? 1 : 0,
    duration_s: null,
  }));

export default function Parts() {
  const [gain, setGain] = useState(11);
  const [aa, setAa] = useState(12500);
  const [role, setRole] = useState("snr");
  const [rate, setRate] = useState(48000);
  const [on, setOn] = useState(true);
  return (
    <div className="parts">
      <header className="parts-head">
        <span className="stencil" style={{ fontSize: 30 }}>1260</span>
        <span className="title" style={{ color: "var(--tx-md)" }}>COMPONENT SHEET</span>
        <span className="micro" style={{ marginLeft: "auto" }}>live components · not a screen</span>
      </header>
      <div className="parts-grid">
        <Panel title="TOKENS" idx="01">
          <div className="tokens">
            {TOKENS.map((t) => (
              <div key={t}>
                <i style={{ background: `var(--${t})` }} />
                <span className="hi">{t.replace("-", "_")}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="TYPE" idx="02">
          <span className="stencil" style={{ fontSize: 30 }}>1260 STENCIL</span>
          <span className="title">CHAIN&nbsp;&nbsp;DRUM PATH</span>
          <span className="label">FREQ GAIN ORDER HEARTBEAT</span>
          <span className="v">26041.67&nbsp;&nbsp;+11.0 dB&nbsp;&nbsp;a41f…09c2</span>
          <Lcd style={{ width: 150, height: 56, display: "flex", alignItems: "center", gap: 10, padding: "0 12px" }}>
            <SevenSeg text="-2" h={40} />
            <SevenSeg text="1.35" h={24} gap={4} />
          </Lcd>
          <span className="jp">ガン突き　ちょい歪み</span>
        </Panel>
        <Panel title="BUTTON STATES" idx="03">
          <div className="two">
            <Btn h={38} w="100%">SAVE</Btn>
            <Btn h={38} w="100%">FORK</Btn>
            <Btn kind="primary" h={38} w="100%">RENDER</Btn>
            <Btn kind="running" h={38} w="100%">RENDERING</Btn>
            <Btn kind="failed" h={38} w="100%">FAILED</Btn>
            <Btn h={38} w="100%" disabled>RENDER</Btn>
          </div>
          <span className="label lo">CHIPS</span>
          <div className="row" style={{ gap: 8 }}>
            {(["running", "queued", "succeeded", "failed", "cancelled", "lost", "idle"] as const).map((s) => <Chip key={s} state={s} />)}
          </div>
          <span className="label lo">TAGS</span>
          <div className="row"><Tag s="VER" /><span className="meta">sourced</span><Tag s="HYP" /><span className="meta">hypothesis · calibratable</span></div>
        </Panel>
        <Panel title="CONTROLS" idx="04" className="wide">
          <div className="three" style={{ gap: 24 }}>
            <div className="field"><div className="field-head"><span className="label">GAIN</span><span className="val">{gain > 0 ? "+" : ""}{gain.toFixed(1)} dB</span></div><Slider label="gain" bipolar min={-24} max={24} step={0.5} value={gain} onChange={setGain} /></div>
            <div className="field"><div className="field-head"><span className="label">AA FC</span><Tag s="HYP" /><span className="val">{(aa / 1000).toFixed(1)}k</span></div><Slider label="aa" min={6000} max={13020} step={10} value={aa} onChange={setAa} /></div>
            <div className="field dim"><div className="field-head"><span className="label">DECAY</span><span className="val">—</span></div><Slider label="decay" dim min={0} max={1} value={0.5} onChange={() => {}} /></div>
          </div>
          <div className="two" style={{ gap: 24 }}>
            <Seg h={30} value={role} onChange={setRole} items={["kck", "snr", "hat", "prc", "oth"].map((v) => ({ value: v, label: v.toUpperCase() }))} />
            <Seg h={30} mono value={rate} onChange={setRate} items={[{ value: 48000, label: "48000" }, { value: 44100, label: "44100" }, { value: 0, label: "NATIVE" }]} />
          </div>
          <div className="row" style={{ gap: 14 }}>
            <Toggle on={on} onChange={setOn} label="toggle" /><span className="micro">on / bypass</span>
            <Led on /><Led on={false} /><span className="micro">led</span>
          </div>
          <span className="label lo">STAGE PROGRESS</span>
          <div style={{ width: 300, display: "grid", gap: 8 }}>
            <SegProgress stages={stages(5, 5)} />
            <SegProgress stages={stages(4, undefined, 4)} />
            <SegProgress stages={stages(10)} dim />
          </div>
          <span className="label lo">CHAIN</span>
          <ChainV height={120} />
        </Panel>
      </div>
    </div>
  );
}
