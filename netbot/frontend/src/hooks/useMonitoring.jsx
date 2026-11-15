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
  const generation = useRef(0),
    active = useRef(false);
  const refresh = useCallback(async () => {
    if (!enabled || !active.current) return;
    const version = ++generation.current,
      epoch = runtime.state.session;
    const current = () =>
      active.current &&
      generation.current === version &&
      runtime.state.session === epoch;
    setBusy(true);
    const resources = {
      ...RESOURCES,
      traffic: `/interfaces/traffic?window=${windowSeconds}`,
    };
    const results = await Promise.allSettled(
      Object.values(resources).map((path) =>
        runtime.api.monitoringRequest(path),
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
    setBusy(false);
  }, [runtime, enabled, windowSeconds]);
  useEffect(() => {
    active.current = true;
    refresh();
    const timer = enabled ? setInterval(refresh, 5000) : null;
    return () => {
      active.current = false;
      generation.current++;
      clearInterval(timer);
    };
  }, [refresh, enabled]);
  return { data, error, lastSync, busy, refresh, windowSeconds, setWindow };
}
