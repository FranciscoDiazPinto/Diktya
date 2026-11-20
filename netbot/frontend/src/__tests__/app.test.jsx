import { StrictMode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { client, supervisor, admin, mockFetch, response } from "./fixtures.js";
async function login(fetcher, user = client) {
  const ui = render(
    <StrictMode>
      <App fetcher={fetcher} />
    </StrictMode>,
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
  );
  fireEvent.change(screen.getByLabelText("Correo electrónico"), {
    target: { value: user.email },
  });
  fireEvent.change(screen.getByLabelText("Contraseña", { exact: true }), {
    target: { value: "synthetic-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Ingresar" }));
  await screen.findByRole("button", { name: "Cerrar sesión" });
  return ui;
}
beforeEach(() => {
  history.replaceState(null, "", "#overview");
  localStorage.clear();
});
describe("React application with the real feature controllers", () => {
  it("mounts guest chat and cancels a pending login on returning to guests", async () => {
    let resolve;
    const pending = new Promise((r) => {
      resolve = r;
    });
    const fetcher = mockFetch(client, (p) =>
      p === "/auth/login" ? pending : undefined,
    );
    render(<App fetcher={fetcher} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
    );
    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: client.email },
    });
    fireEvent.change(screen.getByLabelText("Contraseña", { exact: true }), {
      target: { value: "synthetic-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ingresar" }));
    expect(screen.getByLabelText("Contraseña", { exact: true })).toHaveValue(
      "",
    );
    fireEvent.click(screen.getByRole("button", { name: /Volver al chat/ }));
    await act(async () =>
      resolve(response({ access_token: "late", refresh_token: "late" })),
    );
    expect(
      screen.getByRole("button", { name: "Iniciar sesión · Equipo" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Cerrar sesión" }),
    ).not.toBeInTheDocument();
  });
  it("keeps tokens in memory, sends chat without browser history and clears all panels on logout", async () => {
    localStorage.setItem("netbot_tokens", "old");
    const fetcher = mockFetch();
    await login(fetcher);
    await waitFor(() =>
      expect(document.querySelector("#chat-send")).not.toBeDisabled(),
    );
    expect(localStorage.getItem("netbot_tokens")).toBeNull();
    fireEvent.change(document.querySelector("#chat-message"), {
      target: { value: "Consulta de prueba" },
    });
    fireEvent.submit(document.querySelector("#chat-form"));
    await screen.findByText("Respuesta segura");
    const request = fetcher.mock.calls.find(
      ([p]) => p === "/api/v1/chat/messages",
    );
    expect(JSON.parse(request[1].body)).toEqual({
      message: "Consulta de prueba",
      conversation_id: 4,
      version: 0,
    });
    fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
    expect(screen.queryByText("Respuesta segura")).not.toBeInTheDocument();
    expect(localStorage.length).toBe(0);
  });
  it("renders Supervisor metrics and Tickets without management controls, including direct hashes", async () => {
    history.replaceState(null, "", "#tickets-panel");
    await login(mockFetch(supervisor), supervisor);
    expect(
      screen.getByRole("heading", { name: "Tickets autorizados" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Crear ticket técnico" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "Resumen y chat",
      }),
    );
    await screen.findByText("firewall-demo");
    expect(screen.getByText("12 %")).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "Usuarios" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/DEMOSTRACIÓN/)).toBeVisible();
  });
  it("mounts every administrator panel and keeps native navigation across back/forward", async () => {
    await login(mockFetch(admin), admin);
    const navigation = screen.getByRole("navigation");
    for (const label of [
      "Dispositivos",
      "Alertas",
      "SSID y VLAN",
      "Planos",
      "Puntos de acceso",
      "Interfaces",
      "Clientes",
      "Firewall",
      "Mi red",
      "Tickets",
      "Aprovisionamiento",
      "Auditoría",
      "Usuarios",
      "Estado del sistema",
      "Mi cuenta",
    ]) {
      fireEvent.click(
        within(navigation).getByRole("link", { name: new RegExp("^" + label) }),
      );
      expect(
        within(navigation).getByRole("link", { name: new RegExp("^" + label) }),
      ).toHaveAttribute("aria-current", "page");
    }
    await act(async () => {
      history.replaceState(null, "", "#devices");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(
      within(navigation).getByRole("link", { name: "Dispositivos" }),
    ).toHaveAttribute("aria-current", "page");
    expect(document.querySelectorAll("#ssid-form")).toHaveLength(1);
    fireEvent.click(
      within(navigation).getByRole("link", { name: "Aprovisionamiento" }),
    );
    expect(document.querySelector("#reservations-summary")).toBeVisible();
    expect(document.querySelector("#user-password")).toHaveAttribute(
      "autocomplete",
      "new-password",
    );
  });
  it("clears revealed Wi-Fi when leaving My network and rejects late responses", async () => {
    let resolve;
    const access = new Promise((r) => {
      resolve = r;
    });
    const fetcher = mockFetch(client, (p) =>
      p === "/api/v1/networks/7/access" ? access : undefined,
    );
    await login(fetcher);
    fireEvent.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "Mi red",
      }),
    );
    await waitFor(() =>
      expect(document.querySelector("#support-network").options.length).toBe(2),
    );
    fireEvent.change(document.querySelector("#support-network"), {
      target: { value: "7" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ver acceso Wi-Fi" }));
    fireEvent.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "Resumen y chat",
      }),
    );
    await act(async () =>
      resolve(
        response({
          ssid: "Feria",
          password: "DO-NOT-DISPLAY",
          expires_in: 60,
          qr_data_url: "data:image/png;base64,AA==",
        }),
      ),
    );
    expect(screen.queryByText("DO-NOT-DISPLAY")).not.toBeInTheDocument();
  });
  it("expires on a protected 401 without retrying or refreshing", async () => {
    const fetcher = mockFetch(client, (p) =>
      p === "/api/v1/chat/messages"
        ? response({ detail: "expired" }, 401)
        : undefined,
    );
    await login(fetcher);
    await waitFor(() =>
      expect(document.querySelector("#chat-send")).not.toBeDisabled(),
    );
    fireEvent.change(document.querySelector("#chat-message"), {
      target: { value: "Hola" },
    });
    fireEvent.submit(document.querySelector("#chat-form"));
    await screen.findByRole("heading", { name: "Iniciar sesión" });
    expect(
      fetcher.mock.calls.filter(([p]) => p === "/api/v1/chat/messages"),
    ).toHaveLength(1);
    expect(fetcher.mock.calls.some(([p]) => p === "/auth/refresh")).toBe(false);
  });
  it("keeps technician deep links scoped and never requests global metrics", async () => {
    const technician = {
      ...client,
      roles: ["tecnico"],
      permissions: [
        ...client.permissions,
        "networks:read:details",
        "changes:request",
        "changes:approve",
        "changes:execute",
        "tickets:read:assigned",
        "tickets:manage:assigned",
      ],
    };
    history.replaceState(null, "", "#users");
    const fetcher = mockFetch(technician);
    await login(fetcher, technician);
    await waitFor(()=>expect(location.hash).toBe("#overview"));
    expect(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "Puntos de acceso",
      }),
    ).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "Usuarios" }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([p]) => p.startsWith("/api/v1/monitoring/")),
    ).toBe(false);
    fireEvent.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "Aprovisionamiento",
      }),
    );
    expect(document.querySelector("#reservations-summary")).not.toBeVisible();
  });
});
