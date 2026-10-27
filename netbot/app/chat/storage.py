"""Propiedad, ámbito y persistencia de conversaciones, independientes del LLM."""
import hashlib
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.roles import effective_permissions
from app.core.config import Settings
from app.networks.access import accessible_networks, require_network, network_read
from .models import ChatMessage, Conversation
from .schemas import ChatTurn, ConversationCreate


def authorization_key(db: Session, user: User) -> str:
    """Un historial no se reutiliza cuando cambia su contexto de autorización."""
    scope = {
        "permissions": sorted(p.value for p in effective_permissions(user)),
        "roles": sorted(r.name for r in user.roles),
        "networks": [n.id for n in accessible_networks(db, user)],
    }
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def conversation_query(db: Session, user: User):
    return select(Conversation).where(
        Conversation.user_id == user.id,
        Conversation.authorization_key == authorization_key(db, user),
    )


def owned_conversation(db: Session, user: User, conversation_id: str) -> Conversation:
    conversation = db.scalar(conversation_query(db, user).where(Conversation.id == conversation_id))
    if conversation is None:
        # Mismo resultado para un ID inexistente, ajeno o cuyo ámbito fue revocado.
        raise HTTPException(status_code=404, detail="Conversación no encontrada o acceso modificado.")
    if conversation.network_id is not None:
        require_network(db, user, conversation.network_id)
    return conversation


def new_conversation(db: Session, user: User, payload: ConversationCreate) -> Conversation:
    if payload.network_id is not None:
        require_network(db, user, payload.network_id)
    conversation = Conversation(
        user_id=user.id, network_id=payload.network_id, title=payload.title,
        authorization_key=authorization_key(db, user),
    )
    db.add(conversation)
    db.flush()
    return conversation


def network_context(db: Session, user: User, conversation: Conversation) -> list[dict]:
    return [
        network_read(n, user).model_dump()
        for n in accessible_networks(db, user)
        if conversation.network_id is None or n.id == conversation.network_id
    ]


def history_for_model(db: Session, conversation: Conversation, settings: Settings) -> list[ChatTurn]:
    if settings.chat_max_history_turns == 0:
        return []
    rows = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
                      .order_by(ChatMessage.id.desc()).limit(settings.chat_max_history_turns)).all()
    selected = []
    size = 0
    for row in rows:
        size += len(row.content)
        if size > settings.chat_max_history_chars:
            break
        selected.append(ChatTurn(role=row.role, content=row.content))
    return list(reversed(selected))


def persist_exchange(db: Session, user: User, conversation: Conversation, version: int,
                     message: str, answer: str, expected_key: str) -> int:
    # El proveedor puede tardar: releer identidad, roles y asignaciones al regresar.
    conversation_id = conversation.id
    db.expire_all()
    if not user.is_active or authorization_key(db, user) != expected_key:
        db.rollback()
        raise HTTPException(status_code=403, detail="Tu acceso cambió durante la consulta. Inicia una nueva conversación.")
    result = db.execute(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user.id,
        Conversation.authorization_key == expected_key, Conversation.version == version,
    ).values(version=version + 1, updated_at=datetime.now(timezone.utc)),
        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="La conversación cambió. Recárgala antes de enviar otro mensaje.")
    db.add_all([
        ChatMessage(conversation_id=conversation_id, role="user", content=message),
        ChatMessage(conversation_id=conversation_id, role="assistant", content=answer),
    ])
    if version == 0:
        db.execute(update(Conversation).where(Conversation.id == conversation_id).values(title=message[:100]),
                   execution_options={"synchronize_session": False})
    db.commit()
    return version + 1
