import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useMonitoring } from "../hooks/useMonitoring.jsx";
import { createApi } from "../../modules/api.mjs";
import { TrafficChart } from "../components/Monitoring.jsx";
import { Workspace } from "../components/Workspace.jsx";
import { supervisor, metric } from "./fixtures.js";

const runtime = (request) => ({
  state: { session: 1, user: supervisor },
  api: { monitoringRequest: request },
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it("waits for slow batches and deduplicates manual refresh before scheduling again", async () => {
  vi.useFakeTimers();
  let resolve;
  const pending = new Promise((r) => {
    resolve = r;
  });
  const request = vi.fn(() => pending);
  const runtimeValue = runtime(request);
  const { result, unmount } = renderHook(() =>
    useMonitoring(runtimeValue, true),
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20000);
    await result.current.refresh();
  });
  expect(request).toHaveBeenCalledTimes(6);
  await act(async () => resolve(metric([])));
  await act(async () => vi.advanceTimersByTimeAsync(4999));
  expect(request).toHaveBeenCalledTimes(6);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(request).toHaveBeenCalledTimes(12);
  unmount();
});
it("aborts background requests, rejects late data and resumes with a fresh batch", async () => {
  let visibility = "visible",
    resolve;
  vi.spyOn(document, "visibilityState", "get").mockImplementation(
    () => visibility,
  );
  const pending = new Promise((r) => {
    resolve = r;
  });
  const request = vi.fn(() => pending),
    value = runtime(request);
  const { result, unmount } = renderHook(() => useMonitoring(value, true));
  const signal = request.mock.calls[0][1].signal;
  act(() => {
    visibility = "hidden";
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(metric(["old"])));
  expect(result.current.data).toEqual({});
  await act(async () => result.current.refresh());
  expect(request).toHaveBeenCalledTimes(6);
  request.mockResolvedValue(metric([]));
  await act(async () => {
    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(request).toHaveBeenCalledTimes(12);
  expect(result.current.data.system.data).toEqual([]);
  const newSignal = request.mock.calls[6][1].signal;
  unmount();
  expect(newSignal.aborted).toBe(true);
});
it("deadline failures finish the batch and permit recovery", async () => {
  const deadline = new AbortController();
  vi.spyOn(AbortSignal, "timeout").mockReturnValue(deadline.signal);
  const request = vi.fn(
    (path, { signal }) =>
      new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), {
          once: true,
        });
      }),
  );
  const value = runtime(request);
  const { result, unmount } = renderHook(() => useMonitoring(value, true));
  await act(async () =>
    deadline.abort(new DOMException("deadline", "TimeoutError")),
  );
  expect(result.current.busy).toBe(false);
  expect(result.current.data.system.status).toBe("unavailable");
  request.mockResolvedValue(metric([]));
  await act(async () => result.current.refresh());
  expect(result.current.error).toBe("");
  unmount();
});
it("cancels old window requests and preserves the newer results", async () => {
  let resolve;
  const pending = new Promise((r) => {
    resolve = r;
  });
  const request = vi.fn(() => pending),
    value = runtime(request);
  const { result, unmount } = renderHook(() => useMonitoring(value, true));
  const signal = request.mock.calls[0][1].signal;
  request.mockResolvedValue(metric(["new"]));
  await act(async () => result.current.setWindow(900));
  expect(signal.aborted).toBe(true);
  expect(request.mock.calls.at(-1)[0]).toContain("window=900");
  await act(async () => resolve(metric(["old"])));
  expect(result.current.data.system.data).toEqual(["new"]);
  unmount();
});
it("hides the mobile disclosure, restores focus on Escape and keeps route hashes intact", async () => {
  const media = {
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  };
  vi.stubGlobal("matchMedia", () => media);
  history.replaceState(null, "", "#overview");
  const value = runtime(vi.fn(() => Promise.resolve(metric([]))));
  value.api.authedRequest = vi.fn(() => Promise.resolve([]));
  value.notify = vi.fn();
  value.signOut = vi.fn();
  const { unmount } = render(<Workspace runtime={value} />);
  await act(async () => {});
  const menu = screen.getByRole("button", { name: "Abrir navegación" });
  expect(screen.queryByRole("navigation")).toBeNull();
  fireEvent.click(menu);
  expect(
    screen.getByRole("button", { name: "Cerrar navegación" }),
  ).toHaveFocus();
  fireEvent.keyDown(document.activeElement, { key: "Escape" });
  expect(menu).toHaveFocus();
  expect(menu).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("navigation")).toBeNull();
  fireEvent.click(menu);
  fireEvent.click(
    within(screen.getByRole("navigation")).getByText("Interfaces"),
  );
  expect(location.hash).toBe("#interfaces");
  expect(document.title).toBe("Interfaces | Netbot");
  expect(
    screen.getByRole("heading", { name: "Interfaces", level: 1 }),
  ).toHaveFocus();
  const skip = screen.getByRole("link", { name: "Saltar al contenido" });
  fireEvent.click(skip);
  expect(location.hash).toBe("#interfaces");
  expect(
    screen.getByRole("table", { name: "Interfaces de red" }),
  ).toBeVisible();
  expect(screen.getAllByRole("columnheader")[0]).toHaveAttribute(
    "scope",
    "col",
  );
  fireEvent.click(menu);
  act(() => {
    media.matches = false;
    media.addEventListener.mock.calls[0][1]();
  });
  expect(screen.getByRole("navigation")).toBeVisible();
  expect(
    within(screen.getByRole("navigation")).getByText("Interfaces"),
  ).toHaveFocus();
  act(() => {
    media.matches = true;
    media.addEventListener.mock.calls[0][1]();
  });
  expect(menu).toHaveFocus();
  expect(screen.queryByRole("navigation")).toBeNull();
  unmount();
});

it("forwards cancellation through the actual monitoring API client", async () => {
  const controller = new AbortController();
  const fetcher = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => metric([]),
  }));
  const api = createApi({
    fetch: fetcher,
    localStorage: { removeItem() {} },
    state: { session: 1 },
    baseUrl: "",
  });
  await api.monitoringRequest("/system", { signal: controller.signal });
  expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal);
});
it("exposes traffic samples in a named table with explicit column headers", () => {
  render(
    <TrafficChart
      series={[
        {
          interface_id: "wan",
          points: [
            {
              timestamp: "2026-11-17T12:00:00Z",
              bytes_in_per_second: 10,
              bytes_out_per_second: 20,
            },
            {
              timestamp: "2026-11-17T12:00:05Z",
              bytes_in_per_second: 30,
              bytes_out_per_second: 40,
            },
          ],
        },
      ]}
    />,
  );
  fireEvent.click(screen.getByText("Ver datos del tráfico WAN"));
  const table = screen.getByRole("table", { name: "Muestras del tráfico WAN" });
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(
    within(table).getByRole("columnheader", { name: "Entrada" }),
  ).toHaveAttribute("scope", "col");
});
