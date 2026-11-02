"""Cliente HTTP de la API oficial de UniFi Network (OpenAPI 10.6.106).

Solo expone GET: el adaptador de monitoreo no puede modificar la red. La API key va en
una cabecera y nunca se registra ni forma parte de los mensajes públicos.
"""

import logging
import ssl
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import SecretStr

from ...exceptions import (
    MonitoringError,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInvalidResponseError,
    ProviderNotSupportedError,
    ProviderPermissionError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderTLSError,
)
from ..opnsense.client import _is_tls_error

logger = logging.getLogger("netbot.monitoring.unifi.client")

API_ROOT = "/proxy/network/integration/v1"
CONNECTOR_BASE = "https://api.ui.com/v1/connector/consoles"
PAGE_SIZE = 200
MAX_ITEMS = 5000  # corta una paginación incoherente


class UnifiAuthenticationError(ProviderAuthenticationError):
    public_message = "UniFi rechazó la API key (HTTP 401)."


class UnifiPermissionError(ProviderPermissionError):
    public_message = "La API key de UniFi no tiene permisos para este recurso (HTTP 403)."


class UnifiNotSupportedError(ProviderNotSupportedError):
    public_message = "El recurso no existe en esta versión de UniFi Network (HTTP 404)."


class UnifiTimeoutError(ProviderTimeoutError):
    public_message = "Tiempo de espera agotado al consultar UniFi."


class UnifiTLSError(ProviderTLSError):
    public_message = "Falló la verificación TLS/SSL con UniFi."


class UnifiConnectionError(ProviderConnectionError):
    public_message = "No se pudo establecer conexión con UniFi."


class UnifiServerError(ProviderServerError):
    public_message = "UniFi respondió con un error interno (HTTP 5xx)."


class UnifiInvalidResponseError(ProviderInvalidResponseError):
    public_message = "UniFi devolvió una respuesta inesperada o ilegible."


def unifi_base_url(*, transport: str, base_url: str | None, console_id: str | None) -> str:
    if transport == "connector":
        return f"{CONNECTOR_BASE}/{console_id}"
    return (base_url or "").strip().rstrip("/")


class UnifiClient:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        *,
        verify: bool | ssl.SSLContext = True,
        timeout: float = 10.0,
        connect_timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept": "application/json", "User-Agent": "netbot-monitoring/0.1",
                     "X-API-Key": api_key.get_secret_value()},
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            verify=verify,
            follow_redirects=False,  # no llevar la API key a otro host
            transport=transport,
        )

    def __repr__(self) -> str:  # evita filtrar configuración por accidente
        return "UnifiClient(<redacted>)"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        try:
            response = await self._client.get(f"{API_ROOT}{path}", params=params)
        except httpx.HTTPError as exc:
            raise self._translate_transport_error(path, exc) from exc
        self._check_status(path, response)
        try:
            return response.json()
        except ValueError as exc:
            raise UnifiInvalidResponseError(f"{path}: el cuerpo no es JSON válido") from exc

    async def get_all(self, path: str) -> list[dict[str, Any]]:
        """Recorre un listado completo. No trunca: una paginación incoherente es un error."""
        items: list[dict[str, Any]] = []
        while True:
            page = await self.get_json(path, {"offset": len(items), "limit": PAGE_SIZE})
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise UnifiInvalidResponseError(f"{path}: listado sin envoltorio data")
            total = page.get("totalCount")
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                raise UnifiInvalidResponseError(f"{path}: totalCount inválido")
            rows = page["data"]
            if not all(isinstance(row, dict) for row in rows):
                raise UnifiInvalidResponseError(f"{path}: fila con forma inválida")
            items.extend(rows)
            if len(items) >= total:
                return items
            if not rows or len(items) >= MAX_ITEMS:
                raise UnifiInvalidResponseError(f"{path}: paginación incompleta o excesiva")

    def _check_status(self, path: str, response: httpx.Response) -> None:
        code = response.status_code
        logger.debug("GET %s -> %s", path, code)
        if 200 <= code < 300:
            return
        detail = f"{path}: HTTP {code}"
        error: MonitoringError
        if code == 401:
            error = UnifiAuthenticationError(detail, status_code=code)
        elif code == 403:
            error = UnifiPermissionError(detail, status_code=code)
        elif code == 404:
            error = UnifiNotSupportedError(detail, status_code=code)
        elif code == 429:
            error = ProviderRateLimitError(detail, status_code=code)
        elif code >= 500:
            error = UnifiServerError(detail, status_code=code)
        else:  # incluye 3xx: no se siguen redirecciones
            error = UnifiInvalidResponseError(f"{detail} inesperado", status_code=code)
        raise error

    @staticmethod
    def _translate_transport_error(path: str, exc: httpx.HTTPError) -> MonitoringError:
        name = type(exc).__name__
        if isinstance(exc, httpx.TimeoutException):
            return UnifiTimeoutError(f"{path}: {name}")
        if _is_tls_error(exc):
            return UnifiTLSError(f"{path}: {name} (error TLS)")
        return UnifiConnectionError(f"{path}: {name}")
