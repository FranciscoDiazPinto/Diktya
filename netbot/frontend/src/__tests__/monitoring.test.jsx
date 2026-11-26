import { act, render, renderHook, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  MonitoringOverview,
  MonitoringNotices,
  TrafficChart,
  Interfaces,
  Clients,
} from "../components/Monitoring.jsx";
import { useMonitoring } from "../hooks/useMonitoring.jsx";
import { metric } from "./fixtures.js";
it("renders missing and stale metrics without claiming live connectivity or interpreting HTML", () => {
  const monitoring = {
    data: {
      system: metric(
        { hostname: "<img src=x onerror=alert(1)>", cpu_percent: 12 },
        { stale: true },
      ),
      interfaces: metric(null, { status: "unavailable" }),
    },
    error: "",
  };
  render(
    <>
      <MonitoringNotices monitoring={monitoring} />
      <MonitoringOverview monitoring={monitoring} />
    </>,
  );
  expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull();
  expect(screen.getByText("Datos parciales o anteriores")).toBeVisible();
  expect(screen.queryByText("En vivo")).not.toBeInTheDocument();
});
it("builds traffic paths from endpoint samples and shows an empty state until two arrive", () => {
  const { rerender } = render(<TrafficChart />);
  expect(screen.getByText(/Recolectando/)).toBeVisible();
  rerender(
    <TrafficChart
      series={[
        {
          interface_id: "wan",
          points: [
            {
              timestamp: "2026-11-14T12:00:00Z",
              bytes_in_per_second: 1,
              bytes_out_per_second: 2,
            },
            {
              timestamp: "2026-11-14T12:00:05Z",
              bytes_in_per_second: 4,
              bytes_out_per_second: 3,
            },
          ],
        },
      ]}
    />,
  );
  expect(screen.getByRole("img")).toBeVisible();
  expect(
    document.querySelector(".inbound-line").getAttribute("d"),
  ).not.toContain("NaN");
});
it("cleans polling and discards a late metrics response after session changes", async () => {
  let resolve;
  const pending = new Promise((r) => {
    resolve = r;
  });
  const runtime = {
    state: { session: 1 },
    api: { monitoringRequest: vi.fn(() => pending) },
  };
  const { result, unmount } = renderHook(() => useMonitoring(runtime, true));
  expect(runtime.api.monitoringRequest).toHaveBeenCalledTimes(6);
  runtime.state.session++;
  await act(async () => resolve(metric([])));
  expect(result.current.data).toEqual({});
  unmount();
});
it("keeps successful endpoints when one metric fails", async () => {
  const runtime = {
    state: { session: 1 },
    api: {
      monitoringRequest: vi.fn((path) =>
        path === "/system"
          ? Promise.reject(new Error("offline"))
          : Promise.resolve(metric([])),
      ),
    },
  };
  const { result } = renderHook(() => useMonitoring(runtime, true));
  await act(async () => {});
  expect(result.current.data.system.status).toBe("unavailable");
  expect(result.current.data.interfaces.status).toBe("ok");
});
it("filters real DHCP component rows", () => {
  const { container } = render(
    <Clients
      monitoring={{
        data: {
          clients: metric([
            { hostname: "stand-a", ip_address: "192.0.2.1", active: true },
            { hostname: "stand-b", ip_address: "192.0.2.2", active: false },
          ]),
        },
      }}
    />,
  );
  expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
});

it("reports denied WAN counters without rendering missing counters as zero", () => {
  const monitoring = {
    data: {
      traffic: { data: null, status: "degraded", source: "opnsense", issues: [{ kind: "permission" }] },
      interfaces: metric([{ name: "WAN principal", status: "up", traffic: null }]),
    },
  };
  render(
    <>
      <MonitoringOverview monitoring={monitoring} />
      <Interfaces monitoring={monitoring} />
    </>,
  );
  expect(screen.getAllByText("Permiso insuficiente en OPNsense.")).toHaveLength(2);
  expect(screen.queryByText("Recolectando muestras de tráfico…")).toBeNull();
  const row = screen.getByText("WAN principal").closest("tr");
  expect(Array.from(row.cells).slice(-2).map((cell) => cell.textContent)).toEqual(["–", "–"]);
});
