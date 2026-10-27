"""Roles predeterminados y comprobación de permisos."""

from dataclasses import dataclass
from enum import Enum
from typing import AbstractSet

from .permissions import Permission


class RoleName(str, Enum):
    ADMIN = "admin"
    OPERADOR = "operador"
    VISOR = "visor"
    CLIENTE = "cliente"
    TECNICO = "tecnico"


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
        "Técnico: acceso limitado a las redes asignadas.",
        frozenset(
            {
                Permission.CHAT_USE,
                Permission.NETWORKS_READ_OWN,
                Permission.NETWORKS_READ_DETAILS,
                Permission.WIFI_ACCESS_READ_OWN,
                Permission.TICKETS_CREATE_OWN,
                Permission.TICKETS_READ_OWN,
                Permission.TICKETS_READ_ASSIGNED,
                Permission.TICKETS_MANAGE_ASSIGNED,
            }
        ),
    ),
    RoleName.VISOR: Role(
        RoleName.VISOR,
        "Consulta el estado global de la red y cambios.",
        frozenset(
            {
                Permission.MONITORING_READ,
                Permission.CHAT_USE,
                Permission.CHANGES_READ,
            }
        ),
    ),
}

# Operador es el nombre anterior del rol técnico. Ninguno recibe permisos globales.
DEFAULT_ROLES[RoleName.TECNICO] = Role(
    RoleName.TECNICO, "Técnico de las redes asignadas.",
    DEFAULT_ROLES[RoleName.OPERADOR].permissions,
)
DEFAULT_ROLES[RoleName.CLIENTE] = Role(
    RoleName.CLIENTE, "Atención y consulta de sus propias redes.",
    frozenset({Permission.CHAT_USE, Permission.NETWORKS_READ_OWN,
               Permission.WIFI_ACCESS_READ_OWN, Permission.TICKETS_CREATE_OWN, Permission.TICKETS_READ_OWN}),
)


def has_permission(roles: AbstractSet[RoleName], permission: Permission) -> bool:
    """Indica si alguno de los roles asignados concede el permiso."""
    return any(
        permission in DEFAULT_ROLES[role].permissions
        for role in roles
        if role in DEFAULT_ROLES
    )


def effective_permissions(user) -> frozenset[Permission]:
    return frozenset(
        permission
        for role in user.roles
        if role.name in RoleName._value2member_map_
        for permission in DEFAULT_ROLES[RoleName(role.name)].permissions
    )
