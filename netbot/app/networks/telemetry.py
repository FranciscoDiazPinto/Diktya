"""Vista técnica por red; nunca entrega el inventario global a un técnico."""
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings
from app.monitoring.schemas import CollectionIssue, IssueKind, MonitoringResponse, MonitoringStatus
from app.monitoring.service import MonitoringService
from .access import authorize
from .support_models import NetworkSupportConfig
from .support_schemas import NetworkTelemetry


def _unavailable(source, message):
    return MonitoringResponse(status=MonitoringStatus.UNAVAILABLE,source=source,collected_at=datetime.now(timezone.utc),
        issues=[CollectionIssue(component='network.scope',kind=IssueKind.CONFIGURATION,message=message)])


def _binding(config):
    if config is None:
        return None
    return config.unifi_site_id, tuple(sorted(config.unifi_ap_ids)), config.monitoring_interface_id


async def network_telemetry(db: Session, user: User, network_id: int,
                            monitoring: MonitoringService, settings: Settings) -> NetworkTelemetry:
    network = authorize(db,user,Permission.NETWORKS_READ_DETAILS,network_id)
    config = db.get(NetworkSupportConfig,network_id)
    initial = _binding(config)
    site = network.site
    aps = _unavailable('unifi','No hay AP explícitamente vinculados a esta red.')
    interfaces = _unavailable(settings.monitoring_provider,'No hay una interfaz y sitio de monitoreo vinculados a esta red.')
    if config and config.unifi_site_id and config.unifi_ap_ids:
        response = await monitoring.get_access_points()
        # Reautorizar antes de usar la vinculación capturada tras la espera externa.
        authorize(db,user,Permission.NETWORKS_READ_DETAILS,network_id)
        config = db.get(NetworkSupportConfig,network_id)
        if _binding(config) != initial:
            return NetworkTelemetry(network_id=network_id,access_points=_unavailable('unifi','Cambió la vinculación de monitoreo; vuelve a consultar.'),interfaces=interfaces)
        if response.data is None:
            aps = response
        else:
            wanted = set(config.unifi_ap_ids)
            selected = [ap for ap in response.data if ap.site_id==config.unifi_site_id and ap.id in wanted]
            missing = len(selected)!=len(wanted)
            issues = list(response.issues)
            if missing:
                issues.append(CollectionIssue(component='network.access_points',kind=IssueKind.INVALID_RESPONSE,
                    message='No se encontraron todos los AP vinculados en el sitio consultado.'))
            aps = response.model_copy(update={'data':selected,'issues':issues,
                'status':MonitoringStatus.DEGRADED if missing else response.status})
    if config and config.monitoring_interface_id and settings.monitoring_site_id==site:
        response = await monitoring.get_interfaces()
        network = authorize(db,user,Permission.NETWORKS_READ_DETAILS,network_id)
        config = db.get(NetworkSupportConfig,network_id)
        if _binding(config)!=initial or network.site!=site:
            return NetworkTelemetry(network_id=network_id,access_points=_unavailable('unifi','Cambió la vinculación de monitoreo; vuelve a consultar.'),interfaces=interfaces)
        if response.data is None:
            interfaces = response
        elif response.source!=settings.monitoring_provider:
            interfaces = _unavailable(settings.monitoring_provider,'La fuente no corresponde a esta red.')
        else:
            selected = [i for i in response.data if i.interface_id==config.monitoring_interface_id]
            interfaces = response.model_copy(update={'data':selected if len(selected)==1 else [],
                'status':response.status if len(selected)==1 else MonitoringStatus.DEGRADED,
                'issues':response.issues if len(selected)==1 else [CollectionIssue(component='network.interface',
                    kind=IssueKind.INVALID_RESPONSE,message='La interfaz vinculada no se pudo identificar inequívocamente.')]})
    # Sin esperas adicionales: esta autorización también cubre el caso sin configuración.
    authorize(db,user,Permission.NETWORKS_READ_DETAILS,network_id)
    return NetworkTelemetry(network_id=network_id,access_points=aps,interfaces=interfaces)
