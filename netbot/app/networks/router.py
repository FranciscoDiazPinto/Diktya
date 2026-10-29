from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.database import get_db
from .access import accessible_networks, require_network, network_read
from . import service
from .schemas import NetworkCreate, NetworkRead, NetworkSummary
from .recipients import RecipientWrite, RecipientsWrite, read_recipients, replace_recipients

router = APIRouter(prefix="/networks", tags=["networks"])
admin_router = APIRouter(prefix="/admin/networks", tags=["network administration"])


@router.get("", response_model=list[NetworkRead | NetworkSummary])
def list_networks(user: User = Depends(require_permission(Permission.NETWORKS_READ_OWN.value)), db: Session = Depends(get_db)):
    return [network_read(n, user) for n in accessible_networks(db, user)]


@router.get("/{network_id}", response_model=NetworkRead | NetworkSummary)
def get_network(network_id: int, user: User = Depends(require_permission(Permission.NETWORKS_READ_OWN.value)), db: Session = Depends(get_db)):
    return network_read(require_network(db, user, network_id), user)


@admin_router.get("/{network_id}/users", response_model=list[int])
def list_assignments(network_id: int, actor: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return service.list_assignments(network_id, db, actor)


@admin_router.post("", response_model=NetworkRead, status_code=201)
def create_network(payload: NetworkCreate, actor: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return service.create_network(payload, db, actor)


@admin_router.put("/{network_id}/users/{user_id}", status_code=204)
def assign_network(network_id: int, user_id: int, actor: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return service.assign_network(network_id, user_id, db, actor)


@admin_router.delete("/{network_id}/users/{user_id}", status_code=204)
def unassign_network(network_id: int, user_id: int, actor: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return service.unassign_network(network_id, user_id, db, actor)

def contacts_no_store(response: Response):
    response.headers['Cache-Control'] = 'no-store, private'
    response.headers['Pragma'] = 'no-cache'


@admin_router.get('/{network_id}/recipients', response_model=list[RecipientWrite], dependencies=[Depends(contacts_no_store)])
def get_recipients(network_id: int, actor: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return read_recipients(db, actor, network_id)


@admin_router.put('/{network_id}/recipients', response_model=list[RecipientWrite], dependencies=[Depends(contacts_no_store)])
def put_recipients(network_id: int, payload: RecipientsWrite, actor: User = Depends(require_permission(Permission.NETWORKS_MANAGE.value)), db: Session = Depends(get_db)):
    return replace_recipients(db, actor, network_id, payload)
