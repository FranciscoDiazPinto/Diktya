"""Auditoría local de soporte; el caso de uso llamante controla el commit."""
from sqlalchemy.orm import Session
from .support_models import SupportAudit

def record_audit(db: Session, actor_id: int, network_id: int, action: str) -> None:
    db.add(SupportAudit(actor_id=actor_id, network_id=network_id, action=action))
