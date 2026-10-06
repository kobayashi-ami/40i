import { useEffect, useState, type ReactNode } from "react";
import { useLive } from "../lib/live";
import { navigate } from "../lib/router";
import { ChainV, Led, Screw, SevenSeg } from "./ui";
import "./frame.css";

export const NAV = [
  { n: "01", l: "LIB", to: "/lib", title: "LIBRARY" },
  { n: "02", l: "CHAIN", to: "/chain", title: "CHAIN" },
  { n: "03", l: "JOBS", to: "/jobs", title: "JOBS" },
  { n: "04", l: "A/B", to: "/ab", title: "A/B" },
];

function Clock() {
  const [t, setT] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setT(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <>{t.toTimeString().slice(0, 8)}</>;
}

export function Link({ to, children, ...rest }: { to: string; children: ReactNode } & Record<string, any>) {
  return (
    <a
      href={to}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.button !== 0) return;
        e.preventDefault();
        navigate(to);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}

export function Frame({ active, context, children }: { active: number; context?: ReactNode; children: ReactNode }) {
  const { snap, health, connected } = useLive();
  const live = snap?.workers.filter((w) => w.state !== "lost" && w.state !== "stopped").length ?? 0;
  const total = snap?.workers.filter((w) => w.state !== "stopped").length ?? 0;
  const pg = health?.db === "ok";
  const rds = health?.redis === "ok";
  const host = location.hostname;
  return (
    <div className="frame">
      <header className="topbar">
        <div className="logo">
          <b>1260</b>
        </div>
        <div className="scr">
          <span className="n">{NAV[active].n}</span>
          <span className="t">{NAV[active].title}</span>
          {context && <span className="ctx">{context}</span>}
        </div>
        <div className="status">
          <span className="grp">
            <span className="label lo">TAILNET</span>
            <Led on={connected} sm />
            <span className="mono meta">{host}</span>
          </span>
          <span className="sep" />
          <span className="grp">
            <span className="label">PG</span>
            <Led on={pg} sm />
          </span>
          <span className="grp">
            <span className="label">RDS</span>
            <Led on={rds} sm />
          </span>
          <span className="sep" />
          <span className="grp">
            <span className="label lo">WRK</span>
            <SevenSeg text={String(live)} h={20} />
          </span>
          <span className="grp">
            <span className="label lo">QUEUE</span>
            <SevenSeg text={String(snap?.queue ?? 0).padStart(2, "0")} h={20} gap={4} />
          </span>
        </div>
      </header>
      <nav className="rail">
        {NAV.map((n, i) => (
          <div key={n.to} style={{ width: "100%" }}>
            <Link to={n.to} aria-current={i === active ? "page" : undefined}>
              <span className="n">{n.n}</span>
              <span className="l">{n.l}</span>
              <Led on={i === active} sm />
            </Link>
            <div className="rule div" style={{ margin: "6px auto 0" }} />
          </div>
        ))}
        <ChainV height={360} color="#232a31" style={{ marginTop: "auto" }} />
        <span style={{ position: "relative", width: 10, height: 36 }}>
          <Screw pos="bl" a={40} />
        </span>
      </nav>
      <main className="main">{children}</main>
      <footer className="strip">
        <span>PG {pg ? "OK" : health ? health.db : "—"}</span>
        <span>REDIS {rds ? "OK" : health ? health.redis : "—"}</span>
        <span>
          WORKERS {live}/{total} LIVE
        </span>
        <span>QUEUE {snap?.queue ?? 0}</span>
        <span>127.0.0.1:8260 → {location.protocol === "https:" ? "tailscale serve :443" : "local only"}</span>
        <span className="right">
          v{health?.version ?? "—"}&nbsp;&nbsp;&nbsp;<Clock />
        </span>
      </footer>
    </div>
  );
}
