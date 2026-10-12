"""Tests for /api/mcp/agent streamable-HTTP MCP server endpoint.

An agent connects to /api/mcp/agent with its OWN Ed25519 registry JWT
(scope a2a_receive/a2a_send/project_tasks), never the owner session/password.
The MCP server exposes tools that wrap existing internal routes.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.agent_registry_store import (
    _b64url_encode,
    load_or_create_signing_keypair,
    mint_registry_token,
)
from tinyagentos.auth import hash_password
from taos_test_csrf import csrf_event_hooks


def _mcp_available() -> bool:
    """Check if mcp extra is installed at runtime."""
    try:
        import mcp
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        return True
    except ImportError:
        return False


_BUS_PATCH = "tinyagentos.routes.a2a_bus.httpx.AsyncClient"


@pytest_asyncio.fixture
async def mcp_agent_client(app, tmp_data_dir):
    """Admin client with the registry + grants stores initialised.

    Exposes ._app so tests can register agents / mint tokens directly against the
    stores and drive bare (cookieless) requests with a Bearer header.
    """
    for attr in ("agent_registry", "agent_grants", "metrics"):
        store = getattr(app.state, attr)
        if store._db is None:
            await store.init()

    app.state.auth.setup_user("admin", "Test Admin", "", "testpass")
    record = app.state.auth.find_user("admin")
    uid = record["id"] if record else ""
    token = app.state.auth.create_session(user_id=uid, long_lived=True)
    app.state._startup_complete = True

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"taos_session": token},
        event_hooks=csrf_event_hooks(),
    ) as c:
        c._app = app
        c._test_admin_uid = uid
        yield c

    for attr in ("agent_registry", "agent_grants", "metrics"):
        store = getattr(app.state, attr)
        if store._db is not None:
            await store.close()


async def _make_agent_token(app, *, scopes=("a2a_receive",), origin="taos-deployed"):
    """Register an agent, add its grants, and return (canonical_id, signed JWT)."""
    registry = app.state.agent_registry
    grants = app.state.agent_grants
    priv, _pub = app.state.agent_registry_keypair

    rec = await registry.register(
        framework="taosmd",
        display_name="MCP Agent",
        origin=origin,
        handle="@mcp-agent",
    )
    cid = rec["canonical_id"]
    for scope in scopes:
        await grants.add_grant(cid, scope)
    token = mint_registry_token(cid, priv, user_id="u", framework="taosmd")
    return cid, token


def _bare(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _mock_bus_client(json_payload: dict):
    """Return a mock httpx.AsyncClient whose async context manager yields a
    client that returns *json_payload* from .get().json()."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = json_payload

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    return mock_ctx


def _mock_bus_post(json_payload: dict, *, raise_on_status: bool = False):
    """A mock httpx.AsyncClient whose async ctx yields a client whose
    .post().json() returns *json_payload*. If *raise_on_status* the mocked
    response.raise_for_status() raises, simulating a bus error."""
    mock_resp = MagicMock()
    if raise_on_status:
        mock_resp.raise_for_status = MagicMock(side_effect=RuntimeError("bus 500"))
    else:
        mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = json_payload

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx, mock_client


class TestMcpAgentEndpointAvailability:
    """Basic availability / auth-gate tests for /api/mcp/agent."""

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_no_bearer_returns_401(self, mcp_agent_client):
        """No Authorization header -> 401."""
        async with _bare(mcp_agent_client._app) as bare:
            resp = await bare.post("/api/mcp/agent", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert resp.status_code == 401

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_invalid_token_returns_401(self, mcp_agent_client):
        """Malformed token -> 401."""
        async with _bare(mcp_agent_client._app) as bare:
            resp = await bare.post(
                "/api/mcp/agent",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                headers={"Authorization": "Bearer not-a-valid-token"},
            )
        assert resp.status_code == 401

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_token_signed_by_different_key_returns_401(self, mcp_agent_client):
        """Token signed with foreign key -> 401."""
        registry = mcp_agent_client._app.state.agent_registry
        grants = mcp_agent_client._app.state.agent_grants
        rec = await registry.register(framework="taosmd", display_name="Foreign", handle="@foreign")
        cid = rec["canonical_id"]
        await grants.add_grant(cid, "a2a_receive")
        with tempfile.TemporaryDirectory() as d:
            foreign_priv, _ = load_or_create_signing_keypair(Path(d))
        bad_token = mint_registry_token(cid, foreign_priv, user_id="u", framework="taosmd")
        async with _bare(mcp_agent_client._app) as bare:
            resp = await bare.post(
                "/api/mcp/agent",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                headers={"Authorization": f"Bearer {bad_token}"},
            )
        assert resp.status_code == 401


class TestMcpAgentTools:
    """Tool-specific tests for the MCP agent endpoint."""

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_send_requires_a2a_send_scope(self, mcp_agent_client):
        """Token without a2a_send calling send tool -> tool error, nothing posted."""
        cid, token = await _make_agent_token(mcp_agent_client._app, scopes=("a2a_receive",))
        with patch(_BUS_PATCH, return_value=_mock_bus_post({"id": 1, "from": cid, "thread": "build"})):
            async with _bare(mcp_agent_client._app) as bare:
                resp = await bare.post(
                    "/api/mcp/agent",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "send", "arguments": {"thread": "build", "text": "hi"}},
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        data = resp.json()
        # Should return a tool error (not HTTP 403)
        assert "error" in data or "result" in data
        if "result" in data:
            result = data["result"]
            assert result.get("isError") is True

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_send_forces_from_to_token_identity(self, mcp_agent_client):
        """send tool posts with from = token identity even when argument tries to set another sender."""
        cid, token = await _make_agent_token(mcp_agent_client._app, scopes=("a2a_send", "a2a_receive"))
        assert cid != "@somebody-else"
        ctx, client = _mock_bus_post({"id": 1, "from": cid, "thread": "build"})
        with patch(_BUS_PATCH, return_value=ctx):
            async with _bare(mcp_agent_client._app) as bare:
                resp = await bare.post(
                    "/api/mcp/agent",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "send",
                            "arguments": {"thread": "build", "text": "hi", "from": "@somebody-else"},
                        },
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        # Verify the bus was called with the token's canonical_id, not the spoofed from
        sent = client.post.call_args.kwargs["json"]
        assert sent["from"] == cid
        assert sent["thread"] == "build"
        assert sent["body"] == "hi"

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_inbox_returns_messages_after_cursor(self, mcp_agent_client):
        """inbox(since) returns only messages after the cursor."""
        cid, token = await _make_agent_token(mcp_agent_client._app, scopes=("a2a_receive",))
        # Return messages with different timestamps
        payload = {
            "messages": [
                {"id": "1", "ts": 1000.0, "from": "other", "body": "old", "thread": "general"},
                {"id": "2", "ts": 2000.0, "from": "other", "body": "new", "thread": "general"},
                {"id": "3", "ts": 3000.0, "from": "other", "body": "newer", "thread": "general"},
            ]
        }
        with patch(_BUS_PATCH, return_value=_mock_bus_client(payload)):
            async with _bare(mcp_agent_client._app) as bare:
                resp = await bare.post(
                    "/api/mcp/agent",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "inbox", "arguments": {"since": 1500.0}},
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        # Should only return messages with ts > 1500
        messages = result.get("messages", [])
        assert len(messages) == 2
        assert all(m["ts"] > 1500.0 for m in messages)


class TestMcpAgentProjectTools:
    """Project-scoped tool tests (board, ready, claim, release, close, comment)."""

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_board_requires_project_tasks_scope(self, mcp_agent_client):
        """Token without project_tasks calling board -> tool error."""
        cid, token = await _make_agent_token(mcp_agent_client._app, scopes=("a2a_receive",))
        async with _bare(mcp_agent_client._app) as bare:
            resp = await bare.post(
                "/api/mcp/agent",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "board", "arguments": {}},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data or "result" in data
        if "result" in data:
            result = data["result"]
            assert result.get("isError") is True

    @pytest.mark.skipif(not _mcp_available(), reason="mcp extra not installed")
    async def test_ready_requires_project_tasks_scope(self, mcp_agent_client):
        """Token without project_tasks calling ready -> tool error."""
        cid, token = await _make_agent_token(mcp_agent_client._app, scopes=("a2a_receive",))
        async with _bare(mcp_agent_client._app) as bare:
            resp = await bare.post(
                "/api/mcp/agent",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "ready", "arguments": {}},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data or "result" in data
        if "result" in data:
            result = data["result"]
            assert result.get("isError") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])