"""Único adaptador de errores de aplicación a respuestas HTTP."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.core.errors import (ApplicationError, Unauthenticated, AccessDenied,
                             NotFound, Conflict, InvalidInput, ServiceUnavailable, PayloadTooLarge, RateLimited)

STATUS_CODES = {Unauthenticated: 401, AccessDenied: 403, NotFound: 404,
                Conflict: 409, InvalidInput: 400, ServiceUnavailable: 503, PayloadTooLarge: 413, RateLimited: 429}

async def application_error_handler(request: Request, exc: ApplicationError):
    headers = {}
    if request.url.path.endswith('/access') or request.url.path.startswith('/api/v1/guest/'):
        headers = {'Cache-Control': 'no-store, private', 'Pragma': 'no-cache'}
    return JSONResponse(status_code=STATUS_CODES.get(type(exc), 500),
                        content={'detail': exc.detail}, headers=headers)

def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApplicationError, application_error_handler)
