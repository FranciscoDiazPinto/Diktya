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
  it("prepares and confirms selected VLAN batch rows from provisioning", async () => {
    const changes = "/api/v1/changes";
    const batch = {
      id: "batch-1", status: "preview", revision: "reviewed",
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      rows: [{row_number: 1, ssid: "Invitados", target_vlan: 30, impact: "Reconexión breve.", errors: []}],
      results: [],
    };
    const fetcher = mockFetch(admin, path => {
      if (path === `${changes}/wifi-scopes`) return response([{id: 7, name: "Feria"}]);
      if (path === `${changes}/wifi-scopes/7/options`) {
        return response({networks: [{id: "net-30", tag: 30, parent_interface: "igc1"}],
                         security_profiles: [], aps: [], simulated: false});
      }
      if (path === `${changes}/wifi-scopes/7/ssids`) return response([{id: "ssid-1", ssid: "Invitados"}]);
      if (path === `${changes}/ssid-vlan-batches?scope_id=7`) return response([]);
      if (path === `${changes}/ssid-vlan-batches/preview`) return response(batch);
      if (path === `${changes}/ssid-vlan-batches/batch-1/confirm`) return response({...batch, status: "confirmed"});
    });
    history.replaceState(null, "", "#provisioning");
    await login(fetcher, admin);
    const scope = document.querySelector("#changes-scope");
    await waitFor(() => expect(scope.options).toHaveLength(2));
    fireEvent.change(scope, {target: {value: "7"}});
    const add = screen.getByRole("button", {name: "Agregar selección al lote"});
    await waitFor(() => expect(add).toBeEnabled());
    fireEvent.change(document.querySelector("#vlan-change-ssid"), {target: {value: "ssid-1"}});
    fireEvent.change(document.querySelector("#vlan-change-network"), {target: {value: "net-30"}});
    fireEvent.change(document.querySelector("#vlan-change-purpose"), {target: {value: "Prueba"}});
    fireEvent.click(add);
    fireEvent.click(screen.getByRole("button", {name: "Revisar lote"}));
    const row = await screen.findByRole("checkbox", {name: /Fila 1: Invitados/});
    const confirm = screen.getByRole("button", {name: "Confirmar filas del lote"});
    expect(confirm).toBeDisabled();
    fireEvent.click(row);
    fireEvent.click(confirm);
    await screen.findByText(/Aprobación registrada. Actualiza el estado/);
    const [, request] = fetcher.mock.calls.find(([path]) => path.endsWith("/batch-1/confirm"));
    expect(JSON.parse(request.body)).toEqual({revision: "reviewed", row_numbers: [1]});
  });

  it("requires a reviewed closure revision before submitting", async () => {
    const base = "/api/v1/changes/wifi-scopes";
    const preview = {
      event_name: "Feria de prueba",
      accepts_changes: true,
      pending: [{kind: "ssid", id: "plan-1", status: "confirmed"}],
      blockers: [],
      review: [],
      linked_reservations: [{id: 7, releasable: true}],
      revision: "reviewed",
    };
    const fetcher = mockFetch(admin, path => {
      if (path === base) return response([{id: 7, name: "Feria de prueba"}]);
      if (path === `${base}/7/options`) {
        return response({networks: [], security_profiles: [], aps: [], simulated: true});
      }
      if (path === `${base}/7/closure-preview`) return response(preview);
      if (path === `${base}/7/closure-confirm`) {
        return response({...preview, accepts_changes: false, pending: [], linked_reservations: []});
      }
    });
    history.replaceState(null, "", "#provisioning");
    await login(fetcher, admin);
    const card = screen.getByRole("region", {name: "Cierre de feria"});
    expect(within(card).queryByRole("button", {name: "Confirmar cierre del ámbito"})).toBeNull();
    const scope = document.querySelector("#ssid-scope");
    await waitFor(() => expect(scope.options).toHaveLength(2));
    fireEvent.change(scope, {target: {value: "7"}});
    const review = within(card).getByRole("button", {name: "Revisar cierre del ámbito"});
    await waitFor(() => expect(review).toBeEnabled());
    fireEvent.click(review);
    await within(card).findByText("Reserva 7 · Se liberará al confirmar");
    expect(fetcher.mock.calls.some(([path]) => path.endsWith("/closure-confirm"))).toBe(false);
    fireEvent.click(within(card).getByRole("button", {name: "Confirmar cierre del ámbito"}));
    await screen.findByText("Cambios bloqueados para esta feria.");
    const [, request] = fetcher.mock.calls.find(([path]) => path.endsWith("/closure-confirm"));
    expect(JSON.parse(request.body)).toEqual({revision: "reviewed"});
  });

  it("opens the next fair only from a reviewed closed scope and assigns selected staff", async () => {
    const base = "/api/v1/changes/wifi-scopes";
    const administrator = {...admin, permissions: [...admin.permissions, "users:read"]};
    const fetcher = mockFetch(administrator, path => {
      if (path === base) return response([{id: 7, name: "Feria anterior"}]);
      if (path === `${base}/7/options`) {
        return response({networks: [], security_profiles: [], aps: [], accepts_changes: false});
      }
      if (path === `${base}/7/closure-preview`) {
        return response({event_name: "Feria anterior", accepts_changes: false, revision: "reviewed-closed",
                         pending: [], blockers: [], review: [], linked_reservations: []});
      }
      if (path === "/admin/users") return response([{
        id: 8, email: "staff@example.com", full_name: "Técnico de prueba", is_active: true,
        permissions: ["changes:request"],
      }]);
      if (path === `${base}/7/successor`) return response({id: 9, name: "Feria siguiente"}, 201);
    });
    history.replaceState(null, "", "#provisioning");
    await login(fetcher, administrator);
    const scope = document.querySelector("#ssid-scope");
    await waitFor(() => expect(scope.options).toHaveLength(2));
    fireEvent.change(scope, {target: {value: "7"}});
    const preview = screen.getByRole("button", {name: "Revisar cierre del ámbito"});
    await waitFor(() => expect(preview).toBeEnabled());
    expect(screen.queryByRole("form", {name: "Abrir próxima feria"})).toBeNull();
    fireEvent.click(preview);
    const form = await screen.findByRole("form", {name: "Abrir próxima feria"});
    const staff = await within(form).findByRole("checkbox", {name: /Técnico de prueba/});
    fireEvent.change(within(form).getByLabelText(/Nombre del ámbito/), {target: {value: "Feria siguiente"}});
    fireEvent.change(within(form).getByLabelText(/Nombre del evento/), {target: {value: "Nuevo evento"}});
    fireEvent.click(staff);
    fireEvent.submit(form);
    await screen.findByText(/Ámbito «Feria siguiente» creado/);
    const [, request] = fetcher.mock.calls.find(([path]) => path.endsWith("/7/successor"));
    expect(JSON.parse(request.body)).toEqual({
      name: "Feria siguiente", event_name: "Nuevo evento", revision: "reviewed-closed", user_ids: [8],
    });
    expect([...scope.options].map(option => option.value)).toContain("9");
    expect([...document.querySelector("#changes-scope").options].map(option => option.value)).toContain("9");
  });

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
