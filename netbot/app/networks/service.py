"""Casos de uso del inventario local y sus asignaciones."""
from app.core.errors import NotFound, Conflict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.auth.models import User
from app.auth.access import require_user_permission
from app.auth.service import user_exists
from app.auth.permissions import Permission
from .models import Network, NetworkAssignment
from .schemas import NetworkCreate, NetworkRead

def list_assignments(network_id: int, db: Session, actor: User) -> list[int]:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    if not db.get(Network, network_id):
        raise NotFound("Red no encontrada.")
    return db.scalars(select(NetworkAssignment.user_id).where(
        NetworkAssignment.network_id == network_id).order_by(NetworkAssignment.user_id)).all()


def create_network(payload: NetworkCreate, db: Session, actor: User) -> NetworkRead:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    network = Network(**payload.model_dump())
    db.add(network)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("La red ya está registrada en ese sitio.") from None
    db.refresh(network)
    return NetworkRead.model_validate(network)


def assign_network(network_id: int, user_id: int, db: Session, actor: User) -> None:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    if not db.get(Network, network_id) or not user_exists(db, user_id):
        raise NotFound("Red o usuario no encontrado.")
    if not db.get(NetworkAssignment, (network_id, user_id)):
        db.add(NetworkAssignment(network_id=network_id, user_id=user_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not db.get(NetworkAssignment, (network_id, user_id)):
                raise Conflict("La asignación cambió. Reintenta.") from None


def unassign_network(network_id: int, user_id: int, db: Session, actor: User) -> None:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    assignment = db.get(NetworkAssignment, (network_id, user_id))
    if assignment:
        db.delete(assignment)
        db.commit()
