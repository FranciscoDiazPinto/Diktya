"""Excepciones del módulo de monitoreo.

`public_message` es el texto que puede mostrarse en la API/dashboard: nunca incluye
URLs internas, cabeceras ni credenciales. El detalle técnico (`detail`) es solo
para logs.
"""

from typing import ClassVar

from .schemas import IssueKind


class MonitoringError(Exception):
    kind: ClassVar[IssueKind] = IssueKind.UNKNOWN
    public_message: ClassVar[str] = "Error desconocido al consultar la fuente de monitoreo."

    def __init__(self, detail: str | None = None, *, status_code: int | None = None) -> None:
        self.detail = detail or self.public_message
        self.status_code = status_code
        super().__init__(self.detail)


class ProviderConfigurationError(MonitoringError):
    kind = IssueKind.CONFIGURATION
    public_message = "La integración no está configurada correctamente."


class ProviderAuthenticationError(MonitoringError):
    kind = IssueKind.AUTHENTICATION
    public_message = "OPNsense rechazó las credenciales de la API (HTTP 401)."


class ProviderPermissionError(MonitoringError):
    kind = IssueKind.PERMISSION
    public_message = "El usuario de la API no tiene permisos para este recurso (HTTP 403)."


class ProviderNotSupportedError(MonitoringError):
    kind = IssueKind.NOT_SUPPORTED
    public_message = "El recurso no existe o no está soportado en esta versión/hardware (HTTP 404)."


class ProviderTimeoutError(MonitoringError):
    kind = IssueKind.TIMEOUT
    public_message = "Tiempo de espera agotado al consultar OPNsense."


class ProviderTLSError(MonitoringError):
    kind = IssueKind.TLS
    public_message = "Falló la verificación TLS/SSL con OPNsense."


class ProviderConnectionError(MonitoringError):
    kind = IssueKind.CONNECTION
    public_message = "No se pudo establecer conexión con OPNsense."


class ProviderServerError(MonitoringError):
    kind = IssueKind.SERVER_ERROR
    public_message = "OPNsense respondió con un error interno (HTTP 5xx)."


class ProviderInvalidResponseError(MonitoringError):
    kind = IssueKind.INVALID_RESPONSE
    public_message = "OPNsense devolvió una respuesta inesperada o ilegible."
