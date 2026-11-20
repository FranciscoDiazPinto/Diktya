import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { GoogleSignIn } from "../components/GoogleSignIn.jsx";
import { client, mockFetch, response, tokens } from "./fixtures.js";

function sdk() {
  let options;
  const identity = {
    initialize: vi.fn((value) => {
      options = value;
    }),
    renderButton: vi.fn((container) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Continuar con Google";
      button.addEventListener("click", () =>
        options.callback({ credential: "synthetic-google-token" }),
      );
      container.append(button);
    }),
  };
  vi.stubGlobal("google", { accounts: { id: identity } });
  return {
    identity,
    get options() {
      return options;
    },
  };
}
const challenge = {
  nonce: "nonce-from-server",
  challenge_token: "challenge-from-server",
  expires_in: 300,
};
const config = {
  enabled: true,
  client_id: "123-test.apps.googleusercontent.com",
};
const googleFetch = (override = () => undefined) =>
  mockFetch(client, (path, options) => {
    const custom = override(path, options);
    if (custom !== undefined) return custom;
    if (path === "/auth/google/config") return response(config);
    if (path === "/auth/google/challenge") return response(challenge);
    if (path === "/auth/google") return response(tokens());
  });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("does not load the Google SDK or issue a challenge while disabled", async () => {
  const google = sdk();
  const api = { apiRequest: vi.fn(async () => ({ enabled: false })) };
  render(<GoogleSignIn api={api} onCredential={vi.fn()} />);
  await waitFor(() =>
    expect(document.querySelector(".google-sign-in")).not.toBeVisible(),
  );
  expect(google.identity.initialize).not.toHaveBeenCalled();
  expect(api.apiRequest).toHaveBeenCalledTimes(1);
  expect(
    document.querySelector(
      'script[src="https://accounts.google.com/gsi/client"]',
    ),
  ).toBeNull();
});
it("uses only the server client ID and nonce, then sends the credential and single-use challenge", async () => {
  const google = sdk(),
    fetcher = googleFetch();
  render(<App fetcher={fetcher} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Continuar con Google" }),
  );
  await screen.findByRole("button", { name: "Cerrar sesión" });
  expect(google.options.client_id).toBe(config.client_id);
  expect(google.options.nonce).toBe(challenge.nonce);
  const request = fetcher.mock.calls.find(([path]) => path === "/auth/google");
  expect(JSON.parse(request[1].body)).toEqual({
    credential: "synthetic-google-token",
    challenge_token: challenge.challenge_token,
  });
  expect(localStorage.getItem("netbot_tokens")).toBeNull();
});
it("ignores a Google popup callback after returning to guest chat", async () => {
  const google = sdk(),
    fetcher = googleFetch();
  render(<App fetcher={fetcher} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
  );
  await screen.findByRole("button", { name: "Continuar con Google" });
  const callback = google.options.callback;
  fireEvent.click(screen.getByRole("button", { name: /Volver al chat/ }));
  await act(async () => callback({ credential: "late-google-token" }));
  expect(fetcher.mock.calls.some(([p]) => p === "/auth/google")).toBe(false);
  expect(
    screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
  ).toBeVisible();
});
it("does not restore a pending Google login after navigation cancels it", async () => {
  sdk();
  let resolve;
  const pending = new Promise((r) => {
    resolve = r;
  });
  const fetcher = googleFetch((path) =>
    path === "/auth/google" ? pending : undefined,
  );
  render(<App fetcher={fetcher} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Continuar con Google" }),
  );
  fireEvent.click(screen.getByRole("button", { name: /Volver al chat/ }));
  await act(async () => resolve(response(tokens())));
  expect(
    screen.queryByRole("button", { name: "Cerrar sesión" }),
  ).not.toBeInTheDocument();
});
it("rejects duplicate SDK callbacks and keeps local password login available after failure", async () => {
  const google = sdk(),
    fetcher = googleFetch((path) =>
      path === "/auth/google" ? response({ detail: "denied" }, 401) : undefined,
    );
  render(<App fetcher={fetcher} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
  );
  await screen.findByRole("button", { name: "Continuar con Google" });
  fireEvent.change(screen.getByLabelText("Contraseña", { exact: true }), {
    target: { value: "never-send-local-password" },
  });
  const callback = google.options.callback;
  await act(async () => {
    callback({ credential: "synthetic-google-token" });
    callback({ credential: "duplicate" });
  });
  await screen.findByText(/No fue posible autorizar/);
  expect(fetcher.mock.calls.filter(([p]) => p === "/auth/google")).toHaveLength(
    1,
  );
  expect(screen.getByRole("button", { name: "Ingresar" })).not.toBeDisabled();
  expect(screen.getByLabelText("Contraseña", { exact: true })).toHaveValue("");
});
it("expires the button nonce and requires a new challenge instead of reusing it", async () => {
  vi.useFakeTimers();
  const google = sdk(),
    onCredential = vi.fn();
  const api = {
    apiRequest: vi.fn(async (path) =>
      path.endsWith("config") ? config : challenge,
    ),
  };
  render(<GoogleSignIn api={api} onCredential={onCredential} />);
  await act(async () => {});
  const old = google.options.callback;
  await act(async () => vi.advanceTimersByTime(300000));
  expect(
    screen.queryByRole("button", { name: "Continuar con Google" }),
  ).not.toBeInTheDocument();
  old({ credential: "expired" });
  expect(onCredential).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Reintentar acceso con Google" }),
  );
  await act(async () => {});
  expect(
    api.apiRequest.mock.calls.filter(([p]) => p.endsWith("challenge")),
  ).toHaveLength(2);
});
