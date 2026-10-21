from datetime import datetime, timezone

import pytest

from app.auth.permissions import Permission
from app.chat.tools import (
    ChatToolError,
    ChatToolPermissionError,
    TOOL_REGISTRY,
    invoke_tool,
    openrouter_tool_definitions,
)
from app.monitoring.schemas import MonitoringResponse, MonitoringStatus


class FakeMonitoringService:
    def __init__(self):
        self.calls = []

    def _result(self, data=None):
        return MonitoringResponse(
            status=MonitoringStatus.OK,
            source="mock",
            collected_at=datetime.now(timezone.utc),
            data=data,
        )

    async def get_system(self):
        self.calls.append(("get_system", {}))
        return self._result({"hostname": "fw-netbot"})

    async def get_interfaces(self):
        self.calls.append(("get_interfaces", {}))
        return self._result([])

    async def get_clients(self):
        self.calls.append(("get_clients", {}))
        return self._result([])

    async def get_firewall_stats(self):
        self.calls.append(("get_firewall_stats", {}))
        return self._result({})

    async def get_firewall_events(self, *, limit, action):
        self.calls.append(("get_firewall_events", {"limit": limit, "action": action}))
        return self._result([])


@pytest.mark.asyncio
async def test_registry_contains_only_read_only_monitoring_tools():
    expected = {
        "get_system",
        "get_interfaces",
        "get_clients",
        "get_firewall_stats",
        "get_firewall_events",
    }

    assert set(TOOL_REGISTRY) == expected
    assert {item["function"]["name"] for item in openrouter_tool_definitions()} == expected
    assert all(tool.required_permission is Permission.MONITORING_READ for tool in TOOL_REGISTRY.values())


@pytest.mark.asyncio
async def test_firewall_event_tool_validates_args_and_calls_monitoring_service():
    service = FakeMonitoringService()
    result = await invoke_tool(
        "get_firewall_events",
        {"limit": 5, "action": "block"},
        service,
        frozenset({Permission.MONITORING_READ}),
    )

    assert service.calls == [
        ("get_firewall_events", {"limit": 5, "action": "block"})
    ]
    assert result["source"] == "mock"
    assert result["data"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,arguments",
    [
        ("not_registered", {}),
        ("get_firewall_events", {"limit": 1000}),
        ("get_system", {"command": "uname -a"}),
    ],
)
async def test_invalid_tool_calls_never_reach_monitoring(name, arguments):
    service = FakeMonitoringService()

    with pytest.raises(ChatToolError):
        await invoke_tool(
            name, arguments, service, frozenset({Permission.MONITORING_READ})
        )

    assert service.calls == []


@pytest.mark.asyncio
async def test_tool_permission_is_checked_before_monitoring_call():
    service = FakeMonitoringService()

    with pytest.raises(ChatToolPermissionError):
        await invoke_tool("get_system", {}, service, frozenset())

    assert service.calls == []
