// design.md §6.1 LIBRARY
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Frame } from "../components/Frame";
import { Btn, Field, Lcd, Panel, Seg, SevenSeg, Waveform } from "../components/ui";
import { api, type Job, type Role, type Route, type Sample } from "../lib/api";
import { kHz, ROLE_SHORT, ROLES, secs, sha8, tuneStr } from "../lib/format";
import { navigate, useLocation } from "../lib/router";
import "./screens.css";

const PAGE = 14;
type Upload = { name: string; progress: number; state: "up" | "ok" | "dup" | "err"; msg?: string };

function uploadOne(file: File, onProgress: (p: number) => void): Promise<{ created: boolean; error?: string }> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const fd = new FormData();
    fd.append("files", file, file.name);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      try {
        const b = JSON.parse(xhr.responseText);
        if (xhr.status >= 300) resolve({ created: false, error: b.detail ?? xhr.statusText });
        else resolve({ created: b.samples?.[0]?.created ?? false });
      } catch {
        resolve({ created: false, error: xhr.statusText });
      }
    };
    xhr.onerror = () => resolve({ created: false, error: "network error" });
    xhr.open("POST", "/api/samples");
    xhr.send(fd);
  });
}

const peakCache = new Map<string, Promise<[number, number][]>>();
function usePeaks(id: string | null, n: number) {
  const [pk, setPk] = useState<[number, number][] | null>(null);
  useEffect(() => {
    if (!id) return setPk(null);
    const key = `${id}:${n}`;
    if (!peakCache.has(key)) peakCache.set(key, api.peaks(id, n));
    let live = true;
    peakCache.get(key)!.then((p) => live && setPk(p)).catch(() => live && setPk(null));
    return () => {
      live = false;
    };
  }, [id, n]);
  return pk;
}

function MiniWave({ id, sel }: { id: string; sel: boolean }) {
  const pk = usePeaks(id, 60);
  return <Waveform a={null} b={pk} colorB={sel ? "#6c97be" : "#56606a"} height={26} grid={false} />;
}

export default function Library() {
  const { query } = useLocation();
  const [samples, setSamples] = useState<Sample[]>([]);
  const [roleF, setRoleF] = useState<Role | "all">("all");
  const [routeF, setRouteF] = useState<Route | "all">("all");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renders, setRenders] = useState<Job[]>([]);
  const [store, setStore] = useState<{ data_dir: string; bytes: number } | null>(null);
  const [dups, setDups] = useState(0);
  const [hdr, setHdr] = useState<{ channels: number; subtype: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const selId = query.get("s");

  const reload = useCallback(() => {
    api.samples().then(setSamples).catch((e) => setError(String(e.message ?? e)));
    api.store().then(setStore).catch(() => setStore(null));
  }, []);
  useEffect(() => {
    reload();
  }, [reload]);

  const filtered = useMemo(
    () =>
      samples.filter(
        (s) =>
          (roleF === "all" || s.role === roleF) &&
          (routeF === "all" || s.route === routeF) &&
          (!q || s.name.toLowerCase().includes(q.toLowerCase())),
      ),
    [samples, roleF, routeF, q],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE));
  const rows = filtered.slice(page * PAGE, page * PAGE + PAGE);
  const sel = samples.find((s) => s.id === selId) ?? samples[0] ?? null;
  const detailPk = usePeaks(sel?.id ?? null, 300);

  useEffect(() => {
    if (!sel) return setRenders([]);
    api.renders(sel.id).then(setRenders).catch(() => setRenders([]));
  }, [sel?.id, sel?.renders]);
  useEffect(() => {
    setHdr(null);
    if (sel) api.sampleInfo(sel.id).then(setHdr).catch(() => setHdr(null));
  }, [sel?.id]);

  const select = (id: string) => navigate(`/lib?s=${id}`);

  async function addFiles(files: File[]) {
    setError(null);
    const start = uploads.length;
    setUploads((u) => [...u, ...files.map((f) => ({ name: f.name, progress: 0, state: "up" as const }))]);
    for (let i = 0; i < files.length; i++) {
      const res = await uploadOne(files[i], (p) =>
        setUploads((u) => u.map((x, k) => (k === start + i ? { ...x, progress: p } : x))),
      );
      setUploads((u) =>
        u.map((x, k) =>
          k === start + i ? { ...x, progress: 1, state: res.error ? "err" : res.created ? "ok" : "dup", msg: res.error } : x,
        ),
      );
      if (!res.error && !res.created) setDups((d) => d + 1);
    }
    reload();
  }

  async function patch(body: Partial<Pick<Sample, "role" | "route">>) {
    if (!sel) return;
    try {
      const s = await api.patchSample(sel.id, body);
      setSamples((all) => all.map((x) => (x.id === s.id ? { ...x, ...s } : x)));
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function remove() {
    if (!sel) return;
    try {
      await api.deleteSample(sel.id);
      navigate("/lib");
      reload();
    } catch (e: any) {
      setError(e.message);
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: samples.length };
    for (const r of ROLES) c[r] = samples.filter((s) => s.role === r).length;
    return c;
  }, [samples]);
  const total = samples.reduce((a, s) => a + (s.length_s ?? 0), 0);
  const peak = detailPk ? Math.max(...detailPk.map(([lo, hi]) => Math.max(-lo, hi))) : 0;

  return (
    <Frame active={0} context={`${samples.length} samples · ${Math.floor(total / 60)}:${(total % 60).toFixed(2).padStart(5, "0")} total`}>
      <div className="lib">
        <div className="col">
          <Panel title="INTAKE" idx="A">
            <div
              className={`drop ${drag ? "over" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDrag(false);
                addFiles([...e.dataTransfer.files]);
              }}
              onClick={() => fileInput.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === "Enter" && fileInput.current?.click()}
            >
              <i className="tl" />
              <i className="tr" />
              <i className="bl" />
              <i className="br" />
              <span className="stencil">DROP WAV</span>
              <span className="micro">WAV · AIFF · ANY SR · ANY DEPTH</span>
              <input
                ref={fileInput}
                type="file"
                accept="audio/*,.wav,.aif,.aiff,.flac"
                multiple
                hidden
                onChange={(e) => {
                  addFiles([...(e.target.files ?? [])]);
                  e.target.value = "";
                }}
              />
            </div>
            <div className="uploads">
              {uploads.slice(-3).map((u, i) => (
                <div key={i} className={`up ${u.state}`}>
                  <span className="mono nm">{u.name}</span>
                  <span className="bar">
                    <b style={{ width: `${u.progress * 100}%` }} />
                  </span>
                  <span className="mono st">
                    {u.state === "up" ? `${Math.round(u.progress * 100)}%` : u.state === "ok" ? "SHA OK" : u.state === "dup" ? "DUP" : "ERR"}
                  </span>
                </div>
              ))}
              {error && <div className="err-line">{error}</div>}
            </div>
          </Panel>
          <Panel title="FILTER" idx="B">
            <Seg
              h={26}
              value={roleF}
              onChange={(v) => {
                setRoleF(v);
                setPage(0);
              }}
              items={[{ value: "all" as const, label: "ALL" }, ...ROLES.map((r) => ({ value: r, label: ROLE_SHORT[r] }))]}
            />
            <div className="counts">
              {["all", ...ROLES].map((r) => (
                <span key={r} className="micro">
                  {counts[r] ?? 0}
                </span>
              ))}
            </div>
            <div className="row">
              <Seg
                h={22}
                mono
                style={{ width: 120 }}
                value={routeF}
                onChange={(v) => setRouteF(v)}
                items={[
                  { value: "sp" as const, label: "A" },
                  { value: "mpc" as const, label: "B" },
                  { value: "all" as const, label: "A+B" },
                ]}
              />
              <span className="label lo">ROUTE</span>
            </div>
            <label className="search">
              <span className="mono lo">/</span>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search" aria-label="search samples" />
              <span className="micro">{filtered.length} hits</span>
            </label>
          </Panel>
          <Panel title="STORE" idx="C" style={{ flex: 1 }}>
            <Lcd style={{ height: 70, display: "flex", alignItems: "center", gap: 16, padding: "0 12px" }}>
              <SevenSeg text={String(samples.length).padStart(3, "0")} h={46} />
              <span style={{ display: "grid", gap: 8 }}>
                <span className="label lo">SAMPLES</span>
                <span className="meta">{secs(total, 2)} s total</span>
              </span>
            </Lcd>
            <dl className="kv">
              <dt>DATA DIR</dt>
              <dd>{store?.data_dir ?? "—"}</dd>
              <dt>SIZE</dt>
              <dd>{store ? `${(store.bytes / 1048576).toFixed(1)} MB` : "—"}</dd>
              <dt>DUP (SHA)</dt>
              <dd>{dups}</dd>
              <dt>UNROLED</dt>
              <dd>{counts.other ?? 0}</dd>
            </dl>
          </Panel>
        </div>

        <Panel title="SAMPLES" idx="D" tone="bg1" bodyStyle={{ padding: "8px 8px 12px" }}>
          <table className="tbl">
            <colgroup>
              <col style={{ width: 30 }} />
              <col />
              <col style={{ width: 52 }} />
              <col style={{ width: 30 }} />
              <col style={{ width: 54 }} />
              <col style={{ width: 54 }} />
              <col style={{ width: 88 }} />
              <col style={{ width: 128 }} />
            </colgroup>
            <thead>
              <tr>
                <th>#</th>
                <th>NAME</th>
                <th>ROLE</th>
                <th>RT</th>
                <th>LEN</th>
                <th>SR</th>
                <th>SHA256</th>
                <th>WAVE</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s, i) => {
                const on = sel?.id === s.id;
                return (
                  <tr key={s.id} className={on ? "sel" : ""} style={{ height: 40 }} onClick={() => select(s.id)}>
                    <td className="micro">{String(page * PAGE + i + 1).padStart(2, "0")}</td>
                    <td className={on ? "achi" : "hi"} style={{ fontSize: 11.5 }}>
                      {s.name}
                    </td>
                    <td className={on ? "ac" : "meta"}>
                      <span className="stamp">{ROLE_SHORT[s.role ?? "other"]}</span>
                    </td>
                    <td className={s.route === "sp" ? "ac" : "meta"}>{s.route === "sp" ? "A" : "B"}</td>
                    <td className="meta">{secs(s.length_s)}</td>
                    <td className="meta">{kHz(s.sample_rate)}</td>
                    <td className="micro">{sha8(s.sha256)}</td>
                    <td>
                      <MiniWave id={s.id} sel={on} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!samples.length && <div className="empty">Drop WAV files on INTAKE to start the library.</div>}
          <div className="pager">
            <span className="meta">
              {filtered.length} / {samples.length}
            </span>
            <span className="label lo" style={{ marginLeft: "auto" }}>
              PAGE
            </span>
            <Seg
              h={20}
              mono
              style={{ width: Math.min(pages, 6) * 44 }}
              value={page}
              onChange={setPage}
              items={Array.from({ length: Math.min(pages, 6) }, (_, k) => ({ value: k, label: String(k + 1) }))}
            />
          </div>
        </Panel>

        <Panel title="DETAIL" idx="E">
          {sel ? (
            <>
              <div>
                <div className="detail-name">{sel.name}</div>
                <div className="micro">sha256 {sel.sha256.slice(0, 24)}…</div>
              </div>
              <div>
                <Lcd style={{ padding: 4 }}>
                  <Waveform a={null} b={detailPk} colorB="#6c97be" height={138} />
                </Lcd>
                <div className="ruler">
                  {[0, 1, 2, 3, 4].map((k) => (
                    <span key={k} className="micro">
                      {secs(((sel.length_s ?? 0) * k) / 4, 2)}
                    </span>
                  ))}
                </div>
              </div>
              <Field label="ROLE">
                <Seg h={34} size={13} value={sel.role ?? "other"} onChange={(role) => patch({ role })} items={ROLES.map((r) => ({ value: r, label: r.toUpperCase() }))} />
              </Field>
              <Field label="ROUTE">
                <Seg
                  h={30}
                  value={sel.route}
                  onChange={(route) => patch({ route })}
                  items={[
                    { value: "sp" as const, label: "A · 12B LIN 26.04K" },
                    { value: "mpc" as const, label: "B · 12B NL 40K" },
                  ]}
                />
              </Field>
              <dl className="meta-grid">
                <div>
                  <dt className="label lo">LEN</dt>
                  <dd className="v">{secs(sel.length_s)} s</dd>
                </div>
                <div>
                  <dt className="label lo">SR</dt>
                  <dd className="v">{sel.sample_rate} Hz</dd>
                </div>
                <div>
                  <dt className="label lo">CH</dt>
                  <dd className="v">{hdr ? `${hdr.channels} / ${hdr.channels === 1 ? "MONO" : "STEREO"}` : "—"}</dd>
                </div>
                <div>
                  <dt className="label lo">DEPTH</dt>
                  <dd className="v">{hdr ? depth(hdr.subtype) : "—"}</dd>
                </div>
                <div>
                  <dt className="label lo">PEAK</dt>
                  <dd className="v">{peak ? `${(20 * Math.log10(peak)).toFixed(1)} dBFS` : "—"}</dd>
                </div>
                <div>
                  <dt className="label lo">ADDED</dt>
                  <dd className="v">{new Date(sel.created_at).toLocaleString("sv-SE").slice(0, 16)}</dd>
                </div>
              </dl>
              <div className="rule" />
              <div>
                <div className="label lo" style={{ marginBottom: 8 }}>
                  LAST RENDERS
                </div>
                {renders.filter((r) => r.state === "succeeded").slice(0, 4).map((r) => (
                  <div key={r.id} className="render-row">
                    <span className="meta">
                      {r.preset_name} tune {tuneStr(r.tune)}
                    </span>
                    <span className="ac micro">OK</span>
                  </div>
                ))}
                {!renders.some((r) => r.state === "succeeded") && <div className="empty">none yet</div>}
              </div>
              <div className="detail-actions">
                <Btn kind="primary" h={40} w={196} size={14} onClick={() => navigate(`/chain?s=${sel.id}`)}>
                  SEND TO CHAIN
                </Btn>
                <Btn h={40} w="100%" onClick={remove}>
                  REMOVE
                </Btn>
              </div>
            </>
          ) : (
            <div className="empty">No sample selected.</div>
          )}
        </Panel>
      </div>
    </Frame>
  );
}

function depth(subtype: string) {
  const m = /PCM_(\d+)|FLOAT|DOUBLE/.exec(subtype);
  if (!m) return subtype.toLowerCase();
  return m[1] ? `${m[1]} int` : m[0] === "FLOAT" ? "32 float" : "64 float";
}
