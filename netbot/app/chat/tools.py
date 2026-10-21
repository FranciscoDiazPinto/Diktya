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


ToolExecutor = Callable[
    ["MonitoringService", BaseModel], Awaitable[MonitoringResponse[Any]]
]


@dataclass(frozen=True, slots=True)
class MonitoringTool:
    name: str
    description: str
    arguments_model: type[BaseModel]
    required_permission: Permission
    executor: ToolExecutor

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


_tools = {
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
}
TOOL_REGISTRY: Mapping[str, MonitoringTool] = MappingProxyType(_tools)


def openrouter_tool_definitions() -> list[dict[str, Any]]:
    return [tool.provider_definition() for tool in TOOL_REGISTRY.values()]


async def invoke_tool(
    name: str,
    arguments: dict[str, Any],
    service: MonitoringService,
    permissions: frozenset[Permission],
) -> dict[str, Any]:
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

    response = await tool.executor(service, validated_arguments)
    result = response.model_dump(mode="json")
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > MAX_TOOL_RESULT_CHARS:
        raise ChatToolError("El resultado de monitoreo es demasiado grande para el chat.")
    return result
