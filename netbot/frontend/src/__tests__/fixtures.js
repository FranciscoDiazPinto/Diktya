import { vi } from "vitest";
export const client = {
  id: 1,
  email: "cliente@example.test",
  full_name: "Cliente Demo",
  roles: ["cliente"],
  permissions: [
    "chat:use",
    "networks:read:own",
    "wifi:access:read:own",
    "tickets:create:own",
    "tickets:read:own",
  ],
};
export const supervisor = {
  id: 2,
  email: "supervisor@example.test",
  full_name: "Supervisor Demo",
  roles: ["visor"],
  permissions: ["monitoring:read", "chat:use", "changes:read"],
};
export const admin = {
  id: 3,
  email: "admin@example.test",
  full_name: "Admin Demo",
  roles: ["admin"],
  permissions: [
    "monitoring:read",
    "chat:use",
    "networks:read:own",
    "networks:manage",
    "wifi:access:read:own",
    "tickets:manage",
    "tickets:read",
    "tickets:create:own",
    "changes:request",
    "changes:approve",
    "vlan:reserve",
    "audit:read",
    "users:manage",
  ],
};
export const tokens = () => ({
  access_token:
    "header." +
    btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })) +
    ".signature",
  refresh_token: "synthetic-refresh",
});
export const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});
export const metric = (data, extra = {}) => ({
  data,
  status: "ok",
  source: "mock",
  stale: false,
  collected_at: new Date().toISOString(),
  ...extra,
});
export function mockFetch(user = client, overrides = () => undefined) {
  return vi.fn(async (path, options = {}) => {
    const custom = overrides(path, options);
    if (custom !== undefined) return custom;
    const url = new URL(path, "http://localhost"),
      p = url.pathname;
    if (p === "/auth/login") return response(tokens());
    if (p === "/auth/me") return response(user);
    if (p === "/auth/logout") return response(null, 204);
    if (p === "/api/v1/networks")
      return response([{ id: 7, name: "Feria", ssid: "Feria-Demo" }]);
    if (p === "/api/v1/chat/messages")
      return response({ version: 1, answer: "Respuesta segura" });
    if (p === "/api/v1/chat/conversations" && options.method === "POST")
      return response({ id: 4, version: 0 });
    if (p === "/api/v1/chat/conversations") return response([]);
    if (p === "/api/v1/monitoring/system")
      return response(
        metric({
          hostname: "firewall-demo",
          cpu_percent: 12,
          memory: { used_percent: 35 },
          uptime_seconds: 3600,
        }),
      );
    if (p === "/api/v1/monitoring/summary")
      return response({
        access_points_online: 1,
        access_points_total: 1,
        access_points_offline: 0,
        active_alerts: 0,
        ssids_active: 1,
        vlans_active: 1,
        sources: [],
        last_update_at: new Date().toISOString(),
      });
    if (p === "/api/v1/monitoring/interfaces")
      return response(
        metric([
          {
            interface_id: "wan",
            name: "WAN Demo",
            status: "up",
            ip_addresses: [],
          },
        ]),
      );
    if (p === "/api/v1/monitoring/firewall/stats")
      return response(
        metric({
          packets_blocked: 12,
          packets_passed: 100,
          states: { current_entries: 2 },
        }),
      );
    if (
      [
        "/api/v1/monitoring/clients",
        "/api/v1/monitoring/interfaces/traffic",
        "/api/v1/monitoring/firewall/events",
      ].includes(p)
    )
      return response(metric([]));
    if (p === "/api/v1/changes/csv-imports/options")
      return response({
        interfaces: [],
        vlans: [],
        max_bytes: 100000,
        max_rows: 100,
        source: "mock",
      });
    if (p === "/api/v1/notifications")
      return response({ items: [], unread: 0 });
    if (p === "/api/v1/audit" || p === "/api/v1/audit/mine")
      return response({ items: [], total: 0 });
    if (p === "/api/v1/chat/health")
      return response({ provider: "mock", detail: "Simulado" });
    if (p === "/api/v1/monitoring/plans") return response([]);
    if (p.startsWith("/api/v1/monitoring/"))
      return response({ items: [], total: 0, offset: 0, limit: 25 });
    return response([]);
  });
}
