"""Frontera pública de autoatención, separada de la API autenticada."""
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.networks.guest_access import GuestNetwork, GuestWifiQr, list_guest_networks, guest_wifi_qr, client_networks
from app.networks.recipients import normalize_contact
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
def create_session():
    return GuestSessionCreated(token=sessions.create())


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
        return GuestAnswer(answer=await sessions.answer(token, payload.message, provider, settings))
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
    sessions.begin_identification(token)
    contact = normalize_contact(payload.contact)
    result = client_networks(db, contact)
    if not result:
        # No confirma existencia del cliente ni expone redes de otra persona.
        raise HTTPException(403, 'No se pudo habilitar el acceso con esos datos. Revisa lo ingresado o solicita ayuda al equipo.', headers={'Cache-Control': 'no-store, private'})
    sessions.set_contact(token, contact)
    return result
