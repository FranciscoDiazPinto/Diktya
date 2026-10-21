from app.auth.models import Role, User
from app.auth.security import hash_password
from app.chat.provider import ChatProviderError, ChatProviderNotConfigured, ChatProviderUnavailable
from app.chat.router import get_chat_service
from app.chat.schemas import ChatMessageResponse
from app.core.config import Settings
from app.main import app


class FakeChatService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def answer(self, *, message, history, permissions):
        self.calls.append((message, history, permissions))
        if self.error:
            raise self.error
        return ChatMessageResponse(answer="Consulta recibida.", tools_used=[])


def install_chat_service(service):
    app.dependency_overrides[get_chat_service] = lambda: service


def test_chat_requires_authentication(client):
    response = client.post("/api/v1/chat/messages", json={"message": "¿Cómo está la red?"})

    assert response.status_code == 401


def test_default_roles_can_use_chat_and_receive_server_permissions(
    client, db_session, viewer_user, admin_user, login
):
    operator_role = db_session.query(Role).filter_by(name="operador").one()
    operator = User(
        email="operator@example.com",
        hashed_password=hash_password("operator-password"),
        roles=[operator_role],
    )
    db_session.add(operator)
    db_session.commit()
    service = FakeChatService()
    install_chat_service(service)

    for email, password in (
        (viewer_user.email, "viewer-password"),
        (operator.email, "operator-password"),
        (admin_user.email, "admin-password"),
    ):
        _, headers = login(email, password)
        response = client.post(
            "/api/v1/chat/messages",
            json={"message": "¿Hay clientes conectados?"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json() == {"answer": "Consulta recibida.", "tools_used": [], "reservation_proposal": None}

    assert len(service.calls) == 3
    assert all("monitoring:read" in {permission.value for permission in call[2]} for call in service.calls)


def test_user_without_chat_permission_is_rejected_before_service_call(
    client, db_session, login
):
    role = Role(name="sin-chat", description="Sin permiso de chat")
    user = User(
        email="no-chat@example.com",
        hashed_password=hash_password("no-chat-password"),
        roles=[role],
    )
    db_session.add_all([role, user])
    db_session.commit()
    service = FakeChatService()
    install_chat_service(service)
    _, headers = login(user.email, "no-chat-password")

    response = client.post(
        "/api/v1/chat/messages",
        json={"message": "Hola"},
        headers=headers,
    )

    assert response.status_code == 403
    assert service.calls == []


def test_oversized_message_is_rejected(client, viewer_user, login, monkeypatch):
    from app.chat import router as chat_router

    monkeypatch.setattr(
        chat_router,
        "get_settings",
        lambda: Settings(_env_file=None, chat_max_message_chars=3),
    )
    service = FakeChatService()
    install_chat_service(service)
    _, headers = login(viewer_user.email, "viewer-password")

    response = client.post(
        "/api/v1/chat/messages",
        json={"message": "demasiado largo"},
        headers=headers,
    )

    assert response.status_code == 422
    assert service.calls == []


def test_provider_configuration_error_returns_503(client, viewer_user, login):
    service = FakeChatService(ChatProviderNotConfigured("private key text"))
    install_chat_service(service)
    _, headers = login(viewer_user.email, "viewer-password")

    response = client.post(
        "/api/v1/chat/messages", json={"message": "Hola"}, headers=headers
    )

    assert response.status_code == 503
    assert "private key text" not in response.text


def test_provider_outage_returns_502_without_upstream_details(client, viewer_user, login):
    service = FakeChatService(ChatProviderUnavailable("private upstream body"))
    install_chat_service(service)
    _, headers = login(viewer_user.email, "viewer-password")

    response = client.post(
        "/api/v1/chat/messages", json={"message": "Hola"}, headers=headers
    )

    assert response.status_code == 502
    assert "private upstream body" not in response.text


def test_unexpected_provider_error_is_sanitized(client, viewer_user, login):
    service = FakeChatService(ChatProviderError("sensitive upstream detail"))
    install_chat_service(service)
    _, headers = login(viewer_user.email, "viewer-password")

    response = client.post(
        "/api/v1/chat/messages", json={"message": "Hola"}, headers=headers
    )

    assert response.status_code == 502
    assert "sensitive upstream detail" not in response.text
