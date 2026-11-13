"""Auditoría 2026-11: ninguna conexión de base queda retenida durante la espera del LLM."""
from sqlalchemy import func, select, text

from app.auth.models import Role, User
from app.auth.security import hash_password
from app.chat.models import Conversation
from app.chat.provider import ProviderCompletion
from app.chat.router import get_chat_service
from app.chat.service import ChatService
from app.core.config import Settings
from app.main import app


class Provider:
    def __init__(self, db, fail=False):
        self.db, self.fail, self.in_transaction = db, fail, []

    async def complete(self, *, messages, tools):
        self.in_transaction.append(self.db.in_transaction())
        if self.fail:
            from app.chat.provider import ChatProviderError
            raise ChatProviderError('sin servicio')
        return ProviderCompletion(content='respuesta')


def service_for(db, provider):
    settings = Settings(_env_file=None, openrouter_api_key='k', openrouter_model='m')
    return ChatService(settings=settings, provider=provider, monitoring_service=None, release_connection=db.rollback)


def test_no_open_transaction_while_waiting_for_the_model(client, db_session, viewer_user, login):
    provider = Provider(db_session)
    app.dependency_overrides[get_chat_service] = lambda: service_for(db_session, provider)
    _, headers = login(viewer_user.email, 'viewer-password')
    conversation = client.post('/api/v1/chat/conversations', headers=headers, json={}).json()
    first = client.post('/api/v1/chat/messages', headers=headers, json={'message': 'hola', 'conversation_id': conversation['id'], 'version': 0})
    assert first.status_code == 200 and first.json()['version'] == 1
    assert provider.in_transaction == [False]
    app.dependency_overrides.pop(get_chat_service)


def test_new_conversation_is_created_only_after_the_answer(client, db_session, viewer_user, login):
    app.dependency_overrides[get_chat_service] = lambda: service_for(db_session, Provider(db_session, fail=True))
    _, headers = login(viewer_user.email, 'viewer-password')
    before = db_session.scalar(select(func.count()).select_from(Conversation))
    assert client.post('/api/v1/chat/messages', headers=headers, json={'message': 'hola'}).status_code == 502
    assert db_session.scalar(select(func.count()).select_from(Conversation)) == before
    provider = Provider(db_session)
    app.dependency_overrides[get_chat_service] = lambda: service_for(db_session, provider)
    created = client.post('/api/v1/chat/messages', headers=headers, json={'message': 'hola'})
    assert created.status_code == 200 and created.json()['conversation_id']
    assert db_session.scalar(select(func.count()).select_from(Conversation)) == before + 1
    app.dependency_overrides.pop(get_chat_service)
