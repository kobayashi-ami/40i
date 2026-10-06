// Routes: /lib /chain /jobs /ab on desktop; under 900 px the mobile tabs (design.md §7).
import { useEffect } from "react";
import Mobile from "./mobile/Mobile";
import AB from "./screens/AB";
import Chain from "./screens/Chain";
import Jobs from "./screens/Jobs";
import Library from "./screens/Library";
import Parts from "./screens/Parts";
import { navigate, useLocation, useMedia } from "./lib/router";

const DESKTOP: Record<string, () => JSX.Element> = { "/lib": Library, "/chain": Chain, "/jobs": Jobs, "/ab": AB };
const MOBILE_TO_DESKTOP: Record<string, string> = { "/listen": "/ab", "/workers": "/jobs", "/log": "/jobs" };

export default function App() {
  const { path, query } = useLocation();
  const mobile = useMedia("(max-width: 899px)");

  useEffect(() => {
    if (!mobile && !DESKTOP[path] && path !== "/parts") {
      const to = MOBILE_TO_DESKTOP[path] ?? "/lib";
      const qs = query.toString();
      navigate(qs ? `${to}?${qs}` : to, true);
    }
  }, [mobile, path]);

  if (path === "/parts") return <Parts />;
  if (mobile) return <Mobile />;
  const Screen = DESKTOP[path] ?? Library;
  return <Screen />;
}
