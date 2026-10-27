"""Adaptación HTTP de la carga CSV: cuerpo crudo y lectura acotada."""
from fastapi import Depends, Request
from sqlalchemy.orm import Session
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import InvalidInput, PayloadTooLarge
from app.monitoring.dependencies import MonitoringServiceDep
from .csv_service import CsvImportService


def get_csv_service(monitoring: MonitoringServiceDep, db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)) -> CsvImportService:
    return CsvImportService(db, monitoring, settings)


async def read_csv_body(request: Request, settings: Settings = Depends(get_settings)) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"text/csv", "application/csv", "application/octet-stream"}:
        raise InvalidInput("Envía el archivo CSV como cuerpo crudo con Content-Type: text/csv.")
    if request.headers.get("content-length"):
        try:
            length = int(request.headers["content-length"])
        except ValueError:
            raise InvalidInput("Tamaño de archivo inválido.") from None
        if length < 0:
            raise InvalidInput("Tamaño de archivo inválido.")
        if length > settings.csv_max_bytes:
            raise PayloadTooLarge("El CSV supera el tamaño máximo permitido.")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > settings.csv_max_bytes:
            raise PayloadTooLarge("El CSV supera el tamaño máximo permitido.")
        content.extend(chunk)
    return bytes(content)
