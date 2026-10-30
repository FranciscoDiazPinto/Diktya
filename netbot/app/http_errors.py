"""Único adaptador de errores de aplicación a respuestas HTTP."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from app.core.errors import (ApplicationError, Unauthenticated, AccessDenied,
                             NotFound, Conflict, InvalidInput, ServiceUnavailable, PayloadTooLarge, RateLimited)

STATUS_CODES = {Unauthenticated: 401, AccessDenied: 403, NotFound: 404,
                Conflict: 409, InvalidInput: 400, ServiceUnavailable: 503, PayloadTooLarge: 413, RateLimited: 429}

async def application_error_handler(request: Request, exc: ApplicationError):
    headers = {}
    if request.url.path.endswith('/access') or request.url.path.startswith('/api/v1/guest/'):
        headers = {'Cache-Control': 'no-store, private', 'Pragma': 'no-cache'}
    body = {'detail': exc.detail}
    if exc.field is not None:
        body['errors'] = {exc.field: exc.detail}
    return JSONResponse(status_code=STATUS_CODES.get(type(exc), 500),
                        content=body, headers=headers)

async def validation_error_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith(("/auth/", "/admin/users", "/admin/roles")):
        # No reflejar contraseñas/tokens en errores de validación.
        errors = [{key: error[key] for key in ("loc", "msg", "type") if key in error} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors}, headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(ApplicationError, application_error_handler)
