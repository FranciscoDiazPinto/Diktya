"""Roles predeterminados y comprobación de permisos."""

from dataclasses import dataclass
from enum import StrEnum
from typing import AbstractSet

from .permissions import Permission


class RoleName(StrEnum):
    ADMIN = "admin"
    OPERADOR = "operador"
    VISOR = "visor"


@dataclass(frozen=True)
class Role:
    name: RoleName
    description: str
    permissions: frozenset[Permission]


DEFAULT_ROLES: dict[RoleName, Role] = {
    RoleName.ADMIN: Role(
        RoleName.ADMIN,
        "Administración completa del sistema.",
        frozenset(Permission),
    ),
    RoleName.OPERADOR: Role(
        RoleName.OPERADOR,
        "Monitorea la red y gestiona operaciones e incidencias.",
        frozenset(
            {
                Permission.MONITORING_READ,
                Permission.CHAT_USE,
                Permission.VLAN_RESERVE,
                Permission.CHANGES_READ,
                Permission.CHANGES_REQUEST,
                Permission.CHANGES_EXECUTE,
                Permission.CHANGES_ROLLBACK,
                Permission.TICKETS_READ,
                Permission.TICKETS_MANAGE,
            }
        ),
    ),
    RoleName.VISOR: Role(
        RoleName.VISOR,
        "Consulta el estado de la red, cambios e incidencias.",
        frozenset(
            {
                Permission.MONITORING_READ,
                Permission.CHANGES_READ,
                Permission.TICKETS_READ,
            }
        ),
    ),
}


def has_permission(roles: AbstractSet[RoleName], permission: Permission) -> bool:
    """Indica si alguno de los roles asignados concede el permiso."""
    return any(permission in DEFAULT_ROLES[role].permissions for role in roles)
