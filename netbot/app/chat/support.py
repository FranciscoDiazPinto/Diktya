"""Herramientas de soporte de consulta/propuesta, ligadas a la sesión real."""
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.auth.models import User
from app.core.config import Settings
from app.monitoring.service import MonitoringService

from app.auth.permissions import Permission
from app.networks.support import network_status, wifi_action, authorize
from app.tickets.models import Ticket
from app.tickets.schemas import TicketProposal, TicketRead
from app.tickets.service import ticket_query


class CustomerSupport:
    def __init__(self, db: Session, user: User, monitoring: MonitoringService, settings: Settings):
        self.db, self.user = db, user
        self.monitoring, self.settings = monitoring, settings

    async def invoke(self, name: str, arguments: dict, allowed_network_ids: set[int]) -> dict:
        if name == "list_support_tickets":
            query = ticket_query(self.db, self.user).where(Ticket.network_id.in_(allowed_network_ids))
            rows = self.db.scalars(query.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).limit(5)).all()
            return {"data": [TicketRead.model_validate(row).model_dump(
                mode="json", include={"id", "network_id", "summary", "status", "version", "updated_at"}
            ) for row in rows]}
        network_id = arguments["network_id"]
        if network_id not in allowed_network_ids:
            raise HTTPException(status_code=404, detail="Red no disponible en esta conversación.")
        if name == "get_network_status":
            return (await network_status(self.db, self.user, network_id, self.monitoring, self.settings)).model_dump(mode="json")
        if name == "offer_wifi_access":
            try:
                action = wifi_action(self.db, self.user, network_id, self.settings)
            except HTTPException as exc:
                if exc.status_code == 503:
                    return {"status": "unavailable", "message": exc.detail}
                raise
            return {"status": "available", "action": action.model_dump(),
                    "message": "El usuario puede pulsar el botón protegido para ver el acceso. La clave no está en el chat."}
        if name == "prepare_support_ticket":
            authorize(self.db, self.user, Permission.TICKETS_CREATE_OWN, network_id)
            proposal = TicketProposal.model_validate(arguments)
            return {"proposal": proposal.model_dump(), "status": "awaiting_confirmation",
                    "message": "Solo es una propuesta; el usuario debe confirmar para guardar el ticket."}
        raise HTTPException(status_code=400, detail="Herramienta de soporte no disponible.")
