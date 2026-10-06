// Minimal path router (history API). Query parameters carry the selected sample / job.
import { useSyncExternalStore } from "react";

const subs = new Set<() => void>();
window.addEventListener("popstate", () => subs.forEach((f) => f()));

export function navigate(to: string, replace = false) {
  if (to !== location.pathname + location.search) {
    if (replace) history.replaceState(null, "", to);
    else history.pushState(null, "", to);
    subs.forEach((f) => f());
  }
}

export function useLocation(): { path: string; query: URLSearchParams } {
  const href = useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => location.pathname + location.search,
  );
  const u = new URL(href, location.origin);
  return { path: u.pathname, query: u.searchParams };
}

export function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (f) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", f);
      return () => m.removeEventListener("change", f);
    },
    () => window.matchMedia(query).matches,
  );
}
