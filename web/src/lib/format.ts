import type { Role } from "./api";

export const ROLE_SHORT: Record<Role, string> = { kick: "KCK", snare: "SNR", hat: "HAT", perc: "PRC", other: "OTH" };
export const ROLES: Role[] = ["kick", "snare", "hat", "perc", "other"];

export const sha8 = (h: string) => `${h.slice(0, 4)}…${h.slice(-4)}`;
export const kHz = (sr: number | null) => (sr ? `${+(sr / 1000).toFixed(2)}k` : "—");
export const secs = (s: number | null | undefined, d = 3) => (s == null ? "—" : s.toFixed(d));
export const tuneStr = (t: number | null | undefined) => (t == null ? "—" : t > 0 ? `+${t}` : `${t}`);
export const clock = (iso: string) => {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}.${String(d.getMilliseconds()).padStart(3, "0")}`;
};

// FNV-1a 64-bit over canonical JSON: a short, stable fingerprint of the parameters for display.
export function paramHash(obj: unknown): string {
  const canon = (v: unknown): unknown =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v as object).sort().map((k) => [k, canon((v as any)[k])]))
      : v;
  const s = JSON.stringify(canon(obj));
  let h = 0xcbf29ce484222325n;
  for (let i = 0; i < s.length; i++) {
    h ^= BigInt(s.charCodeAt(i));
    h = (h * 0x100000001b3n) & 0xffffffffffffffffn;
  }
  const hex = h.toString(16).padStart(16, "0");
  return hex.match(/.{4}/g)!.join(" ");
}

export function outputName(sampleName: string, preset: string, tune: number): string {
  const stem = sampleName.replace(/\.[^.]+$/, "").replace(/[^\w.-]+/g, "_");
  return `${stem}__${preset.replace(/_/g, "-")}__tune${tune > 0 ? "+" : ""}${tune}.wav`;
}

export function deepMerge<T extends Record<string, any>>(a: T, b: Record<string, any>): T {
  const out: any = Array.isArray(a) ? [...a] : { ...a };
  for (const [k, v] of Object.entries(b ?? {})) {
    out[k] = v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object" ? deepMerge(out[k], v) : v;
  }
  return out;
}

export function getPath(obj: any, path: string): any {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

export function setPath<T>(obj: T, path: string, value: unknown): T {
  const keys = path.split(".");
  const clone: any = structuredClone(obj);
  let o = clone;
  for (const k of keys.slice(0, -1)) o = o[k] ??= {};
  o[keys[keys.length - 1]] = value;
  return clone;
}

// Default preset per role / route (CLAUDE.md: kick low, snare high).
export const PRESET_FOR: Record<string, string> = {
  kick: "sp_kick_low",
  snare: "sp_snare_hard",
  hat: "sp_hat_air",
  perc: "sp_perc_ch3",
  other: "sp_break_45",
  mpc: "mpc_nl_pwl",
};

// Measured TUNE length ratios (engine/sp.py MEASURED_LENGTH_RATIOS) for the RATIO readout.
export const MEASURED: Record<number, number> = {
  [-1]: 1.05652677103003, [-2]: 1.1215356033380033, [-3]: 1.1834835840896631, [-4]: 1.253228360845465,
  [-5]: 1.3310440397149297, [-6]: 1.4039714929646099, [-7]: 1.5028019735639886, [-8]: 1.5766735700797954,
};
export function tuneRatio(st: number, table: string): number {
  if (st === 0) return 1;
  if (table === "equal_tempered" || st > 0) return 2 ** (st / 12);
  return 1 / MEASURED[st];
}
