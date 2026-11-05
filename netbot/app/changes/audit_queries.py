"""Metadatos de reservas y planes; no reconstruye ejecuciones inexistentes."""
from app.core.audit import audit_projection
from .models import VlanReservation as Reservation, CsvImport, SsidPlan


def audit_queries():
    queries = [
        audit_projection("reservations", Reservation.id, Reservation.created_at,
                         Reservation.requested_by_id, "reservation.created", "reserved", "reservation", Reservation.id),
        audit_projection("reservations", Reservation.id, Reservation.released_at,
                         Reservation.released_by_id, "reservation.released", "released", "reservation", Reservation.id)
                         .where(Reservation.released_at.is_not(None)),
    ]
    for source, model, resource in [("csv", CsvImport, "csv_import"), ("ssid", SsidPlan, "ssid_plan")]:
        queries.extend([
            audit_projection(source, model.id, model.created_at, model.owner_id,
                             resource + ".created", "preview", resource, model.id),
            audit_projection(source, model.id, model.confirmed_at, model.owner_id,
                             resource + ".confirmed", "confirmed", resource, model.id)
                             .where(model.confirmed_at.is_not(None)),
            # El resultado pertenece al estado actual, no a la fecha de ejecución.
            audit_projection(source, model.id, model.created_at, model.owner_id,
                             resource + ".snapshot", model.status, resource, model.id, snapshot=True),
        ])
    return queries
