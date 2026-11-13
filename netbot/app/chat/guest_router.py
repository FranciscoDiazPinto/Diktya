"""Frontera pública de autoatención, separada de la API autenticada."""
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.request_security import client_peer
from app.networks.guest_access import GuestNetwork, GuestWifiQr, list_guest_networks, guest_wifi_qr
from .guest import sessions, TTL
from .provider import OpenRouterProvider, ChatProviderError, ChatProviderNotConfigured
from .schemas import ChatInputError


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(prefix="/guest", tags=["guest self service"], dependencies=[Depends(no_store)])


class GuestMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=2000)


class GuestAnswer(BaseModel):
    answer: str
    state: Literal["needs_information", "answered", "closed"] = "needs_information"
    needs_clarification: bool = False
    expires_in: int = TTL


class GuestSessionCreated(BaseModel):
    token: str
    expires_in: int = TTL


def guest_token(x_guest_session: str = Header(min_length=40, max_length=64)) -> str:
    sessions.get(x_guest_session)
    return x_guest_session


def get_guest_provider(settings: Settings = Depends(get_settings)):
    return OpenRouterProvider(settings)


@router.post("/sessions", response_model=GuestSessionCreated, status_code=201)
def create_session(request: Request):
    return GuestSessionCreated(token=sessions.create(client_peer(request.scope)))


@router.delete("/session", status_code=204)
def end_session(token: str = Depends(guest_token)):
    sessions.delete(token)


@router.post("/session/activity", status_code=204)
def activity(token: str = Depends(guest_token)):
    sessions.touch(token)


@router.post("/messages", response_model=GuestAnswer)
async def send_message(payload: GuestMessage, token: str = Depends(guest_token),
                       settings: Settings = Depends(get_settings), provider=Depends(get_guest_provider)):
    try:
        answer = await sessions.answer(token, payload.message, provider, settings)
        session = sessions.get(token)
        return GuestAnswer(answer=answer, state=session.dialogue_state,
                           needs_clarification=session.dialogue_state == "needs_information")
    except ChatInputError as exc:
        raise HTTPException(422, str(exc)) from None
    except ChatProviderNotConfigured:
        raise HTTPException(503, "El asistente no está configurado. Puedes usar el botón de QR Wi-Fi.") from None
    except ChatProviderError:
        raise HTTPException(502, "No se pudo responder. Inténtalo nuevamente o usa el botón de QR Wi-Fi.") from None


@router.get("/networks", response_model=list[GuestNetwork])
def networks(token: str = Depends(guest_token), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    sessions.touch(token)
    return list_guest_networks(db, settings)


@router.post("/networks/{network_id}/access", response_model=GuestWifiQr)
def wifi_access(network_id: int, token: str = Depends(guest_token), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    result = guest_wifi_qr(db, settings, network_id, sessions.get(token).contact)
    sessions.touch(token)
    return result


class GuestIdentification(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    contact: str = Field(min_length=3, max_length=320)


@router.post('/identify', response_model=list[GuestNetwork])
def identify(payload: GuestIdentification, token: str = Depends(guest_token), db: Session = Depends(get_db)):
    # Respuesta uniforme, sin consultar ni enumerar contactos registrados.
    raise HTTPException(403, 'La recuperación privada requiere verificación de identidad. Solicita ayuda al equipo.',
                        headers={'Cache-Control': 'no-store, private'})


# Recuperación verificada por correo, independiente del historial y del modelo.
from fastapi import BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import EmailStr
from app.networks.email_recovery import prepare_email, approve_and_reveal, build_recovery_mailer, recovery_origin, GENERIC_MESSAGE
from .recovery_pages import APPROVAL_HTML, APPROVAL_JS, APPROVAL_CSS


def get_recovery_mailer(settings: Settings = Depends(get_settings)):
    return build_recovery_mailer(settings)


class EmailRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    email: EmailStr = Field(max_length=320)


class EmailApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(min_length=40, max_length=64)


@router.post('/recovery/email', status_code=202)
def request_email_recovery(payload: EmailRecoveryRequest, background: BackgroundTasks,
                           token: str = Depends(guest_token), db: Session = Depends(get_db),
                           settings: Settings = Depends(get_settings), mailer=Depends(get_recovery_mailer)):
    background.add_task(prepare_email(db, settings, str(payload.email), mailer))
    return {'message': GENERIC_MESSAGE}


@router.get('/recovery/approve', response_class=HTMLResponse)
def recovery_approval_page():
    return HTMLResponse(APPROVAL_HTML, headers={
        'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src data:; base-uri 'none'; frame-ancestors 'none'",
        'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY', 'Cache-Control': 'no-store, private'})


@router.get('/recovery/approval.css')
def recovery_approval_styles():
    return Response(APPROVAL_CSS, media_type='text/css', headers={'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'})


@router.get('/recovery/approval.js')
def recovery_approval_script():
    return Response(APPROVAL_JS, media_type='application/javascript', headers={'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'})


@router.post('/recovery/approve', response_model=list[GuestWifiQr])
def approve_email_recovery(payload: EmailApprovalRequest, request: Request,
                           db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    if request.headers.get('origin') != recovery_origin(settings):
        raise HTTPException(403, 'Origen de confirmación no permitido.')
    return approve_and_reveal(db, settings, payload.token)
