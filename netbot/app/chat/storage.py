"""Propiedad, ámbito y persistencia de conversaciones, independientes del LLM."""
from app.core.errors import AccessDenied, NotFound, Conflict
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.roles import effective_permissions
from app.core.config import Settings
from app.networks.access import accessible_network_ids, assert_network_access, authorized_network_data
from .models import ChatMessage, Conversation
from .schemas import ChatTurn, ConversationCreate, ConversationRead, ConversationDetail, StoredMessageRead


def authorization_key(db: Session, user: User) -> str:
    """Un historial no se reutiliza cuando cambia su contexto de autorización."""
    scope = {
        "permissions": sorted(p.value for p in effective_permissions(user)),
        "roles": sorted(r.name for r in user.roles),
        "networks": accessible_network_ids(db, user),
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
        raise NotFound("Conversación no encontrada o acceso modificado.")
    if conversation.network_id is not None:
        assert_network_access(db, user, conversation.network_id)
    return conversation


def new_conversation(db: Session, user: User, payload: ConversationCreate) -> Conversation:
    if payload.network_id is not None:
        assert_network_access(db, user, payload.network_id)
    conversation = Conversation(
        user_id=user.id, network_id=payload.network_id, title=payload.title,
        authorization_key=authorization_key(db, user),
    )
    db.add(conversation)
    db.flush()
    return conversation


def network_context(db: Session, user: User, conversation: Conversation) -> list[dict]:
    return [
        n.model_dump()
        for n in authorized_network_data(db, user)
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
        raise AccessDenied("Tu acceso cambió durante la consulta. Inicia una nueva conversación.")
    result = db.execute(update(Conversation).where(
        Conversation.id == conversation_id, Conversation.user_id == user.id,
        Conversation.authorization_key == expected_key, Conversation.version == version,
    ).values(version=version + 1, updated_at=datetime.now(timezone.utc)),
        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise Conflict("La conversación cambió. Recárgala antes de enviar otro mensaje.")
    db.add_all([
        ChatMessage(conversation_id=conversation_id, role="user", content=message),
        ChatMessage(conversation_id=conversation_id, role="assistant", content=answer),
    ])
    if version == 0:
        db.execute(update(Conversation).where(Conversation.id == conversation_id).values(title=message[:100]),
                   execution_options={"synchronize_session": False})
    db.commit()
    return version + 1


def list_conversations(db: Session, user: User, limit: int, offset: int) -> list[ConversationRead]:
    rows = db.scalars(conversation_query(db, user).order_by(
        Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit).offset(offset)).all()
    return [ConversationRead.model_validate(row) for row in rows]


def conversation_detail(db: Session, user: User, conversation_id: str, limit: int, before_id: int | None) -> ConversationDetail:
    conversation = owned_conversation(db, user, conversation_id)
    query = select(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    rows = db.scalars(query.order_by(ChatMessage.id.desc()).limit(limit)).all()
    return ConversationDetail(**ConversationRead.model_validate(conversation).model_dump(),
                              messages=[StoredMessageRead.model_validate(m) for m in reversed(rows)])


def create_conversation(db: Session, user: User, payload: ConversationCreate) -> ConversationRead:
    conversation = new_conversation(db, user, payload)
    db.commit()
    db.refresh(conversation)
    return ConversationRead.model_validate(conversation)
