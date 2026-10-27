from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from .access import accessible_networks, require_network, network_read
from .models import Network, NetworkAssignment
from .schemas import NetworkCreate, NetworkRead, NetworkSummary

router = APIRouter(prefix="/networks", tags=["networks"])
admin_router = APIRouter(prefix="/admin/networks", tags=["network administration"])


@router.get("", response_model=list[NetworkRead | NetworkSummary])
def list_networks(user: User = Depends(require_permission(Permission.NETWORKS_READ_OWN.value)), db: Session = Depends(get_db)):
    return [network_read(n, user) for n in accessible_networks(db, user)]


@router.get("/{network_id}", response_model=NetworkRead | NetworkSummary)
def get_network(network_id: int, user: User = Depends(require_permission(Permission.NETWORKS_READ_OWN.value)), db: Session = Depends(get_db)):
    return network_read(require_network(db, user, network_id), user)


@admin_router.get("/{network_id}/users", response_model=list[int])
def list_assignments(network_id: int, _: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    if not db.get(Network, network_id):
        raise HTTPException(status_code=404, detail="Red no encontrada.")
    return db.scalars(select(NetworkAssignment.user_id).where(
        NetworkAssignment.network_id == network_id).order_by(NetworkAssignment.user_id)).all()


@admin_router.post("", response_model=NetworkRead, status_code=201)
def create_network(payload: NetworkCreate, _: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    network = Network(**payload.model_dump())
    db.add(network)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="La red ya está registrada en ese sitio.") from None
    db.refresh(network)
    return network


@admin_router.put("/{network_id}/users/{user_id}", status_code=204)
def assign_network(network_id: int, user_id: int, _: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    if not db.get(Network, network_id) or not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="Red o usuario no encontrado.")
    if not db.get(NetworkAssignment, (network_id, user_id)):
        db.add(NetworkAssignment(network_id=network_id, user_id=user_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if not db.get(NetworkAssignment, (network_id, user_id)):
                raise HTTPException(status_code=409, detail="La asignación cambió. Reintenta.") from None


@admin_router.delete("/{network_id}/users/{user_id}", status_code=204)
def unassign_network(network_id: int, user_id: int, _: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    assignment = db.get(NetworkAssignment, (network_id, user_id))
    if assignment:
        db.delete(assignment)
        db.commit()
