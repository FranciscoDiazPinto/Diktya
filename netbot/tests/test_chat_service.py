import pytest

from app.auth.permissions import Permission
from app.chat.provider import (
    ChatProviderError,
    ProviderCompletion,
    ProviderToolCall,
)
from app.chat.schemas import ChatMessageResponse, ChatTurn
from app.chat.service import ChatService
from app.chat.tools import ChatToolPermissionError
from app.core.config import Settings
from app.monitoring.schemas import MonitoringResponse, MonitoringStatus
from app.monitoring.providers.mock import MockMonitoringProvider
from app.changes.service import VlanReservationService
from app.monitoring.service import MonitoringService

from datetime import datetime, timezone


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, *, messages, tools):
        self.calls.append({"messages": messages, "tools": tools})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeMonitoringService:
    def __init__(self):
        self.calls = []

    async def get_system(self):
        self.calls.append("get_system")
        return MonitoringResponse(
            status=MonitoringStatus.OK,
            source="mock",
            collected_at=datetime.now(timezone.utc),
            data={"hostname": "fw-netbot"},
        )


def make_service(responses, *, max_rounds=3):
    provider = FakeProvider(responses)
    monitoring = FakeMonitoringService()
    service = ChatService(
        settings=Settings(_env_file=None, chat_max_tool_rounds=max_rounds),
        provider=provider,
        monitoring_service=monitoring,
    )
    return service, provider, monitoring


@pytest.mark.asyncio
async def test_text_completion_uses_fixed_policy_and_returns_answer():
    service, provider, monitoring = make_service(
        [ProviderCompletion(content="La red está estable.")]
    )

    result = await service.answer(
        message="¿Cómo está la red?",
        history=[ChatTurn(role="user", content="Hola"), ChatTurn(role="assistant", content="Hola")],
        permissions=frozenset({Permission.MONITORING_READ}),
    )

    assert result == ChatMessageResponse(answer="La red está estable.", tools_used=[])
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert "Netbot" in provider.calls[0]["messages"][0]["content"]
    assert [item["role"] for item in provider.calls[0]["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert monitoring.calls == []


@pytest.mark.asyncio
async def test_monitoring_tool_call_is_executed_then_summarized():
    service, provider, monitoring = make_service(
        [
            ProviderCompletion(
                content=None,
                tool_calls=(
                    ProviderToolCall(id="call-1", name="get_system", arguments={}),
                ),
            ),
            ProviderCompletion(content="El firewall reporta estado normal."),
        ]
    )

    result = await service.answer(
        message="Consulta el estado actual",
        history=[],
        permissions=frozenset({Permission.MONITORING_READ}),
    )

    assert result.answer == "El firewall reporta estado normal."
    assert result.tools_used == ["get_system"]
    assert monitoring.calls == ["get_system"]
    second_messages = provider.calls[1]["messages"]
    assert second_messages[-2]["role"] == "assistant"
    assert second_messages[-1]["role"] == "tool"
    assert second_messages[-1]["tool_call_id"] == "call-1"


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_without_monitoring_call():
    service, _, monitoring = make_service(
        [
            ProviderCompletion(
                content=None,
                tool_calls=(ProviderToolCall(id="call-1", name="run_shell", arguments={}),),
            )
        ]
    )

    with pytest.raises(ChatProviderError):
        await service.answer(
            message="consulta",
            history=[],
            permissions=frozenset({Permission.MONITORING_READ}),
        )

    assert monitoring.calls == []


@pytest.mark.asyncio
async def test_prepared_vlan_proposal_is_returned_typed_and_not_persisted(db_session):
    monitoring = MonitoringService(MockMonitoringProvider())
    reservations = VlanReservationService(monitoring, db_session)
    provider = FakeProvider([
        ProviderCompletion(content=None, tool_calls=(ProviderToolCall(
            id="proposal-1", name="prepare_vlan_reservation", arguments={
                "parent_interface": "igc1", "tag": 20, "event_name": "Feria",
                "purpose": "Invitados", "ssid": "Evento",
            }),)),
        ProviderCompletion(content="Preparé la propuesta; confirma en el panel.")
    ])
    service = ChatService(settings=Settings(_env_file=None), provider=provider,
                          monitoring_service=monitoring, reservation_service=reservations)
    result = await service.answer(message="Reserva una VLAN", history=[], permissions=frozenset({
        Permission.MONITORING_READ, Permission.VLAN_RESERVE,
    }))
    assert result.reservation_proposal.tag == 20
    assert result.reservation_proposal.event_name == "Feria"
    assert reservations.list_active() == []
    offered = {tool["function"]["name"] for tool in provider.calls[0]["tools"]}
    assert "prepare_vlan_reservation" in offered


@pytest.mark.asyncio
async def test_tool_permission_is_checked_before_monitoring_call():
    service, _, monitoring = make_service(
        [
            ProviderCompletion(
                content=None,
                tool_calls=(ProviderToolCall(id="call-1", name="get_system", arguments={}),),
            )
        ]
    )

    with pytest.raises(ChatToolPermissionError):
        await service.answer(message="consulta", history=[], permissions=frozenset())

    assert monitoring.calls == []


@pytest.mark.asyncio
async def test_tool_call_round_limit_stops_before_extra_execution():
    repeated_call = ProviderCompletion(
        content=None,
        tool_calls=(ProviderToolCall(id="call-1", name="get_system", arguments={}),),
    )
    service, _, monitoring = make_service([repeated_call, repeated_call], max_rounds=1)

    with pytest.raises(ChatProviderError):
        await service.answer(
            message="consulta",
            history=[],
            permissions=frozenset({Permission.MONITORING_READ}),
        )

    assert monitoring.calls == ["get_system"]


@pytest.mark.asyncio
async def test_provider_error_is_propagated_for_api_translation():
    service, _, monitoring = make_service([ChatProviderError("safe provider error")])

    with pytest.raises(ChatProviderError, match="safe provider error"):
        await service.answer(
            message="consulta",
            history=[],
            permissions=frozenset({Permission.MONITORING_READ}),
        )

    assert monitoring.calls == []
