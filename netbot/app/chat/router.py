"""API autenticada del chatbot."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from uuid import UUID
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.config import Settings, get_settings
from app.monitoring.dependencies import MonitoringServiceDep
from app.core.database import get_db
from app.changes.service import VlanReservationService

from .provider import ChatProviderError, ChatProviderNotConfigured, OpenRouterProvider
from .schemas import ChatInputError, ChatSendRequest, ConversationCreate, ConversationRead, ConversationDetail, ChatMessageResponse
from .service import ChatService
from .tools import ChatToolPermissionError
from .application import answer_message
from . import storage
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
    return storage.create_conversation(db, user, payload)


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return storage.list_conversations(db, user, limit, offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: UUID,
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=100),
    before_id: int | None = Query(default=None, gt=0),
):
    return storage.conversation_detail(db, user, str(conversation_id), limit, before_id)


@router.post("/messages", response_model=ChatMessageResponse)
async def send_message(
    payload: ChatSendRequest,
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    chat_service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_chat_settings),
    db: Session = Depends(get_db),
) -> ChatMessageResponse:
    try:
        return await answer_message(db, user, payload, chat_service, settings)
    except ChatInputError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except ChatToolPermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        ) from None
    except ChatProviderNotConfigured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El chatbot no está configurado.",
        ) from None
    except ChatProviderError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="El chatbot no pudo completar la consulta. Inténtalo nuevamente.",
        ) from None
