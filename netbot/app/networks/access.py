from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from .models import Network, NetworkAssignment
from .schemas import NetworkRead, NetworkSummary


def accessible_networks(db: Session, user: User) -> list[Network]:
    permissions = effective_permissions(user)
    statement = select(Network).order_by(Network.id)
    if Permission.NETWORKS_MANAGE not in permissions:
        if Permission.NETWORKS_READ_OWN not in permissions:
            return []
        statement = statement.join(NetworkAssignment).where(NetworkAssignment.user_id == user.id)
    return list(db.scalars(statement).all())


def require_network(db: Session, user: User, network_id: int) -> Network:
    network = next((n for n in accessible_networks(db, user) if n.id == network_id), None)
    if network is None:
        raise HTTPException(status_code=404, detail="Red no encontrada.")
    return network


def network_read(network: Network, user: User) -> NetworkRead | NetworkSummary:
    schema = NetworkRead if Permission.NETWORKS_READ_DETAILS in effective_permissions(user) else NetworkSummary
    return schema.model_validate(network)
