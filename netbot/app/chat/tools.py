"""Herramientas de monitoreo disponibles para el modelo."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.auth.permissions import Permission
from app.monitoring.schemas import FirewallAction, MonitoringResponse
from app.changes.schemas import VlanReservationCreate
from app.changes.service import InventoryUnavailable, VlanConflict, VlanReservationService
from app.tickets.schemas import TicketProposal
from app.changes.ssid_schemas import SsidProposal

if TYPE_CHECKING:
    from app.monitoring.service import MonitoringService
    from .support import CustomerSupport

MAX_TOOL_RESULT_CHARS = 12_000


class ChatToolError(ValueError):
    """El modelo pidió una herramienta o argumentos que la aplicación no admite."""


class ChatToolPermissionError(ChatToolError):
    """El usuario no cuenta con el permiso requerido por la herramienta."""


class EmptyToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FirewallEventsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=100)
    action: FirewallAction | None = None


class VlanProposalArguments(VlanReservationCreate):
    pass


class ScopeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_id: int = Field(gt=0)


class NetworkArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    network_id: int = Field(gt=0)


ToolExecutor = Callable[
    ["MonitoringService", BaseModel], Awaitable[MonitoringResponse[Any]]
]


@dataclass(frozen=True, slots=True)
class MonitoringTool:
    name: str
    description: str
    arguments_model: type[BaseModel]
    required_permission: Permission
    executor: ToolExecutor | None

    def provider_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }


async def _get_system(service: MonitoringService, _: BaseModel) -> MonitoringResponse[Any]:
    return await service.get_system()


async def _get_interfaces(
    service: MonitoringService, _: BaseModel
) -> MonitoringResponse[Any]:
    return await service.get_interfaces()


async def _get_clients(service: MonitoringService, _: BaseModel) -> MonitoringResponse[Any]:
    return await service.get_clients()


async def _get_firewall_stats(
    service: MonitoringService, _: BaseModel
) -> MonitoringResponse[Any]:
    return await service.get_firewall_stats()


async def _get_firewall_events(
    service: MonitoringService, arguments: BaseModel
) -> MonitoringResponse[Any]:
    assert isinstance(arguments, FirewallEventsArguments)
    return await service.get_firewall_events(
        limit=arguments.limit, action=arguments.action
    )


async def _get_available_vlans(service, _: BaseModel):
    inventory = await service.get_vlan_inventory()
    if inventory.data is None:
        return {"status": "unavailable", "data": None}
    return {"status": inventory.status.value, "data": [item.model_dump() for item in inventory.data]}


_tools = {
    "get_wifi_scopes": MonitoringTool("get_wifi_scopes", "Lista ámbitos de aprovisionamiento explícitamente autorizados; no inventes IDs.", EmptyToolArguments, Permission.CHANGES_REQUEST, None),
    "get_wifi_scope_options": MonitoringTool("get_wifi_scope_options", "Consulta AP, redes/VLAN existentes y perfiles de seguridad permitidos para un ámbito. Indica si son simulados.", ScopeArguments, Permission.CHANGES_REQUEST, None),
    "prepare_ssid_creation": MonitoringTool("prepare_ssid_creation", "Valida una propuesta de SSID nuevo con AP explícitos y VLAN existente. No guarda, confirma ni ejecuta. Usa el panel para revisión y aprobación. Nunca pidas contraseñas.", SsidProposal, Permission.CHANGES_REQUEST, None),
    "get_network_status": MonitoringTool(
        "get_network_status", "Consulta el estado comprobable de una red autorizada; distingue falta de datos y fallas. No garantiza Wi-Fi ni Internet.",
        NetworkArguments, Permission.NETWORKS_READ_OWN, None,
    ),
    "offer_wifi_access": MonitoringTool(
        "offer_wifi_access", "Ofrece un botón protegido para ver el acceso Wi-Fi de una red propia. Nunca devuelve contraseñas al modelo.",
        NetworkArguments, Permission.WIFI_ACCESS_READ_OWN, None,
    ),
    "prepare_support_ticket": MonitoringTool(
        "prepare_support_ticket", "Prepara un ticket para una red propia. No lo guarda; el usuario confirma en el panel. No incluyas contraseñas.",
        TicketProposal, Permission.TICKETS_CREATE_OWN, None,
    ),
    "list_support_tickets": MonitoringTool(
        "list_support_tickets", "Consulta los últimos cinco tickets autorizados dentro de esta conversación.",
        EmptyToolArguments, Permission.TICKETS_READ_OWN, None,
    ),
    "get_assigned_networks": MonitoringTool(
        name="get_assigned_networks",
        description="Consulta únicamente las redes autorizadas en esta conversación. Es inventario local, no telemetría ni credenciales.",
        arguments_model=EmptyToolArguments,
        required_permission=Permission.NETWORKS_READ_OWN,
        executor=None,  # Se resuelve con contexto filtrado, sin llamar al proveedor global.
    ),
    "get_system": MonitoringTool(
        name="get_system",
        description="Consulta métricas actuales del sistema de red administrado por Netbot.",
        arguments_model=EmptyToolArguments,
        required_permission=Permission.MONITORING_READ,
        executor=_get_system,
    ),
    "get_interfaces": MonitoringTool(
        name="get_interfaces",
        description="Consulta estado y contadores de las interfaces de red.",
        arguments_model=EmptyToolArguments,
        required_permission=Permission.MONITORING_READ,
        executor=_get_interfaces,
    ),
    "get_clients": MonitoringTool(
        name="get_clients",
        description="Consulta clientes DHCP registrados por el monitoreo.",
        arguments_model=EmptyToolArguments,
        required_permission=Permission.MONITORING_READ,
        executor=_get_clients,
    ),
    "get_firewall_stats": MonitoringTool(
        name="get_firewall_stats",
        description="Consulta estadísticas actuales del firewall.",
        arguments_model=EmptyToolArguments,
        required_permission=Permission.MONITORING_READ,
        executor=_get_firewall_stats,
    ),
    "get_firewall_events": MonitoringTool(
        name="get_firewall_events",
        description="Consulta eventos recientes del firewall, opcionalmente filtrados por acción.",
        arguments_model=FirewallEventsArguments,
        required_permission=Permission.MONITORING_READ,
        executor=_get_firewall_events,
    ),
    "get_available_vlans": MonitoringTool(
        name="get_available_vlans",
        description="Consulta el inventario de VLAN existentes en OPNsense.",
        arguments_model=EmptyToolArguments,
        required_permission=Permission.MONITORING_READ,
        executor=_get_available_vlans,
    ),
    "prepare_vlan_reservation": MonitoringTool(
        name="prepare_vlan_reservation",
        description="Prepara una propuesta de reserva local; no la confirma ni modifica OPNsense.",
        arguments_model=VlanProposalArguments,
        required_permission=Permission.VLAN_RESERVE,
        executor=_get_available_vlans,
    ),
}
TOOL_REGISTRY: Mapping[str, MonitoringTool] = MappingProxyType(_tools)


def openrouter_tool_definitions(permissions: frozenset[Permission] | None = None) -> list[dict[str, Any]]:
    tools = list(TOOL_REGISTRY.values())
    if permissions is not None:
        tools = [tool for tool in tools if tool.required_permission in permissions]
    return [tool.provider_definition() for tool in tools]


async def invoke_tool(
    name: str,
    arguments: dict[str, Any],
    service: MonitoringService,
    permissions: frozenset[Permission],
    reservation_service: VlanReservationService | None = None,
    networks: list[dict] | None = None,
    customer_support: CustomerSupport | None = None,
    ssid_context=None,
) -> dict[str, Any]:
    if name in {"get_wifi_scopes", "get_wifi_scope_options", "prepare_ssid_creation"}:
        if Permission.CHANGES_REQUEST not in permissions:
            raise ChatToolPermissionError("Permiso insuficiente para proponer SSID.")
        if ssid_context is None:
            raise ChatToolError("Servicio de planes SSID no disponible.")
        from app.core.errors import ApplicationError
        try:
            args = TOOL_REGISTRY[name].arguments_model.model_validate(arguments)
            service, actor = ssid_context
            if name == "get_wifi_scopes": result = {"data":service.scopes(actor)}
            elif name == "get_wifi_scope_options": result = (await service.options(actor,args.scope_id))[0]
            else: result = await service.propose(actor,args)
        except ValidationError:
            raise ChatToolError("Argumentos SSID inválidos.") from None
        except ApplicationError as exc:
            # Un fallo no concede datos ni persiste una propuesta en el bucle LLM.
            return {"status":"unavailable", "message":exc.detail}
        if len(json.dumps(result,ensure_ascii=False)) > MAX_TOOL_RESULT_CHARS:
            raise ChatToolError("Reduce el ámbito de consulta SSID.")
        return result
    if name == "prepare_vlan_reservation":
        if Permission.VLAN_RESERVE not in permissions:
            raise ChatToolPermissionError("Permiso insuficiente para preparar una reserva.")
        if reservation_service is None:
            raise ChatToolError("Servicio de reservas no disponible.")
        try:
            arguments_model = VlanProposalArguments.model_validate(arguments)
            available = await reservation_service.available_vlans()
        except (ValidationError, InventoryUnavailable):
            raise ChatToolError("Propuesta de reserva inválida o inventario no disponible.") from None
        candidate = next((item for item in available if
                          (item.parent_interface, item.tag) ==
                          (arguments_model.parent_interface, arguments_model.tag)), None)
        if candidate is None:
            raise ChatToolError("La VLAN seleccionada no está disponible.")
        return {**candidate.model_dump(), "event_name": arguments_model.event_name,
                "purpose": arguments_model.purpose, "ssid": arguments_model.ssid}
    if name == "get_available_vlans":
        if Permission.MONITORING_READ not in permissions:
            raise ChatToolPermissionError("Permiso insuficiente para consultar VLAN.")
        if reservation_service is None:
            raise ChatToolError("Servicio de reservas no disponible.")
        try:
            return {"status": "ok", "data": [item.model_dump() for item in await reservation_service.available_vlans()]}
        except InventoryUnavailable:
            return {"status": "unavailable", "data": None}
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise ChatToolError("Herramienta no disponible.")
    if tool.required_permission not in permissions:
        raise ChatToolPermissionError("Permiso insuficiente para consultar monitoreo.")
    if not isinstance(arguments, dict):
        raise ChatToolError("Argumentos de herramienta inválidos.")
    try:
        validated_arguments = tool.arguments_model.model_validate(arguments)
    except ValidationError:
        raise ChatToolError("Argumentos de herramienta inválidos.") from None

    if name in {"get_network_status", "offer_wifi_access", "prepare_support_ticket", "list_support_tickets"}:
        if customer_support is None:
            raise ChatToolError("Servicio de soporte no disponible.")
        result = await customer_support.invoke(name, validated_arguments.model_dump(), {n["id"] for n in networks or []})
        if len(json.dumps(result, ensure_ascii=False)) > MAX_TOOL_RESULT_CHARS:
            raise ChatToolError("El resultado de soporte es demasiado grande para el chat.")
        return result
    if name == "get_assigned_networks":
        result = {"source": "netbot_inventory", "operational_status": "unknown", "data": networks or []}
        if len(json.dumps(result, ensure_ascii=False)) > MAX_TOOL_RESULT_CHARS:
            raise ChatToolError("El inventario es demasiado grande. Abre una conversación para una red específica.")
        return result
    if tool.executor is None:
        raise ChatToolError("Herramienta sin ejecutor.")
    response = await tool.executor(service, validated_arguments)
    result = response.model_dump(mode="json")
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > MAX_TOOL_RESULT_CHARS:
        raise ChatToolError("El resultado de monitoreo es demasiado grande para el chat.")
    return result
