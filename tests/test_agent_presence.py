"""Tests for agent presence stamping (S2)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tinyagentos.agent_registry_store import mint_registry_token
from tinyagentos.projects.agent_presence_store import AgentPresenceStore


async def _mint_agent(app, *, scopes=("a2a_receive",), project_id="prj-1"):
    """Register an active agent with *scopes*, return (canonical_id, jwt)."""
    registry = app.state.agent_registry
    grants = app.state.agent_grants
    priv, _pub = app.state.agent_registry_keypair

    rec = await registry.register(
        framework="grok",
        display_name="Grok",
        origin="external-selfjoin",
        handle="@grok",
    )
    cid = rec["canonical_id"]
    await registry.set_status(cid, "active")
    for scope in scopes:
        await grants.add_grant(cid, scope, project_id=project_id)
    token = mint_registry_token(
        cid, priv, user_id="u", framework="grok", project_id=project_id
    )
    return cid, token


@pytest_asyncio.fixture
async def agent_app(app):
    for attr in ("agent_registry", "agent_grants"):
        store = getattr(app.state, attr)
        if store._db is None:  # noqa: SLF001
            await store.init()
    yield app
    for attr in ("agent_registry", "agent_grants"):
        store = getattr(app.state, attr)
        if store._db is not None:
            await store.close()


@pytest_asyncio.fixture
async def presence_store(tmp_path):
    s = AgentPresenceStore(tmp_path / "agent_presence.db")
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestAgentPresenceStore:
    async def test_stamp_creates_row_with_transport(self, presence_store):
        """A stamp call writes a row with the given transport."""
        handle = "grok"
        project_id = "prj-1"
        transport = "poll"

        await presence_store.stamp(handle, project_id, transport)

        rows = await presence_store._db.execute(
            "SELECT * FROM agent_presence WHERE handle = ? AND project_id = ?",
            (handle, project_id),
        )
        row = await rows.fetchone()
        assert row is not None
        assert row["handle"] == handle
        assert row["project_id"] == project_id
        assert row["transport"] == transport
        assert row["last_seen_at"] > 0

    async def test_stamp_updates_transport_immediately(self, presence_store):
        """Transport is updated immediately even within the 60s window."""
        handle = "grok"
        project_id = "prj-1"

        await presence_store.stamp(handle, project_id, "stream")
        await presence_store.stamp(handle, project_id, "poll")

        rows = await presence_store._db.execute(
            "SELECT transport FROM agent_presence WHERE handle = ? AND project_id = ?",
            (handle, project_id),
        )
        row = await rows.fetchone()
        assert row["transport"] == "poll"

    async def test_stamp_throttles_writes_to_once_per_60s(self, presence_store):
        """Two stamp calls within 60s result in only one DB write (last_seen_at updated once)."""
        handle = "grok"
        project_id = "prj-1"

        # First call
        await presence_store.stamp(handle, project_id, "stream")
        first_rows = await presence_store._db.execute(
            "SELECT last_seen_at FROM agent_presence WHERE handle = ? AND project_id = ?",
            (handle, project_id),
        )
        first_row = await first_rows.fetchone()
        first_ts = first_row["last_seen_at"]

        # Second call immediately after (same second)
        await presence_store.stamp(handle, project_id, "stream")
        second_rows = await presence_store._db.execute(
            "SELECT last_seen_at FROM agent_presence WHERE handle = ? AND project_id = ?",
            (handle, project_id),
        )
        second_row = await second_rows.fetchone()
        second_ts = second_row["last_seen_at"]

        # last_seen_at should NOT have changed (same write)
        assert second_ts == first_ts

    async def test_stamp_writes_again_after_60s(self, presence_store):
        """After 60s, a new stamp call writes again (last_seen_at updated)."""
        handle = "grok"
        project_id = "prj-1"

        await presence_store.stamp(handle, project_id, "stream")
        first_rows = await presence_store._db.execute(
            "SELECT last_seen_at FROM agent_presence WHERE handle = ? AND project_id = ?",
            (handle, project_id),
        )
        first_row = await first_rows.fetchone()
        first_ts = first_row["last_seen_at"]

        # Manually expire the in-memory cache by manipulating the map
        key = (handle, project_id)
        presence_store._last_write[key] = first_ts - 61

        await presence_store.stamp(handle, project_id, "stream")
        second_rows = await presence_store._db.execute(
            "SELECT last_seen_at FROM agent_presence WHERE handle = ? AND project_id = ?",
            (handle, project_id),
        )
        second_row = await second_rows.fetchone()
        second_ts = second_row["last_seen_at"]

        # last_seen_at should have changed (new write)
        assert second_ts > first_ts

    async def test_stamp_failure_does_not_raise(self, presence_store):
        """A stamp failure (e.g. DB locked) is logged but does not raise."""
        # Patch execute to raise an exception to exercise the swallow path
        original_execute = presence_store._db.execute

        async def failing_execute(*args, **kwargs):
            raise RuntimeError("simulated DB failure")

        with patch.object(presence_store._db, "execute", side_effect=failing_execute):
            # Should not raise
            await presence_store.stamp("grok", "prj-1", "poll")


@pytest.mark.asyncio
class TestAgentPresenceViaRoutes:
    async def test_bus_messages_agent_jwt_creates_presence_poll(self, agent_app, client):
        """GET /api/a2a/bus/messages with agent JWT creates presence with transport=poll."""
        cid, token = await _mint_agent(agent_app, scopes=("a2a_receive",))

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"messages": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "tinyagentos.routes.a2a_bus.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            resp = await client.get(
                "/api/a2a/bus/messages",
                params={"channel": "general"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

        # Check presence was recorded (handle includes @ prefix from registry)
        presence_store = agent_app.state.agent_presence
        rows = await presence_store._db.execute(
            "SELECT transport FROM agent_presence WHERE handle = ? AND project_id = ?",
            ("@grok", "prj-1"),
        )
        row = await rows.fetchone()
        assert row is not None
        assert row["transport"] == "poll"

    async def test_bus_stream_agent_jwt_creates_presence_stream(self, agent_app, client):
        """GET /api/a2a/bus/stream with agent JWT creates presence with transport=stream."""
        cid, token = await _mint_agent(agent_app, scopes=("a2a_receive",))

        mock_resp = MagicMock()
        mock_resp.aiter_lines = MagicMock(return_value=iter([]))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        client_ctx = AsyncMock()
        client_ctx.stream = MagicMock(return_value=mock_ctx)
        client_ctx.__aenter__ = AsyncMock(return_value=client_ctx)
        client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "tinyagentos.routes.a2a_bus.httpx.AsyncClient",
            return_value=client_ctx,
        ):
            resp = await client.get(
                "/api/a2a/bus/stream",
                params={"channel": "general"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

        presence_store = agent_app.state.agent_presence
        rows = await presence_store._db.execute(
            "SELECT transport FROM agent_presence WHERE handle = ? AND project_id = ?",
            ("@grok", "prj-1"),
        )
        row = await rows.fetchone()
        assert row is not None
        assert row["transport"] == "stream"

    async def test_bus_send_agent_jwt_creates_presence_rest(self, agent_app, client):
        """POST /api/a2a/bus/send with agent JWT creates presence with transport=rest."""
        cid, token = await _mint_agent(agent_app, scopes=("a2a_send",))

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "m1", "from": "grok", "thread": "general"}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "tinyagentos.routes.a2a_bus.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            resp = await client.post(
                "/api/a2a/bus/send",
                json={"thread": "general", "body": "hi"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200

        presence_store = agent_app.state.agent_presence
        rows = await presence_store._db.execute(
            "SELECT transport FROM agent_presence WHERE handle = ? AND project_id = ?",
            ("@grok", "prj-1"),
        )
        row = await rows.fetchone()
        assert row is not None
        assert row["transport"] == "rest"

    async def test_task_route_agent_jwt_creates_presence_rest(self, agent_app, client):
        """Project task route with agent JWT creates presence with transport=rest."""
        # Create project first via admin
        project_store = agent_app.state.project_store
        project = await project_store.create_project(
            name="Test", slug="test", created_by="admin", user_id="admin"
        )
        pid = project["id"]

        # Register agent with project_tasks scope for THIS project
        cid, token = await _mint_agent(
            agent_app, scopes=("project_tasks", "project_tasks_create"), project_id=pid
        )

        # Add agent as member (using canonical_id as member_id)
        await project_store.add_member(pid, cid, member_kind="native")

        # Now call task route with agent JWT
        resp = await client.get(
            f"/api/projects/{pid}/tasks",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200

        presence_store = agent_app.state.agent_presence
        rows = await presence_store._db.execute(
            "SELECT transport FROM agent_presence WHERE handle = ? AND project_id = ?",
            ("@grok", pid),
        )
        row = await rows.fetchone()
        assert row is not None
        assert row["transport"] == "rest"

    async def test_admin_session_does_not_create_presence(self, agent_app, client):
        """Admin session (cookie auth) does not create a presence row."""
        # Call with admin session (no agent JWT)
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"messages": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "tinyagentos.routes.a2a_bus.httpx.AsyncClient",
            return_value=mock_ctx,
        ):
            resp = await client.get(
                "/api/a2a/bus/messages",
                params={"channel": "general"},
            )

        assert resp.status_code == 200

        presence_store = agent_app.state.agent_presence
        rows = await presence_store._db.execute("SELECT * FROM agent_presence")
        all_rows = await rows.fetchall()
        assert len(all_rows) == 0

    async def test_members_api_carries_presence(self, agent_app, client):
        """GET /api/projects/{pid}/members returns presence per member."""
        # Create project via admin
        project_store = agent_app.state.project_store
        project = await project_store.create_project(
            name="Test", slug="test-presence", created_by="admin", user_id="admin"
        )
        pid = project["id"]

        # Register agent and add as member
        cid, token = await _mint_agent(agent_app, scopes=("a2a_receive",), project_id=pid)
        await project_store.add_member(pid, cid, member_kind="native")

        # Stamp presence for the agent (using handle from registry: @grok)
        presence_store = agent_app.state.agent_presence
        await presence_store.stamp("@grok", pid, "poll")

        # Fetch members
        resp = await client.get(f"/api/projects/{pid}/members")
        assert resp.status_code == 200
        data = resp.json()
        members = data.get("items", [])

        # Find our agent member
        agent_member = next((m for m in members if m["member_id"] == cid), None)
        assert agent_member is not None
        assert "presence" in agent_member
        assert agent_member["presence"] is not None
        assert agent_member["presence"]["transport"] == "poll"
        assert agent_member["presence"]["last_seen_at"] > 0

    async def test_members_api_presence_null_when_no_stamp(self, agent_app, client):
        """Member with no presence stamp has presence=null."""
        project_store = agent_app.state.project_store
        project = await project_store.create_project(
            name="Test", slug="test-null", created_by="admin", user_id="admin"
        )
        pid = project["id"]

        # Add a human member (no agent JWT)
        await project_store.add_member(pid, "hub:human1", member_kind="human")

        resp = await client.get(f"/api/projects/{pid}/members")
        assert resp.status_code == 200
        data = resp.json()
        members = data.get("items", [])

        human_member = next((m for m in members if m["member_id"] == "hub:human1"), None)
        assert human_member is not None
        assert "presence" in human_member
        assert human_member["presence"] is None


# Integration test with write counter to verify throttle
@pytest.mark.asyncio
class TestAgentPresenceThrottleIntegration:
    async def test_two_calls_within_60s_write_once_via_write_counter(self, agent_app, client):
        """Two bus/messages calls within 60s should only write once (verify via write counter)."""
        cid, token = await _mint_agent(agent_app, scopes=("a2a_receive",))

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"messages": []}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        write_count = 0

        presence_store = agent_app.state.agent_presence
        original_execute = presence_store._db.execute

        async def counting_execute(*args, **kwargs):
            nonlocal write_count
            sql = args[0]
            if sql.strip().upper().startswith("INSERT") or sql.strip().upper().startswith("UPDATE"):
                write_count += 1
            return await original_execute(*args, **kwargs)

        with patch.object(presence_store._db, "execute", side_effect=counting_execute):
            with patch(
                "tinyagentos.routes.a2a_bus.httpx.AsyncClient",
                return_value=mock_ctx,
            ):
                # First call
                await client.get(
                    "/api/a2a/bus/messages",
                    params={"channel": "general"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                # Second call immediately
                await client.get(
                    "/api/a2a/bus/messages",
                    params={"channel": "general"},
                    headers={"Authorization": f"Bearer {token}"},
                )

        # Should have only written once (the INSERT), not twice
        # Note: depending on implementation, it might be INSERT then no-op UPDATE
        # The key assertion is that last_seen_at was not updated twice
        rows = await presence_store._db.execute(
            "SELECT last_seen_at FROM agent_presence WHERE handle = ? AND project_id = ?",
            ("@grok", "prj-1"),
        )
        row = await rows.fetchone()
        assert row is not None
        # Two calls within 60s should result in exactly one DB write (INSERT)
        assert write_count == 1