"""Permisos de la aplicación."""

from enum import Enum


class Permission(str, Enum):
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    ROLES_MANAGE = "roles:manage"
    MONITORING_READ = "monitoring:read"
    CHAT_USE = "chat:use"
    NETWORKS_READ_OWN = "networks:read:own"
    NETWORKS_READ_DETAILS = "networks:read:details"
    NETWORKS_MANAGE = "networks:manage"
    VLAN_RESERVE = "vlan:reserve"
    CHANGES_READ = "changes:read"
    CHANGES_REQUEST = "changes:request"
    CHANGES_APPROVE = "changes:approve"
    CHANGES_EXECUTE = "changes:execute"
    CHANGES_ROLLBACK = "changes:rollback"
    TICKETS_READ = "tickets:read"
    TICKETS_MANAGE = "tickets:manage"
    AGENTS_MANAGE = "agents:manage"
