"""Herramientas de soporte de consulta/propuesta, ligadas a la sesión real."""
from app.core.errors import NotFound, InvalidInput, ServiceUnavailable
from sqlalchemy.orm import Session
from app.auth.models import User
from app.core.config import Settings
from app.monitoring.service import MonitoringService

from app.auth.permissions import Permission
from app.networks.diagnostics import network_status
from app.networks.credentials import wifi_action
from app.networks.access import authorize
from app.tickets.schemas import TicketProposal
from app.tickets.service import list_ticket_summaries


class CustomerSupport:
    def __init__(self, db: Session, user: User, monitoring: MonitoringService, settings: Settings):
        self.db, self.user = db, user
        self.monitoring, self.settings = monitoring, settings

    async def invoke(self, name: str, arguments: dict, allowed_network_ids: set[int]) -> dict:
        if name == "list_support_tickets":
            return {"data": list_ticket_summaries(self.db, self.user, allowed_network_ids)}
        network_id = arguments["network_id"]
        if network_id not in allowed_network_ids:
            raise NotFound("Red no disponible en esta conversación.")
        if name == "get_network_status":
            return (await network_status(self.db, self.user, network_id, self.monitoring, self.settings)).model_dump(mode="json")
        if name == "offer_wifi_access":
            try:
                action = wifi_action(self.db, self.user, network_id, self.settings)
            except ServiceUnavailable as exc:
                return {"status": "unavailable", "message": exc.detail}
            return {"status": "available", "action": action.model_dump(),
                    "message": "El usuario puede pulsar el botón protegido para ver el acceso. La clave no está en el chat."}
        if name == "prepare_support_ticket":
            authorize(self.db, self.user, Permission.TICKETS_CREATE_OWN, network_id)
            proposal = TicketProposal.model_validate(arguments)
            return {"proposal": proposal.model_dump(), "status": "awaiting_confirmation",
                    "message": "Solo es una propuesta; el usuario debe confirmar para guardar el ticket."}
        raise InvalidInput("Herramienta de soporte no disponible.")
