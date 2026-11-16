import { useCallback, useEffect, useMemo, useState } from "react";
export const VIEWS = [
  ["overview", "Resumen y chat", []],
  ...[
    ["devices", "Dispositivos"],
    ["alerts", "Alertas"],
    ["wireless", "SSID y VLAN"],
    ["coverage", "Planos"],
    ["interfaces", "Interfaces"],
    ["clients", "Clientes"],
    ["firewall", "Firewall"],
  ].map(([key, title]) => [key, title, ["monitoring:read"]]),
  [
    "access-points-panel",
    "Puntos de acceso",
    ["monitoring:read", "networks:read:details"],
  ],
  [
    "support-panel",
    "Mi red",
    ["networks:read:own", "wifi:access:read:own", "networks:manage"],
  ],
  [
    "tickets-panel",
    "Tickets",
    [
      "tickets:read:own",
      "tickets:read:assigned",
      "tickets:read",
      "tickets:manage",
      "monitoring:read",
    ],
  ],
  ["provisioning", "Aprovisionamiento", ["changes:request", "vlan:reserve"]],
  ["audit", "Auditoría", ["audit:read", "changes:request"]],
  ["users", "Usuarios", ["users:manage"]],
  ["system", "Estado del sistema", ["monitoring:read"]],
  ["account", "Mi cuenta", []],
];
export const navId = (key) =>
  (({
    "access-points-panel": "ap",
    "support-panel": "support",
    "tickets-panel": "tickets",
  })[key] || key) + "-nav";
export const allowedViews = (user) =>
  VIEWS.filter(
    ([, , permissions]) =>
      !permissions.length ||
      permissions.some((p) => user.permissions?.includes(p)),
  );
export function useNavigation(user) {
  const allowed = useMemo(() => allowedViews(user), [user]);
  const resolve = useCallback(() => {
    const key =
      location.hash.slice(1) === "chat" ? "overview" : location.hash.slice(1);
    return allowed.some((v) => v[0] === key) ? key : "overview";
  }, [allowed]);
  const [view, setView] = useState(resolve);
  useEffect(() => {
    const restore = () => {
      const key = resolve();
      setView(key);
      if (location.hash !== "#" + key)
        history.replaceState(null, "", "#" + key);
    };
    restore();
    window.addEventListener("hashchange", restore);
    window.addEventListener("popstate", restore);
    return () => {
      window.removeEventListener("hashchange", restore);
      window.removeEventListener("popstate", restore);
    };
  }, [resolve]);
  const navigate = useCallback(
    (key) => {
      if (key === "chat") key = "overview";
      if (!allowed.some((v) => v[0] === key)) return false;
      history.pushState(null, "", "#" + key);
      setView(key);
      return true;
    },
    [allowed],
  );
  return { view, navigate, allowed };
}
