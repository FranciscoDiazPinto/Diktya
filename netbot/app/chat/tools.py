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

if TYPE_CHECKING:
    from app.monitoring.service import MonitoringService

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
) -> dict[str, Any]:
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
