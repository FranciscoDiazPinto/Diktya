"""Worker de cambios como proceso propio. No carga FastAPI ni la aplicación HTTP.

    python -m app.agents.cli                 una pasada de trabajos aprobados
    python -m app.agents.cli --loop          servicio continuo (despliegue)
    python -m app.agents.cli reconcile vlan <id>   conciliación manual de un trabajo detenido
"""
import argparse
import asyncio
import logging

from app.bootstrap import initialize_database
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.monitoring.factory import build_monitoring_service

from .orchestrator import Orchestrator
from .worker import KINDS, ChangeWorker


async def run(args) -> None:
    settings = get_settings()
    initialize_database()
    monitoring = build_monitoring_service(settings)
    worker = ChangeWorker(SessionLocal, settings, monitoring)
    try:
        if args.command == "reconcile":
            print(args.kind, args.plan_id, await worker.reconcile(args.kind, args.plan_id) or "sin cambios")
            return
        if not settings.unifi_write_enabled:
            raise SystemExit("Ejecutor deshabilitado (UNIFI_WRITE_ENABLED=false). No se realizó ninguna operación.")
        orchestrator = Orchestrator(SessionLocal, settings)
        orchestrator.register("changes", worker.run_cycle, settings.change_worker_interval_seconds)
        if not args.loop:
            await orchestrator.run_once("changes")
            return
        orchestrator.start()
        try:
            await asyncio.Event().wait()
        finally:
            await orchestrator.stop()
    finally:
        await monitoring.aclose()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Ejecuta trabajos de cambio aprobados; nunca reintenta estados inciertos.")
    parser.add_argument("--loop", action="store_true", help="Ejecutar de forma continua.")
    commands = parser.add_subparsers(dest="command")
    reconcile = commands.add_parser("reconcile", help="Conciliar un trabajo detenido leyendo el controlador.")
    reconcile.add_argument("kind", choices=sorted(KINDS))
    reconcile.add_argument("plan_id")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(run(parser.parse_args(argv)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
