"""API autenticada del chatbot."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.auth.roles import DEFAULT_ROLES, RoleName
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
    ChatMessageResponse,
    normalize_chat_request,
)
from .service import ChatService
from .tools import ChatToolPermissionError

router = APIRouter(prefix="/chat", tags=["chat"])


def get_chat_settings() -> Settings:
    return get_settings()


def get_chat_service(
    monitoring_service: MonitoringServiceDep,
    db: Session = Depends(get_db),
) -> ChatService:
    settings = get_chat_settings()
    return ChatService(
        settings=settings,
        provider=OpenRouterProvider(settings),
        monitoring_service=monitoring_service,
        reservation_service=VlanReservationService(monitoring_service, db),
    )


def _effective_permissions(user: User) -> frozenset[Permission]:
    permissions: set[Permission] = set()
    for role in user.roles:
        try:
            role_name = RoleName(role.name)
        except ValueError:
            continue
        permissions.update(DEFAULT_ROLES[role_name].permissions)
    return frozenset(permissions)


@router.post("/messages", response_model=ChatMessageResponse)
async def send_message(
    payload: ChatMessageRequest,
    user: User = Depends(require_permission(Permission.CHAT_USE.value)),
    chat_service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_chat_settings),
) -> ChatMessageResponse:
    try:
        request = normalize_chat_request(payload, settings)
        return await chat_service.answer(
            message=request.message,
            history=request.history,
            permissions=_effective_permissions(user),
        )
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
