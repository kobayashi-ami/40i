// A/B audition with Web Audio: all sources start together and the A/B switch only moves gains, so the
// playback position never jumps (CLAUDE.md: <audio> swapping would lose sync). PAIR adds a second layer
// (the B-path sample) under both sides.

let ctx: AudioContext | null = null;
const cache = new Map<string, Promise<AudioBuffer>>();

export function audioContext(): AudioContext {
  if (!ctx) {
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    ctx = new AC();
    try {
      // iOS: play even with the ring/silent switch on (Safari 17+)
      (navigator as any).audioSession && ((navigator as any).audioSession.type = "playback");
    } catch {
      /* not supported */
    }
  }
  return ctx;
}

export function loadBuffer(url: string): Promise<AudioBuffer> {
  if (!cache.has(url)) {
    cache.set(
      url,
      fetch(url)
        .then((r) => {
          if (!r.ok) throw new Error(`${r.status} ${url}`);
          return r.arrayBuffer();
        })
        .then((ab) => audioContext().decodeAudioData(ab)),
    );
  }
  return cache.get(url)!;
}

export interface Layer {
  a: AudioBuffer;
  b: AudioBuffer;
}

export class ABPlayer {
  side: "A" | "B" = "B";
  loop = true;
  match = false;
  playing = false;
  private layers: Layer[] = [];
  private nodes: { src: AudioBufferSourceNode; gain: GainNode; side: "A" | "B"; norm: number }[] = [];
  private t0 = 0;
  private offset = 0;
  onEnd?: () => void;

  setLayers(layers: Layer[]) {
    const was = this.playing;
    const pos = this.position();
    this.stop(false);
    this.layers = layers;
    this.offset = Math.min(pos, this.duration());
    if (was) this.play(this.offset);
  }

  duration(): number {
    return Math.max(0, ...this.layers.flatMap((l) => [l.a.duration, l.b.duration]));
  }

  position(): number {
    if (!this.playing || !ctx) return this.offset;
    const p = this.offset + (ctx.currentTime - this.t0);
    const d = this.duration() || 1;
    return this.loop ? p % d : Math.min(p, d);
  }

  private gains(side: "A" | "B", norm: number) {
    return (side === this.side ? 1 : 0) * (this.match ? norm : 1);
  }

  async play(at = this.offset) {
    const c = audioContext();
    if (c.state === "suspended") await c.resume();
    this.stop(false);
    const d = this.duration();
    if (!d) return;
    const off = Math.max(0, Math.min(at, d - 0.001));
    const when = c.currentTime + 0.03;
    for (const layer of this.layers) {
      const ra = rms(layer.a);
      const rb = rms(layer.b);
      const ref = Math.min(ra, rb) || 1;
      for (const [side, buf, r] of [["A", layer.a, ra], ["B", layer.b, rb]] as const) {
        const src = c.createBufferSource();
        src.buffer = buf;
        src.loop = this.loop;
        src.loopStart = 0;
        src.loopEnd = d;
        const gain = c.createGain();
        const norm = r ? ref / r : 1;
        gain.gain.value = this.gains(side, norm);
        src.connect(gain).connect(c.destination);
        src.start(when, Math.min(off, buf.duration - 0.0005));
        this.nodes.push({ src, gain, side, norm });
      }
    }
    this.t0 = when;
    this.offset = off;
    this.playing = true;
    if (!this.loop) {
      const first = this.nodes[0]?.src;
      if (first)
        first.onended = () => {
          if (this.playing && this.position() >= d - 0.01) {
            this.stop(false);
            this.offset = 0;
            this.onEnd?.();
          }
        };
    }
  }

  stop(keepPos = true) {
    if (keepPos) this.offset = this.position();
    for (const n of this.nodes) {
      n.src.onended = null;
      try {
        n.src.stop();
      } catch {
        /* not started */
      }
      n.src.disconnect();
    }
    this.nodes = [];
    this.playing = false;
  }

  seek(t: number) {
    if (this.playing) this.play(t);
    else this.offset = Math.max(0, Math.min(t, this.duration()));
  }

  setSide(side: "A" | "B") {
    this.side = side;
    this.applyGains();
  }

  setMatch(on: boolean) {
    this.match = on;
    this.applyGains();
  }

  setLoop(on: boolean) {
    this.loop = on;
    if (this.playing) this.play(this.position());
  }

  private applyGains() {
    if (!ctx) return;
    for (const n of this.nodes) n.gain.gain.setTargetAtTime(this.gains(n.side, n.norm), ctx.currentTime, 0.004); // ~5 ms
  }
}

export function rms(b: AudioBuffer): number {
  const x = b.getChannelData(0);
  let s = 0;
  for (let i = 0; i < x.length; i++) s += x[i] * x[i];
  return Math.sqrt(s / Math.max(1, x.length));
}

export function peaks(b: AudioBuffer, n: number): [number, number][] {
  const x = b.getChannelData(0);
  const out: [number, number][] = [];
  const step = x.length / n;
  for (let k = 0; k < n; k++) {
    let lo = 1;
    let hi = -1;
    const end = Math.min(x.length, Math.floor((k + 1) * step) + 1);
    for (let i = Math.floor(k * step); i < end; i++) {
      if (x[i] < lo) lo = x[i];
      if (x[i] > hi) hi = x[i];
    }
    out.push(lo > hi ? [0, 0] : [lo, hi]);
  }
  return out;
}

// --- metrics for the DELTA table ---------------------------------------------------------------------------

function fftMag(x: Float32Array, n: number): Float64Array {
  const re = new Float64Array(n);
  const im = new Float64Array(n);
  for (let i = 0; i < n && i < x.length; i++) re[i] = x[i] * (0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)));
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    for (let i = 0; i < n; i += len)
      for (let k = 0; k < len / 2; k++) {
        const wr = Math.cos(ang * k);
        const wi = Math.sin(ang * k);
        const ur = re[i + k];
        const ui = im[i + k];
        const vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi;
        const vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr;
        re[i + k] = ur + vr;
        im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr;
        im[i + k + len / 2] = ui - vi;
      }
  }
  const mag = new Float64Array(n / 2);
  for (let i = 0; i < n / 2; i++) mag[i] = re[i] * re[i] + im[i] * im[i];
  return mag;
}

export interface Metrics {
  peak: number;
  rms: number;
  crest: number;
  centroid: number;
  hf: number;
  len: number;
}

const dbv = (v: number) => (v > 0 ? 20 * Math.log10(v) : -Infinity);

export function metrics(b: AudioBuffer): Metrics {
  const x = b.getChannelData(0);
  let pk = 0;
  for (let i = 0; i < x.length; i++) pk = Math.max(pk, Math.abs(x[i]));
  const r = rms(b);
  // average power spectrum over up to 16 frames of 8192
  const n = 8192;
  const frames = Math.max(1, Math.min(16, Math.floor(x.length / n)));
  const hop = frames > 1 ? Math.floor((x.length - n) / (frames - 1)) : 0;
  const acc = new Float64Array(n / 2);
  for (let f = 0; f < frames; f++) {
    const m = fftMag(x.subarray(f * hop, f * hop + n), n);
    for (let i = 0; i < m.length; i++) acc[i] += m[i];
  }
  const binHz = b.sampleRate / n;
  let tot = 0;
  let wsum = 0;
  let hf = 0;
  for (let i = 1; i < acc.length; i++) {
    tot += acc[i];
    wsum += acc[i] * i * binHz;
    if (i * binHz >= 13000) hf += acc[i];
  }
  return {
    peak: dbv(pk),
    rms: dbv(r),
    crest: dbv(pk) - dbv(r),
    centroid: tot ? wsum / tot : 0,
    hf: tot ? 10 * Math.log10(hf / tot + 1e-12) : -Infinity,
    len: b.duration,
  };
}
