"""Recuperación de cuentas: nunca envía contraseñas antiguas."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import logging
import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.auth.models import User, RefreshToken
from app.auth.security import hash_password
from app.auth.audit import record_event
from app.core.config import settings
from .models import TelegramBinding, TelegramChallenge

log = logging.getLogger(__name__)

def now(): return datetime.now(timezone.utc)
def utc(dt): return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def digest(raw: str):
    return hmac.new(settings.jwt_secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()

def token(): return secrets.token_urlsafe(24)

def configured():
    return bool(settings.telegram_recovery_enabled and settings.telegram_bot_token and settings.telegram_webhook_secret)

async def send(chat_id: str, message: str) -> bool:
    if not configured(): return False
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            result = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token.get_secret_value()}/sendMessage",
                json={"chat_id": chat_id, "text": message},
            )
            result.raise_for_status()
            return result.json().get("ok") is True
    except (httpx.HTTPError, ValueError):
        log.warning("No se pudo enviar notificación Telegram")
        return False

def _invalidate(db: Session, user_id: int, kind: str):
    db.execute(update(TelegramChallenge).where(TelegramChallenge.user_id == user_id,
        TelegramChallenge.kind == kind, TelegramChallenge.consumed.is_(False)).values(consumed=True))

def create_link(db: Session, user: User) -> str:
    if not configured(): raise ValueError("Telegram no configurado")
    _invalidate(db, user.id, "link")
    raw = token()
    db.add(TelegramChallenge(user_id=user.id, kind="link", digest=digest(raw),
        created_at=now(), expires_at=now()+timedelta(minutes=10)))
    record_event(db, "auth.telegram.link.request", actor_id=user.id)
    db.commit()
    return raw

def accept_link(db: Session, raw: str, chat_id: str, private: bool) -> bool:
    if not private or not raw or len(raw)>128: return False
    from app.auth.service import _lock_administration
    _lock_administration(db)
    challenge = db.scalar(select(TelegramChallenge).where(TelegramChallenge.digest == digest(raw),
        TelegramChallenge.kind == "link", TelegramChallenge.consumed.is_(False)))
    if not challenge or utc(challenge.expires_at) <= now():
        db.rollback(); return False
    user = db.get(User, challenge.user_id)
    if not user or not user.is_active:
        db.rollback(); return False
    # Un chat nunca puede quedar asociado a dos cuentas.
    other = db.scalar(select(TelegramBinding).where(TelegramBinding.chat_id == chat_id))
    if other and other.user_id != user.id:
        db.rollback(); return False
    binding = db.get(TelegramBinding, user.id)
    if binding:
        binding.chat_id = chat_id
        binding.linked_at = now()
    else: db.add(TelegramBinding(user_id=user.id, chat_id=chat_id, linked_at=now()))
    challenge.consumed = True
    record_event(db, "auth.telegram.link.success", actor_id=user.id)
    db.commit()
    return True

async def request_reset(db: Session, identifier: str) -> None:
    # Respuesta idéntica para cuentas inexistentes y sin Telegram.
    if not configured(): return
    user = db.scalar(select(User).where(User.email == identifier.strip().lower()))
    binding = db.get(TelegramBinding, user.id) if user and user.is_active else None
    if not binding: return
    # Evitar spam: máximo un envío cada 60 segundos por usuario.
    recent = db.scalar(select(TelegramChallenge).where(TelegramChallenge.user_id == user.id,
        TelegramChallenge.kind == "reset", TelegramChallenge.created_at > now()-timedelta(seconds=60))
        .order_by(TelegramChallenge.id.desc()))
    if recent: return
    raw = str(secrets.randbelow(90000000)+10000000)
    _invalidate(db, user.id, "reset")
    challenge = TelegramChallenge(user_id=user.id, kind="reset", digest=digest(raw),
        created_at=now(), expires_at=now()+timedelta(minutes=10))
    db.add(challenge)
    db.commit()
    delivered = await send(binding.chat_id, f"NetBot: código de recuperación: {raw}. Vence en 10 minutos. No lo compartas.")
    if not delivered:
        challenge.consumed = True
        db.commit()
    else:
        record_event(db, "auth.telegram.reset.sent", target_id=user.id)
        db.commit()

def complete_reset(db: Session, identifier: str, code: str, new_password: str) -> bool:
    if not configured(): return False
    from app.auth.service import _lock_administration
    _lock_administration(db)
    user = db.scalar(select(User).where(User.email == identifier.strip().lower()))
    if not user or not user.is_active or not db.get(TelegramBinding, user.id):
        db.rollback(); return False
    challenge = db.scalar(select(TelegramChallenge).where(TelegramChallenge.user_id == user.id,
        TelegramChallenge.kind == "reset", TelegramChallenge.consumed.is_(False))
        .order_by(TelegramChallenge.id.desc()))
    if not challenge or utc(challenge.expires_at) <= now() or challenge.attempts >= 5:
        db.rollback(); return False
    challenge.attempts += 1
    if not hmac.compare_digest(challenge.digest, digest(code)):
        if challenge.attempts >= 5: challenge.consumed = True
        db.commit(); return False
    user.hashed_password = hash_password(new_password)
    user.failed_login_attempts = 0
    user.login_locked_until = None
    challenge.consumed = True
    _invalidate(db, user.id, "reset")
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None)).values(revoked_at=now()))
    record_event(db, "auth.telegram.reset.completed", target_id=user.id)
    db.commit()
    return True
