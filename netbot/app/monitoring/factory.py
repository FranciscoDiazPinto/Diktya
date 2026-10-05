"""Construcción del proveedor de monitoreo según la configuración (mock u OPNsense)."""

import logging
import ssl

from app.core.config import Settings

from .providers.base import NetworkMonitoringProvider
from .providers.mock import MockMonitoringProvider
from .providers.opnsense import (
    DnsmasqLeaseProvider,
    KeaLeaseProvider,
    OPNsenseClient,
    OPNsenseMonitoringProvider,
)
from .service import MonitoringService

logger = logging.getLogger("netbot.monitoring.factory")


def _tls_verify(settings: Settings) -> bool | ssl.SSLContext:
    if not settings.opnsense_verify_tls:
        logger.warning(
            "OPNSENSE_VERIFY_TLS=false: no se verifica el certificado de OPNsense. "
            "Use OPNSENSE_CA_BUNDLE con el certificado propio en lugar de desactivarlo."
        )
        return False
    if settings.opnsense_ca_bundle:
        return ssl.create_default_context(cafile=settings.opnsense_ca_bundle)
    return True


def build_monitoring_provider(settings: Settings) -> NetworkMonitoringProvider:
    if settings.monitoring_provider == "mock":
        logger.info(
            "Monitoreo con proveedor MOCK (escenario: %s)", settings.monitoring_mock_scenario
        )
        return MockMonitoringProvider(scenario=settings.monitoring_mock_scenario)

    assert settings.opnsense_base_url and settings.opnsense_api_key and settings.opnsense_api_secret
    client = OPNsenseClient(
        settings.opnsense_base_url,
        settings.opnsense_api_key,
        settings.opnsense_api_secret,
        verify=_tls_verify(settings),
        timeout=settings.opnsense_timeout_seconds,
        connect_timeout=settings.opnsense_connect_timeout_seconds,
    )
    dhcp = (
        KeaLeaseProvider(client)
        if settings.opnsense_dhcp_backend == "kea"
        else DnsmasqLeaseProvider(client)
    )
    logger.info("Monitoreo con proveedor OPNsense (DHCP: %s)", settings.opnsense_dhcp_backend)
    return OPNsenseMonitoringProvider(client, dhcp)


def build_monitoring_service(settings: Settings) -> MonitoringService:
    return MonitoringService(
        build_monitoring_provider(settings),
        cache_ttl_seconds=settings.monitoring_cache_ttl_seconds,
        firewall_log_fetch_limit=settings.firewall_log_fetch_limit,
    )
