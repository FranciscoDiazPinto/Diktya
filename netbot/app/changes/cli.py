"""Worker explícito de planes aprobados. No se arranca con la API HTTP."""
import argparse
import asyncio
from sqlalchemy import select
from app.bootstrap import initialize_database
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.monitoring.factory import build_monitoring_service
from .models import SsidPlan
from .ssid_service import SsidPlanService
from app.core.errors import ApplicationError


async def run_once():
    settings=get_settings()
    if not settings.unifi_write_enabled:
        raise SystemExit('Ejecutor deshabilitado. No se realizó ninguna operación.')
    initialize_database()
    monitoring=build_monitoring_service(settings)
    try:
        with SessionLocal() as db:
            ids=list(db.scalars(select(SsidPlan.id).where(SsidPlan.status=='confirmed').order_by(SsidPlan.created_at).limit(100)))
            for plan_id in ids:
                try:
                    result=await SsidPlanService(db,settings,monitoring).execute(plan_id)
                    print(plan_id,result.execution_status)
                except ApplicationError as exc:
                    db.rollback();print(plan_id,exc.detail)
    finally:
        await monitoring.aclose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Ejecutar una pasada de planes SSID confirmados; no reintenta estados inciertos.')
    parser.parse_args()
    asyncio.run(run_once())
