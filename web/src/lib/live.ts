// Live snapshot over SSE: a Postgres-built snapshot on connect, then deltas; resync on anything structural.
import { useEffect, useSyncExternalStore } from "react";
import { api, type Health, type Snapshot } from "./api";

type State = { snap: Snapshot | null; connected: boolean; health: Health | null };
let state: State = { snap: null, connected: false, health: null };
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
const set = (patch: Partial<State>) => {
  state = { ...state, ...patch };
  emit();
};

let es: EventSource | null = null;
let refetch: number | undefined;
let users = 0;

function scheduleResync() {
  window.clearTimeout(refetch);
  refetch = window.setTimeout(async () => {
    try {
      set({ snap: await api.snapshot() });
    } catch {
      /* the next event retries */
    }
  }, 200);
}

function onUpdate(e: MessageEvent) {
  const ev = JSON.parse(e.data);
  const snap = state.snap;
  if (ev.type === "progress" && snap && ev.stage_index !== undefined) {
    const jobs = snap.jobs.map((j) => {
      if (j.id !== ev.job_id) return j;
      const k = Number(ev.stage_index);
      const p = Number(ev.stage_progress);
      return {
        ...j,
        state: "running" as const,
        stages: j.stages.map((s) =>
          s.ordinal < k && s.state !== "succeeded"
            ? { ...s, state: "succeeded" as const, progress: 1 }
            : s.ordinal === k
              ? { ...s, state: p >= 1 ? ("succeeded" as const) : ("running" as const), progress: p }
              : s,
        ),
      };
    });
    if (jobs.some((j) => j.id === ev.job_id)) {
      set({ snap: { ...snap, jobs } });
      return;
    }
  }
  scheduleResync();
}

function connect() {
  es = new EventSource("/api/events");
  es.addEventListener("snapshot", (e) => set({ snap: JSON.parse((e as MessageEvent).data), connected: true }));
  es.addEventListener("update", onUpdate as EventListener);
  es.onopen = () => set({ connected: true });
  es.onerror = () => set({ connected: false });
}

let healthTimer: number | undefined;
async function pollHealth() {
  try {
    set({ health: await api.health() });
  } catch {
    set({ health: null });
  }
}

export function useLive(): State {
  useEffect(() => {
    users += 1;
    if (users === 1) {
      connect();
      pollHealth();
      healthTimer = window.setInterval(pollHealth, 10000);
    }
    return () => {
      users -= 1;
      if (users === 0) {
        es?.close();
        es = null;
        window.clearInterval(healthTimer);
      }
    };
  }, []);
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => state,
  );
}

export const resync = scheduleResync;
