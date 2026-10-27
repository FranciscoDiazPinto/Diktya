"""API autenticada del chatbot."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from uuid import UUID
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import effective_permissions
from app.core.config import Settings, get_settings
from app.monitoring.dependencies import MonitoringServiceDep
from app.core.database import get_db
from app.changes.service import VlanReservationService

from .provider import (
    ChatProviderError,
    ChatProviderNotConfigured,
    OpenRouterProvider,
)
from .schemas import (
    ChatInputError,
    ChatMessageRequest,
    ChatSendRequest, ConversationCreate, ConversationRead, ConversationDetail, StoredMessageRead,
    ChatMessageResponse,
    normalize_chat_request,
)
from .service import ChatService
from .tools import ChatToolPermissionError
from .models import ChatMessage, Conversation
from .storage import (conversation_query, owned_conversation, new_conversation,
                      history_for_model, persist_exchange, network_context)
from .policy import profile_for_user
from .support import CustomerSupport

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_settings() -> Settings:
    return get_settings()


def get_chat_service(
    monitoring_service: MonitoringServiceDep,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
) -> ChatService:
    settings = get_chat_settings()
    return ChatService(
        settings=settings,
        provider=OpenRouterProvider(settings),
        monitoring_service=monitoring_service,
        reservation_service=VlanReservationService(monitoring_service, db),
        customer_support=CustomerSupport(db, user, monitoring_service, settings),
    )


@router.post("/conversations", response_model=ConversationRead, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    db: Session = Depends(get_db),
):
    conversation = new_conversation(db, user, payload)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return db.scalars(conversation_query(db, user).order_by(
        Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit).offset(offset)).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
):
    conversation = owned_conversation(db, user, str(conversation_id))
    query = select(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
    if before_id is not None:
        query = query.where(ChatMessage.id < before_id)
    rows = db.scalars(query.order_by(ChatMessage.id.desc()).limit(limit)).all()
    return ConversationDetail(**ConversationRead.model_validate(conversation).model_dump(),
                              messages=[StoredMessageRead.model_validate(m) for m in reversed(rows)])


@router.post("/messages", response_model=ChatMessageResponse)
async def send_message(
    payload: ChatSendRequest,
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    chat_service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_chat_settings),
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    try:
        request = normalize_chat_request(ChatMessageRequest(message=payload.message), settings)
        conversation = (owned_conversation(db, user, str(payload.conversation_id))
                        if payload.conversation_id else new_conversation(db, user, ConversationCreate()))
        version = conversation.version
        key = conversation.authorization_key
        if payload.version is not None and payload.version != version:
            raise HTTPException(status_code=409, detail="La conversación cambió. Recárgala antes de enviar otro mensaje.")
        response = await chat_service.answer(
            message=request.message,
            history=history_for_model(db, conversation, settings),
            permissions=effective_permissions(user),
            networks=network_context(db, user, conversation),
            profile=profile_for_user(user),
        )
        new_version = persist_exchange(db, user, conversation, version, request.message, response.answer, key)
        return response.model_copy(update={"conversation_id": conversation.id, "version": new_version})
    except HTTPException:
        db.rollback()
        raise
    except ChatInputError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except ChatToolPermissionError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        ) from None
    except ChatProviderNotConfigured:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El chatbot no está configurado.",
        ) from None
    except ChatProviderError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El chatbot no pudo completar la consulta. Inténtalo nuevamente.",
        ) from None
