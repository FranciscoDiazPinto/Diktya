import base64
import logging
import ssl

import httpx
import pytest
from pydantic import SecretStr

from app.monitoring.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInvalidResponseError,
    ProviderNotSupportedError,
    ProviderPermissionError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderTLSError,
)
from app.monitoring.providers.opnsense.client import OPNsenseClient, normalize_base_url

from .fixtures import CPU_SSE

KEY = "super-key-123"
SECRET = "super-secret-456"


def make_client(handler, **kwargs) -> OPNsenseClient:
    return OPNsenseClient(
        "https://fw.test/",
        SecretStr(KEY),
        SecretStr(SECRET),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_uses_basic_auth_with_key_and_secret():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    assert await client.get_json("/api/diagnostics/system/system_time") == {"ok": True}
    expected = "Basic " + base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    assert seen["auth"] == expected
    assert seen["path"] == "/api/diagnostics/system/system_time"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderPermissionError),
        (404, ProviderNotSupportedError),
        (500, ProviderServerError),
        (503, ProviderServerError),
        (302, ProviderInvalidResponseError),
    ],
)
async def test_http_status_mapping(status, error):
    client = make_client(lambda request: httpx.Response(status))
    with pytest.raises(error) as info:
        await client.get_json("/api/x")
    assert info.value.status_code == status


async def test_invalid_json_body():
    client = make_client(lambda request: httpx.Response(200, text="<html>login</html>"))
    with pytest.raises(ProviderInvalidResponseError):
        await client.get_json("/api/x")


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slow")])
async def test_timeouts(exc):
    def handler(request):
        raise exc

    with pytest.raises(ProviderTimeoutError):
        await make_client(handler).get_json("/api/x")


async def test_connection_refused():
    def handler(request):
        raise httpx.ConnectError("[Errno 111] Connection refused")

    with pytest.raises(ProviderConnectionError):
        await make_client(handler).get_json("/api/x")


async def test_tls_failure_is_distinguished_from_connection_failure():
    def handler(request):
        error = httpx.ConnectError("handshake failed")
        error.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")
        raise error

    with pytest.raises(ProviderTLSError):
        await make_client(handler).get_json("/api/x")


async def test_sse_returns_first_event_only():
    def handler(request):
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(200, content=CPU_SSE + b'data: {"total": 99}\n\n')

    event = await make_client(handler).stream_first_json_event("/api/diagnostics/cpu_usage/stream")
    assert event["total"] == 14


async def test_sse_without_events_is_invalid():
    client = make_client(lambda request: httpx.Response(200, content=b": keepalive\n\n"))
    with pytest.raises(ProviderInvalidResponseError):
        await client.stream_first_json_event("/api/x")


async def test_sse_http_error_is_translated():
    client = make_client(lambda request: httpx.Response(403))
    with pytest.raises(ProviderPermissionError):
        await client.stream_first_json_event("/api/x")


async def test_credentials_never_appear_in_logs_or_repr(caplog):
    caplog.set_level(logging.DEBUG)
    client = make_client(lambda request: httpx.Response(500))
    with pytest.raises(ProviderServerError):
        await client.get_json("/api/x")
    encoded = base64.b64encode(f"{KEY}:{SECRET}".encode()).decode()
    for secret in (KEY, SECRET, encoded):
        assert secret not in caplog.text
        assert secret not in repr(client)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://fw.test", "https://fw.test"),
        ("https://fw.test/", "https://fw.test"),
        ("https://fw.test/api", "https://fw.test"),
        ("https://fw.test/api/", "https://fw.test"),
        ("  http://10.0.0.1:8443/ ", "http://10.0.0.1:8443"),
    ],
)
def test_normalize_base_url(raw, expected):
    assert normalize_base_url(raw) == expected
