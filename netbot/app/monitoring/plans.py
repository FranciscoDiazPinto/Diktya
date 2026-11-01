"""Planos de cobertura y ubicación de APs. Ubicar un AP no lo configura."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, undefer

from app.auth.access import require_user_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings
from app.core.errors import Conflict, InvalidInput, NotFound, PayloadTooLarge

from .inventory import configured_sources
from .models import CoveragePlan, DevicePlacement, MonitoredDevice
from .schemas import DeviceState, PlacedAccessPoint, PlacementWrite, PlanDetail, PlanRead, UnplacedAccessPoint

MAX_DIMENSION = 20_000


def sniff_image(content: bytes) -> tuple[str, int, int]:
    """(tipo, ancho, alto) según el contenido real. Rechaza lo demás, SVG incluido."""
    size = None
    if content.startswith(b"\x89PNG\r\n\x1a\n") and content[12:16] == b"IHDR" and len(content) >= 24:
        size = ("image/png", int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big"))
    elif content.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 <= len(content) and content[index] == 0xFF:
            marker = content[index + 1]
            if marker == 0xFF:  # relleno
                index += 1
            elif 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                size = ("image/jpeg", int.from_bytes(content[index + 7:index + 9], "big"),
                        int.from_bytes(content[index + 5:index + 7], "big"))
                break
            else:
                index += 2 + int.from_bytes(content[index + 2:index + 4], "big")
    if size is None or not (0 < size[1] <= MAX_DIMENSION and 0 < size[2] <= MAX_DIMENSION):
        raise InvalidInput("El plano debe ser una imagen PNG o JPEG válida.")
    return size


def list_plans(db: Session) -> list[PlanRead]:
    return [PlanRead.model_validate(plan) for plan in db.scalars(select(CoveragePlan).order_by(CoveragePlan.id.desc()))]


def create_plan(db: Session, actor: User, settings: Settings, name: str, content: bytes) -> PlanRead:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    name = name.strip()
    if not 1 <= len(name) <= 120:
        raise InvalidInput("El nombre del plano debe tener entre 1 y 120 caracteres.")
    if len(content) > settings.monitoring_plan_max_bytes:
        raise PayloadTooLarge("La imagen supera el tamaño máximo permitido.")
    content_type, width, height = sniff_image(content)
    plan = CoveragePlan(name=name, content_type=content_type, width=width, height=height, content=content,
                        created_at=datetime.now(timezone.utc))
    db.add(plan)
    db.commit()
    return PlanRead.model_validate(plan)


def plan_image(db: Session, plan_id: int) -> tuple[bytes, str]:
    plan = db.scalar(select(CoveragePlan).where(CoveragePlan.id == plan_id).options(undefer(CoveragePlan.content)))
    if plan is None:
        raise NotFound("Plano no encontrado.")
    return plan.content, plan.content_type


def plan_detail(db: Session, settings: Settings, plan_id: int) -> PlanDetail:
    plan = db.get(CoveragePlan, plan_id)
    if plan is None:
        raise NotFound("Plano no encontrado.")
    sources = configured_sources(settings)
    placed = db.execute(
        select(DevicePlacement, MonitoredDevice).join(MonitoredDevice, MonitoredDevice.id == DevicePlacement.device_id)
        .where(DevicePlacement.plan_id == plan_id, MonitoredDevice.source.in_(sources))).all()
    unplaced = db.scalars(select(MonitoredDevice).where(
        MonitoredDevice.source.in_(sources), MonitoredDevice.device_type == "ap",
        MonitoredDevice.missing_since.is_(None), MonitoredDevice.id.notin_(select(DevicePlacement.device_id)))
        .order_by(MonitoredDevice.name))
    return PlanDetail(
        **PlanRead.model_validate(plan).model_dump(),
        placed=[PlacedAccessPoint(device_id=device.id, name=device.name, x=spot.x, y=spot.y,
                                  state=DeviceState.UNKNOWN if device.missing_since else DeviceState(device.state))
                for spot, device in placed],
        unplaced=[UnplacedAccessPoint(device_id=d.id, name=d.name, state=DeviceState(d.state)) for d in unplaced],
    )


def delete_plan(db: Session, actor: User, plan_id: int) -> None:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    plan = db.get(CoveragePlan, plan_id)
    if plan is None:
        raise NotFound("Plano no encontrado.")
    db.query(DevicePlacement).filter(DevicePlacement.plan_id == plan_id).delete()
    db.delete(plan)
    db.commit()


def place_device(db: Session, actor: User, settings: Settings, plan_id: int, device_id: int,
                 position: PlacementWrite) -> None:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    if db.get(CoveragePlan, plan_id) is None:
        raise NotFound("Plano no encontrado.")
    device = db.get(MonitoredDevice, device_id)
    if device is None or device.source not in configured_sources(settings):
        raise NotFound("Dispositivo no encontrado.")
    if device.device_type != "ap":
        raise InvalidInput("Solo se pueden ubicar puntos de acceso.")
    placement = db.scalar(select(DevicePlacement).where(DevicePlacement.device_id == device_id))
    if placement is None:
        placement = DevicePlacement(device_id=device_id)
        db.add(placement)
    placement.plan_id, placement.x, placement.y = plan_id, position.x, position.y
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("El AP se ubicó en otra solicitud; vuelve a cargar el plano.") from None


def remove_placement(db: Session, actor: User, plan_id: int, device_id: int) -> None:
    require_user_permission(db, actor, Permission.NETWORKS_MANAGE)
    placement = db.scalar(select(DevicePlacement).where(
        DevicePlacement.plan_id == plan_id, DevicePlacement.device_id == device_id))
    if placement is None:
        raise NotFound("El AP no está ubicado en este plano.")
    db.delete(placement)
    db.commit()
