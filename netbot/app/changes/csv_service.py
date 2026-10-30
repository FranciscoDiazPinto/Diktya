"""Vista previa privada y confirmación atómica de reservas desde CSV."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.access import require_user_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings
from app.core.errors import Conflict, InvalidInput, NotFound, ServiceUnavailable
from app.monitoring.schemas import MonitoringStatus
from app.monitoring.service import MonitoringService
from .csv_parser import parse_csv
from .csv_schemas import CsvImportRead, CsvImportSummary, CsvRow, CsvResult, CsvConfirm
from .models import CsvImport, VlanReservation
from .schemas import VlanReservationRead
from .service import build_reservation


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CsvImportService:
    def __init__(self, db: Session, monitoring: MonitoringService, settings: Settings):
        self.db, self.monitoring, self.settings = db, monitoring, settings

    def _authorize(self, actor: User):
        require_user_permission(self.db, actor, Permission.VLAN_RESERVE)

    def _context(self) -> str:
        config = self.settings
        identity = ["netbot_csv_v1", config.monitoring_provider, config.monitoring_site_id,
                    config.opnsense_base_url if config.monitoring_provider == "opnsense" else config.monitoring_mock_scenario]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    def _owned(self, import_id: str, actor: User) -> CsvImport:
        row = self.db.scalar(select(CsvImport).where(CsvImport.id == import_id, CsvImport.owner_id == actor.id))
        if row is None:
            raise NotFound("Importación no encontrada.")
        return row

    def _state(self, row: CsvImport) -> str:
        return "expired" if row.status == "preview" and as_utc(row.expires_at) <= utc_now() else row.status

    def _read(self, row: CsvImport) -> CsvImportRead:
        rows = [CsvRow.model_validate(data) for data in row.rows]
        ids = [result["reservation_id"] for result in row.results]
        reservations = {r.id: r for r in self.db.scalars(select(VlanReservation).where(
            VlanReservation.id.in_(ids), VlanReservation.requested_by_id == row.owner_id)).all()} if ids else {}
        results = [CsvResult(row_number=result["row_number"],
                             reservation=VlanReservationRead.from_model(reservations[result["reservation_id"]]))
                   for result in row.results if result["reservation_id"] in reservations]
        valid = sum(not item.errors and item.data is not None for item in rows)
        return CsvImportRead(id=row.id, filename=row.filename, status=self._state(row), source=row.source,
                             simulated=row.source == "mock", created_at=as_utc(row.created_at), expires_at=as_utc(row.expires_at),
                             confirmed_at=as_utc(row.confirmed_at) if row.confirmed_at else None,
                             rows=rows, valid_count=valid, invalid_count=len(rows) - valid, results=results)

    async def _inventory(self):
        response = await self.monitoring.get_vlan_inventory()
        age = (utc_now() - as_utc(response.collected_at)).total_seconds()
        if (response.status != MonitoringStatus.OK or response.data is None
                or response.source != self.settings.monitoring_provider
                or age < -5 or age > self.settings.csv_inventory_max_age_seconds):
            raise ServiceUnavailable("Inventario VLAN no disponible, incompleto o fuera de vigencia. Vuelve a intentar.")
        counts = Counter((v.parent_interface, v.tag) for v in response.data)
        inventory = {(v.parent_interface, v.tag): v for v in response.data if counts[v.parent_interface, v.tag] == 1}
        return response.source, inventory

    def _active_keys(self):
        return set(self.db.execute(select(VlanReservation.parent_interface, VlanReservation.tag)
                                   .where(VlanReservation.status == "reserved")).all())

    async def preview(self, content: bytes, filename: str, actor: User) -> CsvImportRead:
        self._authorize(actor)
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not filename.lower().endswith(".csv") or len(filename) > 160 or "\x00" in filename:
            raise InvalidInput("Selecciona un archivo con extensión .csv y nombre de hasta 160 caracteres.")
        rows = parse_csv(content, max_bytes=self.settings.csv_max_bytes, max_rows=self.settings.csv_max_rows)
        source = self.settings.monitoring_provider
        if any(row.data is not None and not row.errors for row in rows):
            source, inventory = await self._inventory()
            self._authorize(actor)
            active = self._active_keys()
            for row in rows:
                if row.data is None or row.errors:
                    continue
                key = row.data.parent_interface, row.data.tag
                if key not in inventory:
                    row.errors.append("La VLAN no existe o no es inequívoca en el inventario actual.")
                elif key in active:
                    row.errors.append("La VLAN ya tiene una reserva activa.")
        self._authorize(actor)
        now = utc_now()
        row = CsvImport(id=str(uuid4()), owner_id=actor.id, filename=filename, status="preview", source=source,
                        source_context=self._context(), rows=[r.model_dump(mode="json") for r in rows], results=[],
                        created_at=now, expires_at=now + timedelta(seconds=self.settings.csv_preview_ttl_seconds), confirmed_at=None)
        self.db.add(row)
        self.db.commit()
        return self._read(row)

    def get(self, import_id: str, actor: User) -> CsvImportRead:
        self._authorize(actor)
        return self._read(self._owned(import_id, actor))

    def list_imports(self, actor: User, limit: int = 25, offset: int = 0) -> list[CsvImportSummary]:
        self._authorize(actor)
        rows = self.db.scalars(select(CsvImport).where(CsvImport.owner_id == actor.id)
                               .order_by(CsvImport.created_at.desc(), CsvImport.id.desc()).limit(limit).offset(offset)).all()
        return [CsvImportSummary(id=r.id, filename=r.filename, status=self._state(r), created_at=as_utc(r.created_at)) for r in rows]

    def _confirmed_or_validate(self, row: CsvImport, selected: list[int]) -> CsvImportRead | None:
        if row.status == "confirmed":
            if selected != sorted(result["row_number"] for result in row.results):
                raise Conflict("Esta importación ya se confirmó con otra selección.")
            return self._read(row)
        if self._state(row) != "preview":
            raise Conflict("La vista previa está cancelada o vencida. Carga y valida el CSV nuevamente.")
        rows = {r["row_number"]: CsvRow.model_validate(r) for r in row.rows}
        if any(number not in rows or rows[number].errors or rows[number].data is None for number in selected):
            raise Conflict("Selecciona únicamente filas válidas de esta vista previa.")
        return None

    async def confirm(self, import_id: str, payload: CsvConfirm, actor: User) -> CsvImportRead:
        self._authorize(actor)
        selected = payload.row_numbers
        row = self._owned(import_id, actor)
        previous = self._confirmed_or_validate(row, selected)
        if previous:
            return previous
        source, inventory = await self._inventory()
        self._authorize(actor)
        row = self._owned(import_id, actor)
        previous = self._confirmed_or_validate(row, selected)
        if previous:
            return previous
        if row.source_context != self._context() or source != row.source:
            raise Conflict("Cambió la fuente de inventario. Valida el archivo nuevamente.")
        rows = {r["row_number"]: CsvRow.model_validate(r) for r in row.rows}
        active = self._active_keys()
        for number in selected:
            data = rows[number].data
            key = data.parent_interface, data.tag
            if key not in inventory or key in active:
                raise Conflict(f"La fila {number} ya no está disponible. Valida el archivo nuevamente.")
        now = utc_now()
        try:
            # Bloqueo optimista: la confirmación y las reservas se confirman juntas.
            changed = self.db.execute(update(CsvImport).where(
                CsvImport.id == import_id, CsvImport.owner_id == actor.id,
                CsvImport.status == "preview", CsvImport.expires_at > now,
            ).values(status="confirmed", confirmed_at=now), execution_options={"synchronize_session": False})
            if changed.rowcount != 1:
                self.db.rollback()
                self._authorize(actor)
                previous = self._confirmed_or_validate(self._owned(import_id, actor), selected)
                if previous:
                    return previous
                raise Conflict("La importación cambió. Recarga su estado antes de confirmar.")
            reservations = []
            for number in selected:
                data = rows[number].data
                reservation = build_reservation(data, inventory[data.parent_interface, data.tag], actor.id, now)
                self.db.add(reservation)
                reservations.append((number, reservation))
            self.db.flush()
            row.results = [{"row_number": number, "reservation_id": reservation.id} for number, reservation in reservations]
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Una VLAN fue reservada por otra operación. No se guardó ninguna fila de esta selección.") from None
        self.db.refresh(row)
        return self._read(row)

    def cancel(self, import_id: str, actor: User) -> CsvImportRead:
        self._authorize(actor)
        row = self._owned(import_id, actor)
        if row.status == "confirmed":
            raise Conflict("La importación ya fue confirmada. Las reservas se liberan desde su listado.")
        self.db.execute(update(CsvImport).where(CsvImport.id == import_id, CsvImport.status == "preview")
                        .values(status="cancelled"), execution_options={"synchronize_session": False})
        self.db.commit()
        self.db.refresh(row)
        if row.status != "cancelled":
            raise Conflict("La importación cambió; recarga su estado.")
        return self._read(row)
