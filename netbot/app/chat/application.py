"""Caso de uso conversacional. La ruta HTTP no coordina persistencia ni permisos."""
from app.auth.roles import effective_permissions
from app.auth.access import require_user_permission
from app.auth.permissions import Permission
from app.core.errors import Conflict
from sqlalchemy.orm import Session
from app.auth.models import User
from app.core.config import Settings
from .service import ChatService
from .schemas import ChatMessageRequest, ChatMessageResponse, ChatSendRequest, ConversationCreate, normalize_chat_request
from .storage import owned_conversation, new_conversation, history_for_model, network_context, persist_exchange
from .policy import profile_for_user

async def answer_message(db: Session, user: User, payload: ChatSendRequest,
                         chat_service: ChatService, settings: Settings) -> ChatMessageResponse:
    try:
        require_user_permission(db, user, Permission.CHAT_USE)
        request = normalize_chat_request(ChatMessageRequest(message=payload.message), settings)
        conversation = (owned_conversation(db, user, str(payload.conversation_id))
                        if payload.conversation_id else new_conversation(db, user, ConversationCreate()))
        version = conversation.version
        key = conversation.authorization_key
        if payload.version is not None and payload.version != version:
            raise Conflict("La conversación cambió. Recárgala antes de enviar otro mensaje.")
        response = await chat_service.answer(
            message=request.message,
            history=history_for_model(db, conversation, settings),
            permissions=effective_permissions(user),
            networks=network_context(db, user, conversation),
            profile=profile_for_user(user),
        )
        new_version = persist_exchange(db, user, conversation, version, request.message, response.answer, key)
        return response.model_copy(update={"conversation_id": conversation.id, "version": new_version})
    except Exception:
        db.rollback()
        raise
