"""Self-only chat session routes for registry agents (tsk-lwkv4t).

A registry agent holding the ``chat_session`` grant drains its own chat events
and posts replies through /api/agents/self/chat/*. The slug is derived from the
token only; a body-supplied identity must never select another agent's session.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.agent_registry_store import mint_registry_token
from tinyagentos.bridge_session import BridgeSessionRegistry
from taos_test_csrf import csrf_event_hooks

EVENTS = "/api/agents/self/chat/events"
REPLY = "/api/agents/self/chat/reply"


@pytest_asyncio.fixture
async def chat_app(app, tmp_data_dir):
    for attr in ("agent_registry", "agent_grants", "metrics"):
        store = getattr(app.state, attr)
        if store._db is None:
            await store.init()
    # Initialize chat_channels and chat_messages for the tests
    chat_channels = app.state.chat_channels
    if chat_channels._db is None:
        await chat_channels.init()
    chat_messages = app.state.chat_messages
    if chat_messages._db is None:
        await chat_messages.init()
    app.state.bridge_sessions = BridgeSessionRegistry(
        trace_registry=None,
        chat_messages=chat_messages,
        chat_channels=chat_channels,
        chat_hub=None,
        archive=None,
    )
    app.state._startup_complete = True
    yield app
    for attr in ("agent_registry", "agent_grants", "metrics"):
        store = getattr(app.state, attr)
        if store._db is not None:
            await store.close()


async def _agent(app, handle, *, scopes=("chat_session",), display_name=None):
    registry = app.state.agent_registry
    priv, _pub = app.state.agent_registry_keypair
    rec = await registry.register(
        framework="taosmd",
        display_name=display_name or handle,
        origin="taos-deployed",
        handle=handle,
    )
    cid = rec["canonical_id"]
    for scope in scopes:
        await app.state.agent_grants.add_grant(cid, scope)
    return cid, mint_registry_token(cid, priv, user_id="u", framework="taosmd")


def _bare(app):
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        event_hooks=csrf_event_hooks(),
    )


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
class TestChatSessionAuth:
    async def test_no_bearer_is_refused_events(self, chat_app):
        async with _bare(chat_app) as c:
            r = await c.get(EVENTS)
        assert r.status_code in (401, 403)
        assert "text/event-stream" not in r.headers.get("content-type", "")

    async def test_no_bearer_is_refused_reply(self, chat_app):
        chat_app.state.bridge_sessions.record_reply = AsyncMock()
        async with _bare(chat_app) as c:
            r = await c.post(REPLY, json={"kind": "final", "content": "x"})
        assert r.status_code in (401, 403)
        chat_app.state.bridge_sessions.record_reply.assert_not_called()

    async def test_jwt_without_grant_gets_403(self, chat_app):
        _cid, token = await _agent(chat_app, "@no-grant", scopes=("a2a_receive",))
        chat_app.state.bridge_sessions.record_reply = AsyncMock()
        async with _bare(chat_app) as c:
            r1 = await c.get(EVENTS, headers=_hdr(token))
            r2 = await c.post(REPLY, headers=_hdr(token), json={"kind": "final"})
        assert r1.status_code == 403
        assert r2.status_code == 403
        chat_app.state.bridge_sessions.record_reply.assert_not_called()

    async def test_handle_colliding_with_local_agent_gets_403(self, chat_app):
        chat_app.state.config.agents.append({"name": "alice"})
        try:
            _cid, token = await _agent(chat_app, "@alice")
            chat_app.state.bridge_sessions.record_reply = AsyncMock()

            async def finite(slug):
                yield "event: tick\ndata: {}\n\n"

            chat_app.state.bridge_sessions.subscribe = finite
            async with _bare(chat_app) as c:
                r1 = await c.get(EVENTS, headers=_hdr(token))
                r2 = await c.post(REPLY, headers=_hdr(token), json={"kind": "final"})
        finally:
            chat_app.state.config.agents[:] = [
                a for a in chat_app.state.config.agents if a.get("name") != "alice"
            ]
        assert r1.status_code == 403
        assert r2.status_code == 403
        assert r1.json() == {"error": "handle collides with a local agent"}
        chat_app.state.bridge_sessions.record_reply.assert_not_called()

    async def test_bridge_unavailable_is_503(self, chat_app):
        _cid, token = await _agent(chat_app, "@bridge-down")
        chat_app.state.bridge_sessions = None
        async with _bare(chat_app) as c:
            r1 = await c.get(EVENTS, headers=_hdr(token))
            r2 = await c.post(REPLY, headers=_hdr(token), json={"kind": "final"})
        assert r1.status_code == 503 and r1.json() == {"error": "bridge unavailable"}
        assert r2.status_code == 503


@pytest.mark.asyncio
class TestChatSessionEvents:
    async def test_events_stream_yields_enqueued_message_for_own_slug(self, chat_app):
        _cid, token = await _agent(chat_app, "@guest-a")
        registry = chat_app.state.bridge_sessions
        real_subscribe = registry.subscribe
        subscribed = []

        async def one_frame(slug):
            subscribed.append(slug)
            async for frame in real_subscribe(slug):
                yield frame
                return

        registry.subscribe = one_frame
        await registry.enqueue_user_message("guest-a", {"id": "m1", "text": "hello"})
        await registry.enqueue_user_message("guest-b", {"id": "m2", "text": "other"})
        async with _bare(chat_app) as c:
            r = await c.get(EVENTS, headers=_hdr(token))
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert subscribed == ["guest-a"]
        assert "event: user_message" in r.text
        assert "hello" in r.text
        assert "other" not in r.text

    async def test_session_slug_follows_canonical_id_not_handle(self, chat_app):
        # The router delivers to the canonical_id slug (display-name based), so a
        # handle that differs from the display name must not move the session.
        _cid, token = await _agent(
            chat_app, "@other-handle", display_name="Guest Display"
        )
        registry = chat_app.state.bridge_sessions
        real_subscribe = registry.subscribe
        subscribed = []

        async def one_frame(slug):
            subscribed.append(slug)
            async for frame in real_subscribe(slug):
                yield frame
                return

        registry.subscribe = one_frame
        await registry.enqueue_user_message("guest-display", {"id": "m1", "text": "hi"})
        async with _bare(chat_app) as c:
            r = await c.get(EVENTS, headers=_hdr(token))
        assert r.status_code == 200
        assert subscribed == ["guest-display"]
        assert "hi" in r.text


@pytest.mark.asyncio
class TestChatSessionReply:
    async def test_reply_records_under_own_slug(self, chat_app):
        _cid, token = await _agent(chat_app, "@guest-a")
        chat_app.state.bridge_sessions.record_reply = AsyncMock()
        async with _bare(chat_app) as c:
            r = await c.post(REPLY, headers=_hdr(token), json={"kind": "final", "content": "hi"})
        assert r.status_code == 202
        chat_app.state.bridge_sessions.record_reply.assert_awaited_once_with(
            "guest-a", {"kind": "final", "content": "hi"}
        )

    async def test_body_identity_is_ignored(self, chat_app):
        _a, token_a = await _agent(chat_app, "@guest-a")
        await _agent(chat_app, "@guest-b")
        mock = AsyncMock()
        chat_app.state.bridge_sessions.record_reply = mock
        body = {
            "kind": "final",
            "content": "spoof",
            "agent": "guest-b",
            "slug": "guest-b",
            "from": "@guest-b",
            "author": "guest-b",
        }
        async with _bare(chat_app) as c:
            r = await c.post(REPLY, headers=_hdr(token_a), json=body)
        assert r.status_code == 202
        slugs = [call.args[0] for call in mock.await_args_list]
        assert slugs == ["guest-a"]
        assert "guest-b" not in slugs

    async def test_reply_with_foreign_channel_id_gets_403(self, chat_app):
        _cid, token = await _agent(chat_app, "@guest-a")
        # Create a foreign channel
        chat_channels = chat_app.state.chat_channels
        foreign = await chat_channels.create_channel(
            name="foreign",
            type="group",
            created_by="user",
            members=["other"],  # guest-a is NOT a member
        )
        # Try to reply with that channel_id
        mock = AsyncMock()
        chat_app.state.bridge_sessions.record_reply = mock
        body = {"kind": "final", "content": "x", "channel_id": foreign["id"]}
        async with _bare(chat_app) as c:
            r = await c.post(REPLY, headers=_hdr(token), json=body)
        assert r.status_code == 403
        assert r.json() == {"error": "not a member of this channel"}
        mock.assert_not_called()

    async def test_reply_with_trace_id_of_foreign_channel_gets_403(
        self, chat_app
    ):
        _cid, token = await _agent(chat_app, "@guest-a")
        # Create a foreign channel with a message
        chat_channels = chat_app.state.chat_channels
        chat_messages = chat_app.state.chat_messages
        foreign = await chat_channels.create_channel(
            name="foreign",
            type="group",
            created_by="user",
            members=["other"],  # guest-a is NOT a member
        )
        msg = await chat_messages.send_message(
            channel_id=foreign["id"],
            author_id="user",
            author_type="user",
            content="hello",
            state="complete",
        )
        # Try to reply using trace_id of that message
        mock = AsyncMock()
        chat_app.state.bridge_sessions.record_reply = mock
        body = {"kind": "final", "content": "x", "trace_id": msg["id"]}
        async with _bare(chat_app) as c:
            r = await c.post(REPLY, headers=_hdr(token), json=body)
        assert r.status_code == 403
        assert r.json() == {"error": "not a member of this channel"}
        mock.assert_not_called()

    async def test_reply_into_own_dm_works(self, chat_app):
        # agent is already member of its own DM (created by _resolve_slug flow)
        _cid, token = await _agent(chat_app, "@guest-a")
        mock = AsyncMock()
        chat_app.state.bridge_sessions.record_reply = mock
        async with _bare(chat_app) as c:
            r = await c.post(REPLY, headers=_hdr(token), json={"kind": "final", "content": "x"})
        assert r.status_code == 202
        mock.assert_awaited_once()

    async def test_colliding_slug_with_other_registry_agent_gets_403(self, chat_app):
        # First agent
        _cid1, token1 = await _agent(chat_app, "@alice")
        
        # We need to test the slug collision check, but we can't create a second agent
        # with the same handle due to the UNIQUE constraint. Instead, we'll
        # mock the registry.list_all() method BEFORE creating the agent
        # and return a list with a second agent that has the same slug
        registry = chat_app.state.agent_registry
        
        # Store the original list_all method
        original_list_all = registry.list_all
        
        # Create a mock registry list that includes two agents with the same slug
        async def mock_list_all(*, status=None):
            if status == "active":
                # Return a mock list with two agents having the same slug
                # The first agent's slug (from _cid1) will be calculated
                from tinyagentos.chat.orphan_reconcile import _CANONICAL_AGENT_ID_RE
                slug1 = _CANONICAL_AGENT_ID_RE.sub("", _cid1)
                # Create a second agent with the same slug
                mock_second = {
                    "canonical_id": f"{slug1}-20250101-120000",  # Same slug pattern
                    "handle": "@bob",  # Different handle
                    "display_name": "Bob",  # Different display name
                    "framework": "taosmd",
                    "user_id": "",
                    "origin": "taos-deployed",
                    "role": None,
                    "capabilities": "[]",
                    "created_ts": "2025-01-01T12:00:00Z",
                    "revoked_at": None,
                    "status": "active",
                }
                # We need to return the actual first agent too
                # Let's get it by calling the original list_all and filtering
                original_list = await original_list_all(status="active")
                for agent in original_list:
                    if agent["canonical_id"] == _cid1:
                        return [agent, mock_second]
                return [mock_second]
            return await original_list_all(status=status)
        
        # Replace the list_all method with our mock
        registry.list_all = mock_list_all
        
        try:
            # Now try to use token1 (should fail because we detected the collision)
            async with _bare(chat_app) as c:
                r1 = await c.get(EVENTS, headers=_hdr(token1))
                # Should return 403 because our mock detected the slug collision
                assert r1.status_code == 403
                assert r1.json() == {"error": "handle collides with another registry agent"}
        finally:
            # Restore the original list_all method
            registry.list_all = original_list_all


def test_chat_session_scope_registered_in_both_sets():
    from tinyagentos.routes.agent_auth_requests import VALID_SCOPES
    from tinyagentos.routes.agent_registry import _ALLOWED_SCOPES

    assert "chat_session" in VALID_SCOPES
    assert "chat_session" in _ALLOWED_SCOPES
