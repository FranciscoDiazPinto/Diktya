"""Endpoints de vinculación y restablecimiento de cuenta."""
import hmac
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.database import get_db
from app.core.config import settings
from . import service

router = APIRouter(prefix="/auth/telegram", tags=["telegram-recovery"])

class ResetRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)

class ResetComplete(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^[0-9]{8}$")
    new_password: str = Field(min_length=12, max_length=128)

@router.post("/link")
def link(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not service.configured(): raise HTTPException(503, "Telegram no disponible")
    raw = service.create_link(db, user)
    # El nombre del bot se configura por separado; no exponer el token de API.
    return {"link_token": raw, "expires_in_seconds": 600,
            "instruction": "Enviar /start <link_token> al bot oficial de NetBot en chat privado"}

@router.post("/request-reset", status_code=202)
async def request_reset(data: ResetRequest, db: Session = Depends(get_db)):
    await service.request_reset(db, data.identifier)
    return {"message": "Si la cuenta tiene Telegram vinculado, recibirá instrucciones."}

@router.post("/complete-reset")
def complete_reset(data: ResetComplete, db: Session = Depends(get_db)):
    if not service.complete_reset(db, data.identifier, data.code, data.new_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Código inválido o vencido")
    return {"message": "Contraseña actualizada; inicia sesión nuevamente."}

@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: Session = Depends(get_db),
                  secret: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token")):
    expected = settings.telegram_webhook_secret.get_secret_value() if settings.telegram_webhook_secret else ""
    if not service.configured() or not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(403, "Forbidden")
    if int(request.headers.get("content-length", "0") or "0") > 8192:
        raise HTTPException(413, "Payload too large")
    payload = await request.json()
    message = payload.get("message") or {}
    chat = message.get("chat") or {}
    text = message.get("text") or ""
    if chat.get("type") == "private" and isinstance(text, str) and text.startswith("/start "):
        raw = text.split(" ", 1)[1].strip()
        if len(raw) <= 128:
            ok = service.accept_link(db, raw, str(chat.get("id", "")), True)
            await service.send(str(chat.get("id", "")),
                "NetBot: cuenta vinculada correctamente." if ok else "NetBot: código inválido o vencido.")
    return {"ok": True}
