"""Cliente HTTP asíncrono para la API REST de OPNsense.

- Autenticación: HTTP Basic (API key como usuario, API secret como contraseña).
- Nunca registra cabeceras ni credenciales; los logs solo contienen método, ruta,
  código de estado y duración.
- Traduce los fallos de transporte/HTTP a excepciones tipadas de NetBot.
"""

import asyncio
import json
import logging
import ssl
import time
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
    ProviderServerError,
    ProviderTimeoutError,
    ProviderTLSError,
)

logger = logging.getLogger("netbot.monitoring.opnsense.client")


def normalize_base_url(base_url: str) -> str:
    """Quita barras finales y un sufijo '/api' accidental (las rutas ya lo incluyen)."""
    url = base_url.strip().rstrip("/")
    if url.lower().endswith("/api"):
        url = url[: -len("/api")]
    return url


def _is_tls_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


class OPNsenseClient:
    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        api_secret: SecretStr,
        *,
        verify: bool | ssl.SSLContext = True,
        timeout: float = 5.0,
        connect_timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=normalize_base_url(base_url),
            auth=httpx.BasicAuth(api_key.get_secret_value(), api_secret.get_secret_value()),
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            verify=verify,
            headers={"Accept": "application/json", "User-Agent": "netbot-monitoring/0.1"},
            follow_redirects=False,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            transport=transport,
        )

    def __repr__(self) -> str:  # evita filtrar configuración por accidente
        return "OPNsenseClient(<redacted>)"

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #

    async def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """GET a `path` (p. ej. '/api/diagnostics/system/system_time') y devuelve el JSON."""
        started = time.monotonic()
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise self._translate_transport_error(path, exc) from exc

        self._check_status(path, response, started)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderInvalidResponseError(
                f"{path}: el cuerpo no es JSON válido", status_code=response.status_code
            ) from exc

    async def stream_first_json_event(self, path: str) -> Any:
        """Lee el primer evento `data:` de un endpoint Server-Sent Events y cierra.

        Necesario para `/api/diagnostics/cpu_usage/stream`, que emite eventos de
        forma indefinida y por tanto no puede consumirse con un GET normal.
        """
        started = time.monotonic()
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "GET", path, headers={"Accept": "text/event-stream"}
                ) as response:
                    self._check_status(path, response, started)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[len("data:") :].strip()
                        if not raw:
                            continue
                        try:
                            return json.loads(raw)
                        except ValueError as exc:
                            raise ProviderInvalidResponseError(
                                f"{path}: evento SSE con JSON inválido"
                            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError(f"{path}: sin eventos en {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise self._translate_transport_error(path, exc) from exc
        raise ProviderInvalidResponseError(f"{path}: el stream terminó sin eventos")

    # ------------------------------------------------------------------ #

    def _check_status(self, path: str, response: httpx.Response, started: float) -> None:
        code = response.status_code
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.debug("GET %s -> %s (%.0f ms)", path, code, elapsed_ms)
        if 200 <= code < 300:
            return
        error: MonitoringError
        if code == 401:
            error = ProviderAuthenticationError(f"{path}: HTTP 401", status_code=code)
        elif code == 403:
            error = ProviderPermissionError(f"{path}: HTTP 403", status_code=code)
        elif code == 404:
            error = ProviderNotSupportedError(f"{path}: HTTP 404", status_code=code)
        elif code >= 500:
            error = ProviderServerError(f"{path}: HTTP {code}", status_code=code)
        else:
            # Incluye 3xx: no se siguen redirecciones (típico de http:// vs https://).
            error = ProviderInvalidResponseError(
                f"{path}: HTTP {code} inesperado; revise OPNSENSE_BASE_URL", status_code=code
            )
        raise error

    @staticmethod
    def _translate_transport_error(path: str, exc: httpx.HTTPError) -> MonitoringError:
        name = type(exc).__name__
        if isinstance(exc, httpx.TimeoutException):
            return ProviderTimeoutError(f"{path}: {name}")
        if _is_tls_error(exc):
            return ProviderTLSError(f"{path}: {name} (error TLS)")
        return ProviderConnectionError(f"{path}: {name}")
