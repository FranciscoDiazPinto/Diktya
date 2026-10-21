# Chatbot VLAN Reservations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let an authenticated operator or admin reserve in Netbot an existing OPNsense VLAN through a chatbot proposal and an explicit dashboard confirmation, then release it manually.

**Architecture:** Extend the monitoring provider contract with a normalized VLAN inventory from OPNsense and mock providers. Store active/released reservations in Netbot with a database uniqueness constraint on active `(parent_interface, tag)` pairs. The model may read the inventory and prepare a typed proposal; separate authenticated APIs perform confirmation and release after checking permissions and live availability again.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, existing `httpx` OPNsense client, OpenRouter tool calls, vanilla HTML/CSS/ES modules, pytest, Node built-in test runner.

---

## Design Reference

Implement [the approved design](../specs/2026-10-21-chatbot-vlan-reservations-design.md). Do not create or change VLANs in OPNsense. The documented OPNsense `interfaces.vlan_settings` read resources expose VLAN configuration; normalize `if`, `tag`, `descr`, and `vlanif`. Treat `(if, tag)` as the resource identity because OPNsense requires a tag to be unique on its parent interface. SSID is Netbot reservation metadata only.

## File Map

| File | Responsibility |
| --- | --- |
| `netbot/app/monitoring/schemas.py` | Add normalized `VlanInventoryItem`. |
| `netbot/app/monitoring/providers/base.py` | Add VLAN inventory contract. |
| `netbot/app/monitoring/providers/opnsense/mappers.py` | Parse only normalized OPNsense VLAN row fields; reject malformed list responses. |
| `netbot/app/monitoring/providers/opnsense/provider.py` | Read the fixed `vlan_settings/search_item` endpoint. |
| `netbot/app/monitoring/providers/mock.py` | Return stable VLAN inventory for local development and fail closed in outage mode. |
| `netbot/app/monitoring/service.py` | Expose cached normalized inventory. |
| `netbot/app/changes/models.py` | Define reservation history and active-resource uniqueness. |
| `netbot/app/changes/schemas.py` | Define create, read, available VLAN, and proposal contracts. |
| `netbot/app/changes/service.py` | Calculate availability, create confirmed reservations, list active records, and release records. |
| `netbot/app/changes/router.py` | Expose authenticated availability, reservation, and release endpoints. |
| `netbot/migrations/versions/002_vlan_reservations.py` | Create/drop the reservation table and active-resource index. |
| `netbot/migrations/env.py`, `netbot/app/main.py` | Register the new model/router for migrations and app startup. |
| `netbot/app/chat/policy.py`, `tools.py`, `service.py`, `schemas.py`, `router.py` | Add a role-gated proposal tool and return a typed, non-persistent proposal. |
| `netbot/frontend/index.html`, `styles.css`, `app.js` | Render proposal confirmation, active reservations, and manual release controls safely. |
| `netbot/frontend/chat-reservations.mjs` | Isolate pure UI permission/payload/format helpers for Node tests. |
| `netbot/frontend/tests/chat-reservations.test.mjs` | Test the pure UI helpers using Node’s built-in runner. |
| `netbot/tests/test_vlan_inventory.py` | Test normalized mock and OPNsense inventory behavior. |
| `netbot/tests/test_vlan_reservations.py` | Test service validation, persistence, uniqueness, and release. |
| `netbot/tests/test_vlan_reservation_api.py` | Test authentication, permissions, status codes, and race conflicts. |
| `netbot/tests/test_chat_service.py`, `test_chat_tools.py`, `test_chat_api.py` | Test role-specific tools and proposal response behavior. |
| `netbot/README.md`, `netbot/frontend/README.md` | Document setup, capabilities, API, and live OPNsense validation. |

## Task 1: Normalize VLAN inventory from OPNsense and mock providers

**Files:**
- Modify: `netbot/app/monitoring/schemas.py`
- Modify: `netbot/app/monitoring/providers/base.py`
- Modify: `netbot/app/monitoring/providers/opnsense/mappers.py`
- Modify: `netbot/app/monitoring/providers/opnsense/provider.py`
- Modify: `netbot/app/monitoring/providers/mock.py`
- Modify: `netbot/app/monitoring/service.py`
- Test: `netbot/tests/monitoring/test_mappers.py`
- Test: `netbot/tests/monitoring/test_opnsense_provider.py`
- Test: `netbot/tests/monitoring/test_mock_provider.py`
- Test: `netbot/tests/test_vlan_inventory.py`

- [x] **Step 1: Add failing parser and provider contract tests**

Test a valid OPNsense search response whose `rows` contain `if`, numeric-string `tag`, `descr`, and `vlanif`; assert normalized objects expose only `parent_interface`, `tag`, `description`, and `interface_name`. Test empty rows, malformed top-level payloads, out-of-range tags, missing parent interface, provider timeout/401/404, mock healthy inventory, and mock outage behavior.

```python
async def test_opnsense_vlan_search_normalizes_resource_fields():
    provider = build({paths.PATH_VLAN_SEARCH: {"rows": [
        {"if": "igc1", "tag": "20", "descr": "Evento", "vlanif": "vlan01"}
    ]}})

    result = await provider.get_vlan_inventory()

    assert result.data == [VlanInventoryItem(
        parent_interface="igc1", tag=20, description="Evento", interface_name="vlan01"
    )]
    assert result.issues == []
```

- [x] **Step 2: Run the focused tests and confirm the missing contract fails**

Run from `netbot/`:

```bash
pytest tests/test_vlan_inventory.py tests/monitoring/test_mappers.py tests/monitoring/test_opnsense_provider.py tests/monitoring/test_mock_provider.py -q
```

Expected before implementation: failures for the absent schema/provider method and endpoint constant.

- [x] **Step 3: Add the normalized model and provider contract**

Add a frozen model in `monitoring/schemas.py`:

```python
class VlanInventoryItem(NetbotModel):
    parent_interface: str = Field(min_length=1, max_length=64)
    tag: int = Field(ge=1, le=4094)
    description: str | None = Field(default=None, max_length=160)
    interface_name: str | None = Field(default=None, max_length=64)
```

Add `get_vlan_inventory() -> CollectionResult[list[VlanInventoryItem]]` to `NetworkMonitoringProvider`; implement it for both providers. Add `PATH_VLAN_SEARCH = "/api/interfaces/vlan_settings/search_item"` and use only `OPNsenseClient.get_json()` with GET. In `mappers.py`, parse the documented `rows` structure, use the existing integer/string normalization helpers, and raise `ProviderInvalidResponseError` if the response is not a valid row list or a row has no valid parent/tag. Do not return the upstream JSON.

The mock provider returns deterministic existing resources `(igc1, 20)` and `(igc1, 30)` for healthy/degraded scenarios; outage returns `data=None` with a sanitized connection issue.

- [x] **Step 4: Expose inventory through `MonitoringService` and run focused tests**

Add `get_vlan_inventory()` to `MonitoringService`, using its existing `_cached()` single-flight/cache behavior. Run the command from Step 2 and expect all focused tests to pass, including timeout and malformed-response cases.

- [x] **Step 5: Commit the inventory slice**

```bash
git add netbot/app/monitoring netbot/tests/test_vlan_inventory.py netbot/tests/monitoring
git commit -m "feat: read normalized OPNsense VLAN inventory"
```

## Task 2: Store and operate local VLAN reservations

**Files:**
- Create: `netbot/app/changes/models.py`
- Create: `netbot/app/changes/schemas.py`
- Create: `netbot/app/changes/service.py`
- Create: `netbot/migrations/versions/002_vlan_reservations.py`
- Modify: `netbot/migrations/env.py`
- Modify: `netbot/app/main.py`
- Test: `netbot/tests/test_vlan_reservations.py`

- [x] **Step 1: Write failing persistence and lifecycle tests**

Use the existing `db_session` fixture. Cover successful create with server-supplied user ID; rejection if the VLAN is absent from current inventory; rejection of an already-active `(parent_interface, tag)`; reuse after release; retention of the old released row; and release metadata (`released_by_id`, `released_at`). Verify event, purpose, and SSID are trimmed and validated. Add a database-level test proving two active rows with the same interface/tag violate uniqueness while a released row may coexist.

- [x] **Step 2: Run the reservation tests and confirm they fail for missing models/service**

```bash
pytest tests/test_vlan_reservations.py -q
```

Expected before implementation: import errors for `VlanReservation` and `VlanReservationService`.

- [x] **Step 3: Define reservation models and schemas**

Create a `VlanReservation` SQLAlchemy model with:

- resource identity: `parent_interface`, `tag`, plus display snapshot `description` and `interface_name`;
- request metadata: `event_name`, `purpose`, `ssid`;
- lifecycle: `status` (`reserved` or `released`), `requested_by_id`, `created_at`, nullable `released_by_id`, nullable `released_at`;
- a unique partial index for `(parent_interface, tag)` where `status = 'reserved'`, using both `sqlite_where` and `postgresql_where` so local tests and deployment enforce the same rule.

Create strict Pydantic models with extra fields forbidden. `VlanReservationCreate` accepts only the resource identity and three user-entered metadata fields; the authenticated user, status, and timestamps are never client-controlled. `VlanReservationRead` includes server-owned audit fields.

- [x] **Step 4: Add the migration and register the model**

Create Alembic revision `002_vlan_reservations`, with `down_revision = "001_authentication_roles"`; add the table, foreign keys to `users`, and active partial index. Downgrade drops the index then table. Import `changes.models` in `migrations/env.py` for metadata and in application startup before `Base.metadata.create_all()`.

- [x] **Step 5: Implement service operations and verify them**

Implement `VlanReservationService(monitoring_service, db_session)` with these methods:

```python
async def available_vlans(self) -> list[AvailableVlan]: ...
async def create(self, data: VlanReservationCreate, actor: User) -> VlanReservationRead: ...
def list_active(self) -> list[VlanReservationRead]: ...
def release(self, reservation_id: int, actor: User) -> VlanReservationRead: ...
```

`available_vlans()` fails closed if the inventory is unavailable and subtracts all active local reservations by exact `(parent_interface, tag)`. `create()` performs a fresh inventory read before adding the row, commits inside a transaction, and converts the partial-index `IntegrityError` to `VlanAlreadyReserved` after rollback. `release()` only transitions an active row, records actor and UTC time, and returns a controlled not-found/already-released error without deleting history.

Run `pytest tests/test_vlan_reservations.py -q`; expect all lifecycle, uniqueness, and availability tests to pass.

- [x] **Step 6: Verify migration upgrade/downgrade on SQLite**

Run with an isolated temporary database URL:

```bash
DATABASE_URL=sqlite:///./test-vlan-migration.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite:///./test-vlan-migration.db .venv/bin/alembic downgrade 001_authentication_roles
```

Expected: both commands exit 0; the first creates the reservation table/index and the second removes them. Delete `test-vlan-migration.db` and its journal files after verification.

- [x] **Step 7: Commit persistence and lifecycle**

```bash
git add netbot/app/changes netbot/app/main.py netbot/migrations netbot/tests/test_vlan_reservations.py
git commit -m "feat: persist VLAN reservations with release history"
```

## Task 3: Expose authenticated VLAN reservation APIs

**Files:**
- Create: `netbot/app/changes/router.py`
- Modify: `netbot/app/main.py`
- Test: `netbot/tests/test_vlan_reservation_api.py`
- Modify: `netbot/tests/conftest.py` only if a reusable service override fixture is needed.

- [x] **Step 1: Write failing endpoint and authorization tests**

Cover unauthenticated 401; `visor` may GET the authenticated VLAN options but receives 403 for reservation list/create/release; `operador` and `admin` can list, create, and release; invalid body returns 422; missing inventory returns controlled 503; VLAN no longer present or already reserved returns 409; unknown reservation returns 404. Assert each rejected request leaves the database unchanged.

- [x] **Step 2: Run API tests and confirm the route is absent**

```bash
pytest tests/test_vlan_reservation_api.py -q
```

Expected before implementation: route-not-found or import failures.

- [x] **Step 3: Add the changes router and fixed endpoints**

Register `router = APIRouter(prefix="/changes", tags=["changes"])` under `/api/v1`. Add:

- `GET /vlan-options`, protected by `MONITORING_READ`;
- `GET /vlan-reservations`, `POST /vlan-reservations`, and `POST /vlan-reservations/{reservation_id}/release`, each protected by `VLAN_RESERVE`.

Inject the existing `MonitoringServiceDep`, SQLAlchemy `Session` from `get_db`, and current `User`. Map provider unavailable to 503, concurrent/removed VLAN conflicts to 409, unknown reservation to 404, and validation failures to 422. The request body must not accept actor IDs or lifecycle fields.

- [x] **Step 4: Run API, auth, and migration-adjacent tests**

```bash
pytest tests/test_vlan_reservation_api.py tests/test_auth_api.py tests/test_security.py -q
```

Expected: all role and endpoint cases pass; existing authentication tests remain green.

- [x] **Step 5: Commit the API slice**

```bash
git add netbot/app/changes/router.py netbot/app/main.py netbot/tests/test_vlan_reservation_api.py
git commit -m "feat: expose authorized VLAN reservation endpoints"
```

## Task 4: Let the chatbot prepare a typed, non-persistent proposal

**Files:**
- Modify: `netbot/app/chat/schemas.py`
- Modify: `netbot/app/chat/policy.py`
- Modify: `netbot/app/chat/tools.py`
- Modify: `netbot/app/chat/service.py`
- Modify: `netbot/app/chat/router.py`
- Test: `netbot/tests/test_chat_tools.py`
- Test: `netbot/tests/test_chat_service.py`
- Test: `netbot/tests/test_chat_api.py`

- [x] **Step 1: Add failing role-filter and proposal tests**

Assert `visor` receives only read tools and never receives a reservation proposal tool; `operador` and `admin` receive the proposal tool; every invocation still checks `MONITORING_READ` or `VLAN_RESERVE` server-side. Test proposal arguments for exact current available VLAN, event, purpose, and SSID; reject a reserved/nonexistent resource; assert preparation does not insert into the database. Test the chat response includes the exact typed proposal fields and that a normal response serializes `reservation_proposal: null`; update existing exact response assertions accordingly.

- [x] **Step 2: Run the focused chat tests and confirm the proposal contract is missing**

```bash
pytest tests/test_chat_tools.py tests/test_chat_service.py tests/test_chat_api.py -q
```

Expected before implementation: failures for role-filtered tools and `reservation_proposal`.

- [x] **Step 3: Add a typed proposal response and permission-filtered tools**

Add `VlanReservationProposal` with `parent_interface`, `tag`, `description`, `interface_name`, `event_name`, `purpose`, and `ssid`; add `reservation_proposal: VlanReservationProposal | None = None` to `ChatMessageResponse`. Extend the registry with:

- `get_available_vlans`: read-only, requires `MONITORING_READ`, returns normalized available options;
- `prepare_vlan_reservation`: validates all required proposal fields, checks `VLAN_RESERVE`, verifies the selected resource against the current available inventory, and returns structured data without writing to the DB or OPNsense.

Update `openrouter_tool_definitions(permissions)` to omit tools whose permission the caller lacks. Keep checks in `invoke_tool()` even after filtering. Pass `VlanReservationService` into the chat service and preserve the proposal in its final `ChatMessageResponse`. Update the fixed Spanish policy to say a proposal is not a reservation and the assistant must never claim success until the confirmation API returns success.

- [x] **Step 4: Re-run chat tests and verify persistence boundary**

Run the focused test command from Step 2. Expect all tests to pass, with no provider tool capable of creating or releasing a reservation.

- [x] **Step 5: Commit the chat proposal slice**

```bash
git add netbot/app/chat netbot/tests/test_chat_tools.py netbot/tests/test_chat_service.py netbot/tests/test_chat_api.py
git commit -m "feat: prepare role-gated VLAN reservation proposals in chat"
```

## Task 5: Add explicit confirmation and release controls to the dashboard

**Files:**
- Modify: `netbot/frontend/index.html`
- Modify: `netbot/frontend/styles.css`
- Modify: `netbot/frontend/app.js`
- Create: `netbot/frontend/chat-reservations.mjs`
- Create: `netbot/frontend/tests/chat-reservations.test.mjs`

- [x] **Step 1: Write failing Node tests for frontend role and request helpers**

Use `node:test` and `node:assert/strict` to cover permission display and request payload formation:

```javascript
import test from 'node:test';
import assert from 'node:assert/strict';
import { canReserveVlans, reservationPayload } from '../chat-reservations.mjs';

test('only operator and admin see reservation controls', () => {
  assert.equal(canReserveVlans(['visor']), false);
  assert.equal(canReserveVlans(['operador']), true);
  assert.equal(canReserveVlans(['admin']), true);
});

test('reservation payload contains only the approved fields', () => {
  assert.deepEqual(reservationPayload({
    parent_interface: 'igc1', tag: '20', event_name: 'Feria',
    purpose: 'Invitados', ssid: 'Evento',
  }), {
    parent_interface: 'igc1', tag: 20, event_name: 'Feria',
    purpose: 'Invitados', ssid: 'Evento',
  });
});
```

- [x] **Step 2: Run Node tests and confirm they fail because the module is absent**

```bash
node --test frontend/tests/chat-reservations.test.mjs
```

Expected before implementation: module-not-found failures.

- [x] **Step 3: Build accessible proposal and active-reservation UI**

Implement/export `canReserveVlans(roles)` and `reservationPayload(formValues)` from `chat-reservations.mjs`. Convert the dashboard script to an ES module and import these helpers. Use the authenticated `/auth/me` roles for display only; API permissions remain authoritative. When a chat response includes `reservation_proposal`, render a text-only summary with **Confirmar** and **Cancelar** buttons using DOM elements and `textContent`. Confirm posts only the approved fields to `/api/v1/changes/vlan-reservations`; on success, show a success state and refresh the active reservation list. Cancel removes the proposal without an API write. For `operador`/`admin`, list active reservations and add a manual **Liberar** button calling `POST /api/v1/changes/vlan-reservations/{id}/release`. Disable controls during requests, show recoverable errors, and clear chat proposals and reservation state on logout. Do not render OPNsense or model strings with `innerHTML`.

- [x] **Step 4: Run helper tests and inspect the browser flow**

Run:

```bash
node --test frontend/tests/chat-reservations.test.mjs
node --input-type=module --check < frontend/app.js
```

Expected: all Node tests pass and the app script parses as an ES module. Then use a local static server and mocked chat/changes API responses to verify: visor cannot see action controls; operator sees a proposal and must click confirm; cancel creates no request; confirm refreshes reservations; manual release updates the list; logout clears proposal state; HTML-like values render as plain text.

- [x] **Step 5: Commit the dashboard slice**

```bash
git add netbot/frontend
 git commit -m "feat: add explicit VLAN reservation controls to chat panel"
```

## Task 6: Document and verify the complete flow

**Files:**
- Modify: `netbot/README.md`
- Modify: `netbot/frontend/README.md`
- Modify: `netbot/docs/superpowers/specs/2026-10-21-chatbot-vlan-reservations-design.md`
- Modify: `netbot/docs/superpowers/plans/2026-10-21-chatbot-vlan-reservations.md`

- [x] **Step 1: Document setup, roles, endpoints, and external processing**

Update backend/frontend READMEs to explain that `MONITORING_PROVIDER=opnsense` is needed to use actual OPNsense inventory; mock mode exposes only synthetic VLANs. Document `GET /api/v1/changes/vlan-options`, list/create/release endpoints, `VLAN_RESERVE` roles, manual release, the explicit confirmation boundary, and that the SSID is metadata only. State that chat input/history and relevant VLAN data are sent to OpenRouter, and that no OPNsense write call occurs.

- [x] **Step 2: Record implementation and live integration limitations**

Mark plan checkboxes as tasks complete after each task. Update the design document with final route names and test evidence. State clearly that `httpx.MockTransport` validates the adapter offline, while the deployed OPNsense API version must still be checked with a real authorized read-only account before relying on live inventory.

- [x] **Step 3: Run all backend and frontend checks**

From `netbot/` run:

```bash
pytest -q
node --test frontend/tests/chat-reservations.test.mjs
node --check frontend/app.js
```

Expected: all tests pass. Also run `git diff --check` and the filename-only secret scan:

```bash
git diff --check
rg -l --hidden 'sk-or-v1-[[:alnum:]]+|OPENROUTER_API_KEY=[^[:space:]]+' . --glob '!**/.git/**' --glob '!*.md' --glob '!*.example' --glob '!*.lock' || true
```

Expected: no whitespace errors and no secret-file paths. Delete any `test-auth.db`, migration database, or journal files created by verification.

- [x] **Step 4: Commit documentation and verified plan**

```bash
git add netbot/README.md netbot/frontend/README.md netbot/docs/superpowers/specs/2026-10-21-chatbot-vlan-reservations-design.md netbot/docs/superpowers/plans/2026-10-21-chatbot-vlan-reservations.md
git commit -m "docs: document chatbot VLAN reservation flow"
```

## Plan Self-Review

- **Spec coverage:** inventory normalization, OPNsense failure behavior, `(parent_interface, tag)` identity, role checks, proposal without persistence, explicit confirmation, atomic active uniqueness, manual release/history, safe rendering, OpenRouter disclosure, and real-device validation each appear in Tasks 1–6.
- **Boundaries:** writes are limited to the Netbot reservation table. No OPNsense write action or arbitrary LLM tool is added.
- **Type consistency:** `VlanInventoryItem`, `VlanReservationCreate`, `VlanReservationRead`, `AvailableVlan`, `VlanReservationProposal`, `VlanReservationService`, and `ChatMessageResponse.reservation_proposal` are introduced before later use.
- **No placeholders:** route operations, permissions, data fields, test commands, expected behavior, error cases, and commit steps are specified.
- **External integration:** fixture tests are deterministic and offline; live API verification is documented as a required pre-deployment check because no OPNsense credentials/device are available in this worktree.


## Estado de ejecución

Tareas implementadas y verificadas en el worktree de la rama `feature/chatbot-vlan-reservations`. Verificaciones: `pytest -q` (152 passed), Node tests (2 passed), sintaxis ES module, Alembic upgrade/downgrade SQLite temporal y `git diff --check`. No se hizo una prueba visual interactiva en navegador; debe ejecutarse al integrar en el entorno de desarrollo. La lectura contra una instancia OPNsense real también queda pendiente por no disponer de una cuenta/dispositivo en este entorno.
