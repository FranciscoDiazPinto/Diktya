"""Configuración de soporte. Ningún secreto real se recibe ni persiste aquí."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.models import User
from app.auth.access import require_user_permission
from app.auth.permissions import Permission
from .access import require_network
from .support_models import NetworkSupportConfig, SupportAudit
from .support_schemas import SupportConfigWrite, SupportAuditRead

def read_support_config(network_id: int, user: User, db: Session) -> SupportConfigWrite:
    require_user_permission(db, user, Permission.NETWORKS_MANAGE)
    require_network(db, user, network_id)
    config = db.get(NetworkSupportConfig, network_id)
    return SupportConfigWrite.model_validate(config) if config else SupportConfigWrite()


def read_support_audit(network_id: int, user: User, db: Session, limit: int = 50, offset: int = 0) -> list[SupportAuditRead]:
    require_user_permission(db, user, Permission.NETWORKS_MANAGE)
    require_network(db, user, network_id)
    rows = db.scalars(select(SupportAudit).where(SupportAudit.network_id == network_id)
                      .order_by(SupportAudit.id.desc()).limit(limit).offset(offset)).all()
    return [SupportAuditRead.model_validate(row) for row in rows]


def configure_support(network_id: int, payload: SupportConfigWrite, user: User, db: Session) -> SupportConfigWrite:
    require_user_permission(db, user, Permission.NETWORKS_MANAGE)
    require_network(db, user, network_id)
    config = db.get(NetworkSupportConfig, network_id)
    if config is None:
        config = NetworkSupportConfig(network_id=network_id)
        db.add(config)
    config.credential_ref = payload.credential_ref
    config.monitoring_interface_id = payload.monitoring_interface_id
    db.add(SupportAudit(actor_id=user.id, network_id=network_id, action="network_support.updated"))
    db.commit()
    return SupportConfigWrite.model_validate(config)
