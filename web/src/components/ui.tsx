// design.md §5 building blocks.
import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import type { JobState, Stage } from "../lib/api";
import "./ui.css";

export function Screw({ pos, a = 20 }: { pos: "tr" | "bl"; a?: number }) {
  return <i className={`screw ${pos}`} style={{ ["--a" as any]: `${a}deg` }} aria-hidden />;
}

export function Panel(props: {
  title?: ReactNode;
  idx?: string;
  aside?: ReactNode;
  tone?: "bg1" | "bg2" | "bg3";
  screws?: boolean;
  c?: number;
  className?: string;
  style?: CSSProperties;
  bodyStyle?: CSSProperties;
  bodyClass?: string;
  children?: ReactNode;
}) {
  const { title, idx, aside, tone = "bg2", screws = true, c = 10 } = props;
  return (
    <section className={`panel ${props.className ?? ""}`} style={{ ["--c" as any]: `${c}px`, ...props.style }}>
      <div className={`panel-in metal-${tone}`}>
        {title !== undefined && (
          <>
            <div className="panel-head">
              {idx && <span className="idx">{idx}</span>}
              <span className="ttl">{title}</span>
              {aside && <span className="aside">{aside}</span>}
            </div>
            <div className="rule panel-rule" />
          </>
        )}
        <div className={`panel-body ${props.bodyClass ?? ""}`} style={props.bodyStyle}>
          {props.children}
        </div>
        {screws && (
          <>
            <Screw pos="tr" a={23} />
            <Screw pos="bl" a={62} />
          </>
        )}
      </div>
    </section>
  );
}

export const Led = ({ on, sm }: { on: boolean; sm?: boolean }) => <i className={`led ${on ? "on" : ""} ${sm ? "sm" : ""}`} />;

export const Tag = ({ s }: { s?: "VER" | "HYP" | null }) => (s ? <span className={`tag ${s}`}>{s}</span> : null);

export function Btn(props: {
  kind?: "normal" | "primary" | "running" | "failed";
  disabled?: boolean;
  onClick?: () => void;
  h?: number;
  w?: number | string;
  size?: number;
  children: ReactNode;
  title?: string;
}) {
  const { kind = "normal", h = 36, w, size } = props;
  return (
    <button
      className={`btn ${kind}`}
      disabled={props.disabled}
      onClick={props.onClick}
      title={props.title}
      style={{ height: h, width: w }}
    >
      <span style={size ? { fontSize: size } : undefined}>{props.children}</span>
    </button>
  );
}

export function Seg<T extends string | number>(props: {
  items: { value: T; label: ReactNode }[];
  value: T | null;
  onChange?: (v: T) => void;
  h?: number;
  mono?: boolean;
  dim?: boolean;
  size?: number;
  style?: CSSProperties;
  label?: string;
}) {
  const { h = 22 } = props;
  return (
    <div
      className={`seg ${props.mono ? "mono" : ""} ${props.dim ? "dim" : ""}`}
      style={{ height: h, ...props.style }}
      role="group"
      aria-label={props.label}
    >
      {props.items.map((it) => (
        <button
          key={String(it.value)}
          aria-pressed={it.value === props.value}
          onClick={() => props.onChange?.(it.value)}
          style={props.size ? { fontSize: props.size } : undefined}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

export function Field(props: { label: string; tag?: "VER" | "HYP" | null; val?: ReactNode; dim?: boolean; jp?: string; children?: ReactNode; style?: CSSProperties }) {
  return (
    <div className={`field ${props.dim ? "dim" : ""}`} style={props.style}>
      <div className="field-head">
        <span className="label">{props.label}</span>
        {props.jp && <span className="jp">{props.jp}</span>}
        <Tag s={props.tag} />
        {props.val !== undefined && <span className="val">{props.val}</span>}
      </div>
      {props.children}
    </div>
  );
}

export function Slider(props: {
  value: number;
  min: number;
  max: number;
  step?: number;
  log?: boolean;
  bipolar?: boolean;
  dim?: boolean;
  onChange: (v: number) => void;
  label: string;
}) {
  const { min, max, value, step = 0, log = false } = props;
  const ref = useRef<HTMLDivElement>(null);
  const toPos = (v: number) => (log ? Math.log(v / min) / Math.log(max / min) : (v - min) / (max - min));
  const fromPos = (p: number) => {
    let v = log ? min * Math.pow(max / min, p) : min + p * (max - min);
    if (step) v = Math.round(v / step) * step;
    return Math.min(max, Math.max(min, +v.toFixed(6)));
  };
  const pos = Math.min(1, Math.max(0, toPos(value)));
  const zero = props.bipolar ? toPos(0) : 0;
  const set = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    props.onChange(fromPos(Math.min(1, Math.max(0, (clientX - r.left - 2) / (r.width - 4)))));
  };
  const nudge = (dir: number) => props.onChange(fromPos(Math.min(1, Math.max(0, pos + dir * 0.01))));
  return (
    <div
      ref={ref}
      className={`slider ${props.dim ? "dim" : ""}`}
      role="slider"
      tabIndex={0}
      aria-label={props.label}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuenow={value}
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        set(e.clientX);
      }}
      onPointerMove={(e) => e.buttons && set(e.clientX)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowUp") nudge(1);
        if (e.key === "ArrowLeft" || e.key === "ArrowDown") nudge(-1);
      }}
    >
      <div className="track" />
      <div className="fill" style={{ left: `calc(2px + ${Math.min(pos, zero) * 100}% - ${Math.min(pos, zero) * 4}px)`, width: `calc(${Math.abs(pos - zero) * 100}% - ${Math.abs(pos - zero) * 4}px)` }} />
      <div className="ticks" />
      <div className="thumb" style={{ left: `calc(2px + ${pos * 100}% - ${pos * 4}px)` }} />
    </div>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange?: (v: boolean) => void; label: string }) {
  return (
    <button className="toggle" aria-pressed={on} aria-label={label} onClick={() => onChange?.(!on)}>
      <i className="cap" />
      <i className="bar" />
    </button>
  );
}

export const CHIP: Record<JobState | "lost" | "idle", string> = {
  idle: "IDLE",
  running: "RUN",
  queued: "QUE",
  succeeded: "OK",
  failed: "FAIL",
  cancelled: "CXL",
  lost: "LOST",
};
export const Chip = ({ state }: { state: JobState | "lost" | "idle" }) => <span className={`chip ${CHIP[state]}`}>{CHIP[state]}</span>;

export function SegProgress({ stages, dim }: { stages: Stage[]; dim?: boolean }) {
  return (
    <div className={`sprog ${dim ? "dim" : ""}`}>
      {stages.map((s) =>
        s.state === "succeeded" ? (
          <i key={s.ordinal} className="done" />
        ) : s.state === "failed" ? (
          <i key={s.ordinal} className="fail" />
        ) : s.state === "running" ? (
          <i key={s.ordinal}>
            <b style={{ width: `${Math.round(s.progress * 100)}%` }} />
          </i>
        ) : (
          <i key={s.ordinal} />
        ),
      )}
    </div>
  );
}

export function Lcd({ children, style, className }: { children?: ReactNode; style?: CSSProperties; className?: string }) {
  return (
    <div className={`lcd ${className ?? ""}`} style={style}>
      {children}
    </div>
  );
}

// 5.10 7-segment, drawn (never a font). Unlit segments are always drawn in --seg-off.
const SEGS: Record<string, string> = {
  "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc",
  "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "", A: "abcefg", b: "cdefg", C: "adef", c: "deg", d: "bcdeg",
  E: "adefg", F: "aefg", H: "bcefg", L: "def", P: "abefg", r: "eg", t: "defg", U: "bcdef", n: "ceg", o: "cdeg",
  u: "cde", q: "abcfg", Y: "bcdfg", S: "afgcd", "+": "g",
};

export function SevenSeg({ text, h, gap, fail, color }: { text: string; h: number; gap?: number; fail?: boolean; color?: string }) {
  const w = h * 0.52;
  const t = h * 0.115;
  const e = t / 2;
  const g = gap ?? h * 0.2;
  const sk = 0.09;
  const cells: { ch: string; dp: boolean }[] = [];
  for (const ch of text) {
    if (ch === "." && cells.length) cells[cells.length - 1].dp = true;
    else cells.push({ ch, dp: false });
  }
  const on = color ?? (fail ? "var(--fail)" : "var(--ac-hi)");
  let x = 0;
  const polys: ReactNode[] = [];
  cells.forEach((c, ci) => {
    const hh = h / 2;
    const P = (pts: [number, number][]) => pts.map(([px, py]) => `${(x + px + (h - py) * sk).toFixed(2)},${py.toFixed(2)}`).join(" ");
    const segs: Record<string, [number, number][]> = {
      a: [[e, 0], [w - e, 0], [w - t, t], [t, t]],
      d: [[t, h - t], [w - t, h - t], [w - e, h], [e, h]],
      g: [[e, hh], [t, hh - e], [w - t, hh - e], [w - e, hh], [w - t, hh + e], [t, hh + e]],
      f: [[0, e], [t, t], [t, hh - e], [0, hh - e * 0.2]],
      e: [[0, hh + e * 0.2], [t, hh + e], [t, h - t], [0, h - e]],
      b: [[w, e], [w, hh - e * 0.2], [w - t, hh - e], [w - t, t]],
      c: [[w, hh + e * 0.2], [w, h - e], [w - t, h - t], [w - t, hh + e]],
    };
    const lit = SEGS[c.ch] ?? "";
    for (const [name, pts] of Object.entries(segs)) {
      const isOn = lit.includes(name);
      polys.push(<polygon key={`${ci}${name}`} points={P(pts)} fill={isOn ? on : "var(--seg-off)"} filter={isOn ? "url(#segglow)" : undefined} />);
    }
    if (c.ch === "+") {
      polys.push(<polygon key={`${ci}v`} points={P([[w / 2 - e, hh - h * 0.22], [w / 2 + e, hh - h * 0.22], [w / 2 + e, hh + h * 0.22], [w / 2 - e, hh + h * 0.22]])} fill={on} />);
    }
    if (c.dp) {
      const r = t * 0.62;
      polys.push(<circle key={`${ci}dp`} cx={x + w + t + r} cy={h - r} r={r} fill={on} />);
    }
    x += w + g + (c.dp ? t * 2.4 : 0);
  });
  const W = x - g + h * sk + 2;
  return (
    <svg width={W} height={h} viewBox={`0 0 ${W} ${h}`} style={{ display: "block", overflow: "visible" }} aria-label={text} role="img">
      <defs>
        <filter id="segglow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation={h * 0.05} result="b" />
          <feComponentTransfer in="b" result="b2"><feFuncA type="linear" slope="0.45" /></feComponentTransfer>
          <feMerge><feMergeNode in="b2" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {polys}
    </svg>
  );
}

// 5.16 waveform: min/max columns at device-pixel resolution; optional second (B) layer and playhead.
export function Waveform(props: {
  a?: [number, number][] | null;
  b?: [number, number][] | null;
  colorA?: string;
  colorB?: string;
  height: number;
  grid?: boolean;
  head?: number | null; // 0..1
  onSeek?: (frac: number) => void;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth;
    const H = props.height;
    cv.width = Math.round(W * dpr);
    cv.height = Math.round(H * dpr);
    const g = cv.getContext("2d")!;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, W, H);
    if (props.grid !== false) {
      g.fillStyle = "#151a1f";
      for (let i = 1; i < 4; i++) g.fillRect(0, Math.round((H * i) / 4), W, 1);
    }
    const draw = (pk: [number, number][], col: string) => {
      g.fillStyle = col;
      const n = pk.length;
      const mid = H / 2;
      const half = H / 2 - 3;
      for (let x = 0; x < W * dpr; x++) {
        const k = Math.min(n - 1, Math.floor((x / (W * dpr)) * n));
        const [lo, hi] = pk[k];
        g.fillRect(x / dpr, mid - hi * half, 1 / dpr, Math.max(1 / dpr, (hi - lo) * half));
      }
    };
    if (props.a?.length) draw(props.a, props.colorA ?? "#3a4249");
    if (props.b?.length) draw(props.b, props.colorB ?? "#6c97be");
    g.fillStyle = "#232a31";
    g.fillRect(0, H / 2, W, 1);
    if (props.head != null) {
      const px = props.head * W;
      g.fillStyle = "rgba(29,48,68,0.25)";
      g.fillRect(0, 0, px, H);
      g.fillStyle = "#a8c8e4";
      g.fillRect(px - 0.5, 0, 1.5, H);
    }
  });
  return (
    <canvas
      ref={ref}
      style={{ width: "100%", height: props.height, display: "block", cursor: props.onSeek ? "pointer" : undefined, touchAction: "none", ...props.style }}
      onPointerDown={(e) => {
        if (!props.onSeek) return;
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        const r = (e.target as HTMLElement).getBoundingClientRect();
        props.onSeek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)));
      }}
      onPointerMove={(e) => {
        if (!props.onSeek || !e.buttons) return;
        const r = (e.target as HTMLElement).getBoundingClientRect();
        props.onSeek(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)));
      }}
    />
  );
}

// §4 chain: 8×13 rings and 2.4 px bars alternating at a 9 px pitch.
export function ChainV({ height, color = "#2a3138", style }: { height: number; color?: string; style?: CSSProperties }) {
  const links: ReactNode[] = [];
  for (let y = 0, k = 0; y + 13 <= height; y += 9, k++) {
    links.push(
      k % 2 === 0 ? (
        <rect key={k} x={1} y={y} width={8} height={13} rx={4} fill="none" stroke={color} strokeWidth={1.6} />
      ) : (
        <rect key={k} x={3.8} y={y - 1} width={2.4} height={15} fill={color} />
      ),
    );
  }
  return (
    <svg width={10} height={height} style={{ display: "block", ...style }} aria-hidden>
      {links}
    </svg>
  );
}
