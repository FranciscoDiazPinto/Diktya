import { useCallback, useEffect, useRef, useState } from "react";
const RESOURCES = {
  system: "/system",
  interfaces: "/interfaces",
  clients: "/clients",
  stats: "/firewall/stats",
  events: "/firewall/events?limit=200",
};
export function useMonitoring(runtime, enabled) {
  const [data, setData] = useState({}),
    [error, setError] = useState(""),
    [lastSync, setLastSync] = useState(null);
  const [windowSeconds, setWindow] = useState(300),
    [busy, setBusy] = useState(false);
  const cycle = useRef(null);
  const refresh = useCallback(() => cycle.current?.(), []);
  useEffect(() => {
    let active = true,
      timer,
      controller,
      running = false,
      version = 0;
    const epoch = runtime.state.session;
    const visible = () => document.visibilityState !== "hidden";
    const stop = () => {
      version++;
      clearTimeout(timer);
      controller?.abort();
      running = false;
    };
    async function run() {
      if (
        !enabled ||
        !active ||
        !visible() ||
        running ||
        runtime.state.session !== epoch
      )
        return;
      clearTimeout(timer);
      running = true;
      const currentVersion = ++version;
      controller = new AbortController();
      const signal = AbortSignal.any([
        controller.signal,
        AbortSignal.timeout(15000),
      ]);
      const current = () =>
        active && version === currentVersion && runtime.state.session === epoch;
      setBusy(true);
      const resources = {
        ...RESOURCES,
        traffic: `/interfaces/traffic?window=${windowSeconds}`,
      };
      try {
        const results = await Promise.allSettled(
          Object.values(resources).map((path) =>
            runtime.api.monitoringRequest(path, { signal }),
          ),
        );
        if (!current()) return;
        const next = {},
          failures = [];
        Object.keys(resources).forEach((key, i) => {
          const result = results[i];
          if (result.status === "fulfilled") next[key] = result.value;
          else {
            next[key] = { status: "unavailable", data: null };
            failures.push(key);
          }
        });
        setData(next);
        setLastSync(new Date());
        setError(
          failures.length
            ? "No se pudieron consultar: " + failures.join(", ") + "."
            : "",
        );
      } finally {
        if (current()) {
          running = false;
          setBusy(false);
          if (visible()) timer = setTimeout(run, 5000);
        }
      }
    }
    const onVisibility = () => {
      stop();
      setBusy(false);
      if (visible()) void run();
    };
    cycle.current = run;
    setBusy(false);
    void run();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      if (cycle.current === run) cycle.current = null;
    };
  }, [runtime, enabled, windowSeconds]);
  return { data, error, lastSync, busy, refresh, windowSeconds, setWindow };
}
