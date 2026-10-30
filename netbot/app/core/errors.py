"""Errores públicos de aplicación. Sin dependencia de FastAPI ni transporte."""

class ApplicationError(Exception):
    def __init__(self, detail: str, *, field: str | None = None):
        self.detail = detail
        self.field = field
        super().__init__(detail)

class Unauthenticated(ApplicationError): pass
class AccessDenied(ApplicationError): pass
class NotFound(ApplicationError): pass
class Conflict(ApplicationError): pass
class InvalidInput(ApplicationError): pass
class ServiceUnavailable(ApplicationError): pass
class PayloadTooLarge(ApplicationError): pass

class RateLimited(ApplicationError): pass
