"""Construcción de proveedores según la configuración."""

import logging
import ssl
from zoneinfo import ZoneInfo

from app.core.config import Settings

from .providers.base import InfrastructureSource, NetworkMonitoringProvider
from .providers.mock import MockMonitoringProvider
from .providers.opnsense import (
    DnsmasqLeaseProvider,
    KeaLeaseProvider,
    OPNsenseClient,
    OPNsenseMonitoringProvider,
)
from .providers.unconfigured import UnconfiguredProvider
from .providers.unifi import UnifiClient, UnifiMonitoringProvider, unifi_base_url
from .service import MonitoringService

logger = logging.getLogger("netbot.monitoring.factory")


def _tls_verify(name: str, verify: bool, ca_bundle: str | None) -> bool | ssl.SSLContext:
    if not verify:
        logger.warning("%s_VERIFY_TLS=false: no se verifica el certificado. "
                       "Use %s_CA_BUNDLE con el certificado propio en lugar de desactivarlo.", name, name)
        return False
    return ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True


def build_monitoring_provider(settings: Settings) -> NetworkMonitoringProvider:
    if settings.monitoring_provider == "mock":
        logger.info(
            "Monitoreo con proveedor MOCK (escenario: %s)", settings.monitoring_mock_scenario
        )
        return MockMonitoringProvider(scenario=settings.monitoring_mock_scenario)

    if settings.opnsense_missing:
        logger.warning("OPNsense sin configurar; faltan: %s", ", ".join(settings.opnsense_missing))
        return UnconfiguredProvider("opnsense", settings.opnsense_missing)
    client = OPNsenseClient(
        settings.opnsense_base_url,
        settings.opnsense_api_key,
        settings.opnsense_api_secret,
        verify=_tls_verify("OPNSENSE", settings.opnsense_verify_tls, settings.opnsense_ca_bundle),
        timeout=settings.opnsense_timeout_seconds,
        connect_timeout=settings.opnsense_connect_timeout_seconds,
    )
    dhcp = (
        KeaLeaseProvider(client)
        if settings.opnsense_dhcp_backend == "kea"
        else DnsmasqLeaseProvider(client)
    )
    logger.info("Monitoreo con proveedor OPNsense (DHCP: %s)", settings.opnsense_dhcp_backend)
    return OPNsenseMonitoringProvider(client, dhcp, log_timezone=ZoneInfo(settings.opnsense_timezone))


def build_unifi_source(settings: Settings) -> InfrastructureSource | None:
    if not settings.unifi_enabled:
        return None
    if settings.unifi_missing:
        logger.warning("UniFi sin configurar; faltan: %s", ", ".join(settings.unifi_missing))
        return UnconfiguredProvider("unifi", settings.unifi_missing)
    client = UnifiClient(
        unifi_base_url(transport=settings.unifi_transport, base_url=settings.unifi_base_url,
                       console_id=settings.unifi_console_id),
        settings.unifi_api_key,
        verify=_tls_verify("UNIFI", settings.unifi_verify_tls, settings.unifi_ca_bundle),
        timeout=settings.unifi_timeout_seconds,
        connect_timeout=settings.unifi_connect_timeout_seconds,
    )
    logger.info("Inventario UniFi habilitado (transporte: %s)", settings.unifi_transport)
    return UnifiMonitoringProvider(client, site=settings.unifi_site)


def build_monitoring_service(settings: Settings) -> MonitoringService:
    return MonitoringService(
        build_monitoring_provider(settings),
        cache_ttl_seconds=settings.monitoring_cache_ttl_seconds,
        firewall_log_fetch_limit=settings.firewall_log_fetch_limit,
        history_seconds=settings.monitoring_history_seconds,
    )
