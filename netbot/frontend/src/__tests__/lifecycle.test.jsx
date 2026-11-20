import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSession } from "../hooks/useSession.jsx";
import { createControllerScope } from "../runtime/controller-scope.mjs";
import { client, mockFetch, response } from "./fixtures.js";
afterEach(() => vi.useRealTimers());
it("expires the React session at the JWT deadline and clears tokens without refreshing", async () => {
  vi.useFakeTimers();
  const fetcher = mockFetch();
  const { result } = renderHook(() => useSession({ fetcher }));
  await act(async () =>
    result.current.login(client.email, "synthetic-password"),
  );
  expect(result.current.user.id).toBe(client.id);
  await act(async () => vi.advanceTimersByTime(3600001));
  expect(result.current.user).toBeNull();
  expect(result.current.screen).toBe("login");
  expect(result.current.api.getStoredTokens()).toBeNull();
  expect(fetcher.mock.calls.filter(([p]) => p === "/auth/logout")).toHaveLength(
    1,
  );
});
it("clears a suspended React session immediately on visibility change", async () => {
  vi.useFakeTimers();
  const now = Date.now();
  const fetcher = mockFetch();
  const { result } = renderHook(() => useSession({ fetcher }));
  await act(async () =>
    result.current.login(client.email, "synthetic-password"),
  );
  vi.setSystemTime(now + 3600001);
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  expect(result.current.user).toBeNull();
});
it("rejects a late profile when a newer login already replaced the attempt", async () => {
  let resolve;
  const pending = new Promise((r) => {
    resolve = r;
  });
  let profiles = 0;
  const fetcher = mockFetch(client, (p) =>
    p === "/auth/me" && ++profiles === 1 ? pending : undefined,
  );
  const { result } = renderHook(() => useSession({ fetcher }));
  let first;
  await act(async () => {
    first = result.current.login("old@example.test", "synthetic-password");
  });
  await act(async () =>
    result.current.login(client.email, "synthetic-password"),
  );
  await act(async () => {
    resolve(response({ ...client, email: "old@example.test" }));
    await first;
  });
  expect(result.current.user.email).toBe(client.email);
});
it("never installs credentials when profile validation fails", async () => {
  const fetcher = mockFetch(client, (p) =>
    p === "/auth/me" ? response({ detail: "denied" }, 403) : undefined,
  );
  const { result } = renderHook(() => useSession({ fetcher }));
  await act(async () => {
    await expect(
      result.current.login(client.email, "synthetic-password"),
    ).rejects.toThrow();
  });
  expect(result.current.user).toBeNull();
  expect(result.current.api.getStoredTokens()).toBeNull();
});
it("disposes DOM/global handlers and polling, leaving other mounted instances independent", () => {
  vi.useFakeTimers();
  const hit = vi.fn(),
    other = vi.fn();
  const { container } = render(
    <div>
      <button>Action</button>
    </div>,
  );
  const runtime = { state: { session: 3, user: client }, api: {} };
  const scope = createControllerScope(container, runtime);
  const el = scope.document.querySelector("button");
  el.addEventListener("click", hit);
  scope.window.addEventListener("pageshow", hit);
  scope.document.addEventListener("visibilitychange", hit);
  scope.window.setInterval(hit, 10);
  scope.window.setTimeout(hit, 10);
  scope.finishMount();
  const second = createControllerScope(container, runtime);
  second.window.setInterval(other, 10);
  second.finishMount();
  scope.dispose();
  fireEvent.click(el);
  window.dispatchEvent(new Event("pageshow"));
  document.dispatchEvent(new Event("visibilitychange"));
  vi.advanceTimersByTime(20);
  expect(hit).not.toHaveBeenCalled();
  expect(other).toHaveBeenCalledTimes(2);
  expect(scope.state.session).toBe(-1);
  expect(second.state.session).toBe(3);
  second.dispose();
  expect(vi.getTimerCount()).toBe(0);
});
