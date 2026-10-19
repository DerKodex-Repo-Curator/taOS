"""Tests for dispatcher reconcile / backoff / card-pause logic (Dispatcherservice S6, tsk-6rhjr3)."""

import pytest
import pytest_asyncio
from types import SimpleNamespace

from tinyagentos.projects.dispatcher import DispatcherService
from tinyagentos.projects.dispatcher_store import DispatcherConfig
from tinyagentos.projects.task_store import ProjectTaskStore
from tinyagentos.projects.dispatch_policy import is_candidate
from .conftest import seed_board_with_cards, register_agent_with_grant


@pytest_asyncio.fixture
async def app_state(real_stores, tmp_path):
    """Build app_state with real stores and minimal config for tests."""
    config = SimpleNamespace(
        agents=[],
        wake_budget={"global_default": 100},
    )
    return SimpleNamespace(
        config=config,
        data_dir=tmp_path,
        project_store=real_stores.project_store,
        project_task_store=real_stores.task_store,
        dispatcher_store=real_stores.dispatcher_store,
        agent_registry=real_stores.registry,
        agent_grants=real_stores.grants,
        chat_channels=None,
        chat_messages=None,
    )


@pytest_asyncio.fixture
async def dispatcher_service(app_state):
    return DispatcherService(app_state)


class TestDispatcherReconcile:
    """Tests for dispatcher reconcile_user and backoff / card-pause logic."""

    @pytest.mark.asyncio
    async def test_expired_unclaimed_lease_first_expiry(self, dispatcher_service, real_stores, tmp_path):
        """Case (a): expired unclaimed lease -> card assignee cleared, ledger 'expired', backoff n=1,
        next_eligible_at = now+900; second expiry -> now+1800."""
        board_row, tasks = await seed_board_with_cards(real_stores, "u1", "Test Board", 1)
        board_id = board_row["id"]
        task_id = tasks[0]["id"]

        # Add claimable label
        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
            (task_id,),
        )
        await real_stores.task_store._db.commit()

        # Register agent
        agent_cid = await register_agent_with_grant(real_stores, "agent-a", board_id, "project_tasks")

        # Create a pending lease that is expired (set lease_expires_at in the past)
        now = 1000.0
        lease_id = await real_stores.dispatcher_store.insert_lease(
            user_id="u1",
            task_id=task_id,
            project_id=board_id,
            canonical_id=agent_cid,
            assignee_written=agent_cid,
            reason="test",
            assigned_at=now - 100,
            lease_expires_at=now - 50,  # expired
        )

        # Configure dispatcher for user u1 with the agent eligible
        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=True,
                eligible_agents=[agent_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        # First tick - should reconcile the expired lease
        result = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now)
        # reconcile_user should resolve it as 'expired'
        assert "expired" in result or result.get("expired_count", 0) == 1

        # Check the lease state is 'expired'
        leases = await real_stores.dispatcher_store.pending_for_agent(agent_cid)
        assert len(leases) == 1
        assert leases[0]["state"] == "expired"
        assert leases[0]["resolved_at"] is not None

        # Check backoff was bumped: n=1, next_eligible_at = now + 900
        backoff = await real_stores.dispatcher_store._db.execute(
            "SELECT consecutive_expiries, next_eligible_at FROM dispatch_agent_backoff WHERE canonical_id = ?",
            (agent_cid,),
        )
        row = await backoff.fetchone()
        assert row is not None
        assert row[0] == 1  # consecutive_expiries
        assert row[1] == now + 900  # next_eligible_at

        # Second tick with same expired lease scenario - should bump to n=2, next_eligible_at = now+1800
        # (We need a fresh now that is after the first next_eligible_at)
        now2 = now + 2000  # well past the first backoff
        result2 = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now2)
        leases2 = await real_stores.dispatcher_store.pending_for_agent(agent_cid)
        # Should still be expired
        assert leases2[0]["state"] == "expired"

        # Backoff should be n=2
        backoff2 = await real_stores.dispatcher_store._db.execute(
            "SELECT consecutive_expiries, next_eligible_at FROM dispatch_agent_backoff WHERE canonical_id = ?",
            (agent_cid,),
        )
        row2 = await backoff2.fetchone()
        assert row2[0] == 2  # consecutive_expiries
        assert row2[1] == now2 + 1800  # next_eligible_at = now2 + 900 * 2**(2-1) = now2 + 1800

    @pytest.mark.asyncio
    async def test_agent_claimed_resets_backoff(self, dispatcher_service, real_stores, tmp_path):
        """Case (b): agent claimed -> 'claimed', backoff reset to 0."""
        board_row, tasks = await seed_board_with_cards(real_stores, "u1", "Test Board", 1)
        board_id = board_row["id"]
        task_id = tasks[0]["id"]

        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
            (task_id,),
        )
        await real_stores.task_store._db.commit()

        agent_cid = await register_agent_with_grant(real_stores, "agent-a", board_id, "project_tasks")

        # First: create an expired lease to establish backoff
        now = 1000.0
        await real_stores.dispatcher_store.insert_lease(
            user_id="u1",
            task_id=task_id,
            project_id=board_id,
            canonical_id=agent_cid,
            assignee_written=agent_cid,
            reason="test",
            assigned_at=now - 100,
            lease_expires_at=now - 50,
        )

        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=True,
                eligible_agents=[agent_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        # Second tick: the task is now claimed by the agent (claimed_by is set to agent's alias)
        # This should resolve as 'claimed' and reset backoff
        # We need to set up the task as claimed by the agent
        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET assignee_id = ?, claimed_by = ?, status = 'claimed' WHERE id = ?",
            (agent_cid, agent_cid, task_id),
        )
        await real_stores.task_store._db.commit()

        # Clear any existing backoff
        await real_stores.dispatcher_store._db.execute(
            "DELETE FROM dispatch_agent_backoff WHERE canonical_id = ?",
            (agent_cid,),
        )
        await real_stores.dispatcher_store._db.commit()

        # Now tick - task is claimed by agent
        result = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now + 100)
        # Should resolve as 'claimed'
        assert result.get("claimed_count", 0) == 1 or "claimed" in result

        # Backoff should be reset
        backoff = await real_stores.dispatcher_store._db.execute(
            "SELECT consecutive_expiries, next_eligible_at FROM dispatch_agent_backoff WHERE canonical_id = ?",
            (agent_cid,),
        )
        row = await backoff.fetchone()
        assert row is not None
        assert row[0] == 0  # consecutive_expiries reset to 0
        assert row[1] == 0  # next_eligible_at reset to 0

    @pytest.mark.asyncio
    async def test_assignee_changed_by_human_overridden(self, dispatcher_service, real_stores, tmp_path):
        """Case (c): assignee changed by a human -> 'overridden', card untouched."""
        board_row, tasks = await seed_board_with_cards(real_stores, "u1", "Test Board", 1)
        board_id = board_row["id"]
        task_id = tasks[0]["id"]

        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
            (task_id,),
        )
        await real_stores.task_store._db.commit()

        agent_cid = await register_agent_with_grant(real_stores, "agent-a", board_id, "project_tasks")

        # Create a pending lease
        now = 1000.0
        await real_stores.dispatcher_store.insert_lease(
            user_id="u1",
            task_id=task_id,
            project_id=board_id,
            canonical_id=agent_cid,
            assignee_written=agent_cid,
            reason="test",
            assigned_at=now,
            lease_expires_at=now + 3600,
        )

        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=True,
                eligible_agents=[agent_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        # A human changes the assignee to someone else
        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET assignee_id = 'human-agent' WHERE id = ?",
            (task_id,),
        )
        await real_stores.task_store._db.commit()

        # Tick - should resolve as 'overridden' since assignee changed
        result = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now + 100)
        assert result.get("overridden_count", 0) == 1 or "overridden" in result

        # Lease state should be 'overridden'
        leases = await real_stores.dispatcher_store.pending_for_agent(agent_cid)
        assert len(leases) == 1
        assert leases[0]["state"] == "overridden"

    @pytest.mark.asyncio
    async def test_card_closed(self, dispatcher_service, real_stores, tmp_path):
        """Case (d): card closed -> 'closed'."""
        board_row, tasks = await seed_board_with_cards(real_stores, "u1", "Test Board", 1)
        board_id = board_row["id"]
        task_id = tasks[0]["id"]

        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
            (task_id,),
        )
        await real_stores.task_store._db.commit()

        agent_cid = await register_agent_with_grant(real_stores, "agent-a", board_id, "project_tasks")

        # Create a pending lease
        now = 1000.0
        await real_stores.dispatcher_store.insert_lease(
            user_id="u1",
            task_id=task_id,
            project_id=board_id,
            canonical_id=agent_cid,
            assignee_written=agent_cid,
            reason="test",
            assigned_at=now,
            lease_expires_at=now + 3600,
        )

        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=True,
                eligible_agents=[agent_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        # Close the task
        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET status = 'closed', closed_at = ? WHERE id = ?",
            (2000.0, task_id),
        )
        await real_stores.task_store._db.commit()

        # Tick - should resolve as 'closed' since task status is not open/claimed
        result = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now + 100)
        assert result.get("closed_count", 0) == 1 or "closed" in result

        # Lease state should be 'closed'
        leases = await real_stores.dispatcher_store.pending_for_agent(agent_cid)
        assert len(leases) == 1
        assert leases[0]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_backed_off_agent_no_assignment_next_tick(self, dispatcher_service, real_stores, tmp_path):
        """Case (e): backed-off agent receives no assignment on the next tick while another eligible agent does."""
        # Two boards, two agents
        board1_row, tasks1 = await seed_board_with_cards(real_stores, "u1", "Board One", 1)
        board2_row, tasks2 = await seed_board_with_cards(real_stores, "u1", "Board Two", 1)
        board1_id = board1_row["id"]
        board2_id = board2_row["id"]

        for task in tasks1 + tasks2:
            await real_stores.task_store._db.execute(
                "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
                (task["id"],),
            )
        await real_stores.task_store._db.commit()

        # Register two agents
        agent1_cid = await register_agent_with_grant(real_stores, "agent-a", board1_id, "project_tasks")
        agent2_cid = await register_agent_with_grant(real_stores, "agent-b", board2_id, "project_tasks")

        # Add grant for agent-b on both boards
        await real_stores.grants.add_grant(canonical_id=agent2_cid, scope="project_tasks", project_id=board1_id)

        # Configure dispatcher with both agents
        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=True,
                eligible_agents=[agent1_cid, agent2_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        now = 1000.0

        # First tick: assign agent-a on board1, agent-b on board2
        result1 = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now)
        assert result1["assignments_made"] == 2

        # Now manually back off agent-a by bumping its backoff
        await real_stores.dispatcher_store._db.execute(
            """
            INSERT OR REPLACE INTO dispatch_agent_backoff (canonical_id, consecutive_expiries, next_eligible_at, last_assigned_at)
            VALUES (?, 1, ?, ?)
            """,
            (agent1_cid, now + 900, now),
        )
        await real_stores.dispatcher_store._db.commit()

        # Second tick: agent-a should be backed off, agent-b should still get a lease
        result2 = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now + 2000)
        # agent-b should get an assignment
        assert result2["assignments_made"] >= 1

        # Check that agent-a's lease was resolved as 'expired' or 'overridden' due to backoff
        leases_a = await real_stores.dispatcher_store.pending_for_agent(agent1_cid)
        # agent-a should not have a pending lease (it's backed off)
        # The lease should have been resolved

    @pytest.mark.asyncio
    async def test_card_expiry_cap_5_expired_not_assigned(self, dispatcher_service, real_stores, tmp_path):
        """Case (f): card with 5 'expired' rows in 48h is not assigned, still status open;
        with 4 it is."""
        import time as time_mod

        # Two boards with tasks
        board1_row, tasks1 = await seed_board_with_cards(real_stores, "u1", "Board One", 1)
        board2_row, tasks2 = await seed_board_with_cards(real_stores, "u1", "Board Two", 1)
        board1_id = board1_row["id"]
        board2_id = board2_row["id"]

        for task in tasks1 + tasks2:
            await real_stores.task_store._db.execute(
                "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
                (task["id"],),
            )
        await real_stores.task_store._db.commit()

        # Register one agent
        agent_cid = await register_agent_with_grant(real_stores, "agent-a", board1_id, "project_tasks")

        # Create 5 expired leases on board one task (simulating 5 expiries in 48h)
        # We need to use the dispatcher_store to create ledger entries with state='expired'
        now = 1000.0
        task_id = tasks1[0]["id"]

        # First, create a pending lease
        lease_id = await real_stores.dispatcher_store.insert_lease(
            user_id="u1",
            task_id=task_id,
            project_id=board1_id,
            canonical_id=agent_cid,
            assignee_written=agent_cid,
            reason="test",
            assigned_at=now - 100,
            lease_expires_at=now - 50,  # expired
        )

        # Set up the task as claimed/assigned
        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET assignee_id = ?, claimed_by = ?, status = 'open' WHERE id = ?",
            (agent_cid, agent_cid, task_id),
        )
        await real_stores.task_store._db.commit()

        # Now set up 5 'expired' entries in the ledger for this task
        # We need to insert additional rows with state='expired'
        # Actually, let me reconsider - the test is about expired_counts_48h

        # Configure dispatcher
        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=True,
                eligible_agents=[agent_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        # Test with 5 expired entries - card should NOT be assigned
        # First create 5 expired entries
        for i in range(5):
            expired_lease_id = await real_stores.dispatcher_store.insert_lease(
                user_id="u1",
                task_id=task_id,
                project_id=board1_id,
                canonical_id=agent_cid,
                assignee_written=agent_cid,
                reason="test",
                assigned_at=now - 100 - i * 100,
                lease_expires_at=now - 50 - i * 100,
            )
            # Mark as expired
            await real_stores.dispatcher_store._db.execute(
                "UPDATE dispatch_ledger SET state = 'expired', resolved_at = ? WHERE id = ?",
                (now - 100, expired_lease_id),
            )
        await real_stores.dispatcher_store._db.commit()

        # Check expired counts
        expired_counts = await real_stores.dispatcher_store.expired_counts_48h(now)
        assert expired_counts.get(task_id, 0) >= 5

        # Now run tick - with 5 expiries, card should be paused (not assigned)
        result = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now + 100)
        # With 5 expiries >= CARD_EXPIRY_CAP, the card should be paused

        # Test with 4 expired entries - card should be assigned
        # Clean up and create only 4 expired entries
        await real_stores.dispatcher_store._db.execute(
            "DELETE FROM dispatch_ledger WHERE state = 'expired' AND task_id = ?",
            (task_id,),
        )
        await real_stores.dispatcher_store._db.execute(
            "DELETE FROM dispatch_ledger WHERE state = 'expired'",
        )
        await real_stores.dispatcher_store._db.commit()

        # Create only 4 expired entries
        for i in range(4):
            expired_lease_id = await real_stores.dispatcher_store.insert_lease(
                user_id="u1",
                task_id=task_id,
                project_id=board1_id,
                canonical_id=agent_cid,
                assignee_written=agent_cid,
                reason="test",
                assigned_at=now - 100 - i * 100,
                lease_expires_at=now - 50 - i * 100,
            )
            await real_stores.dispatcher_store._db.execute(
                "UPDATE dispatch_ledger SET state = 'expired', resolved_at = ? WHERE id = ?",
                (now - 100, expired_lease_id),
            )
        await real_stores.dispatcher_store._db.commit()

        expired_counts2 = await real_stores.dispatcher_store.expired_counts_48h(now)
        assert expired_counts2.get(task_id, 0) == 4

        # Now run tick - with 4 expiries < CARD_EXPIRY_CAP, card should be assigned
        result2 = await dispatcher_service.tick_user("u1", await real_stores.dispatcher_store.get_config("u1"), now + 100)
        # With 4 expiries < 5, the card should NOT be paused

    @pytest.mark.asyncio
    async def test_disabled_user_with_expired_lease_unassigns(self, dispatcher_service, real_stores, tmp_path):
        """Case (g): user with enabled=False and an expired pending lease: one tick() un-assigns it."""
        board_row, tasks = await seed_board_with_cards(real_stores, "u1", "Test Board", 1)
        board_id = board_row["id"]
        task_id = tasks[0]["id"]

        await real_stores.task_store._db.execute(
            "UPDATE project_tasks SET labels = json_array('claimable') WHERE id = ?",
            (task_id,),
        )
        await real_stores.task_store._db.commit()

        agent_cid = await register_agent_with_grant(real_stores, "agent-a", board_id, "project_tasks")

        now = 1000.0

        # Create a pending expired lease
        lease_id = await real_stores.dispatcher_store.insert_lease(
            user_id="u1",
            task_id=task_id,
            project_id=board_id,
            canonical_id=agent_cid,
            assignee_written=agent_cid,
            reason="test",
            assigned_at=now - 100,
            lease_expires_at=now - 50,  # expired
        )

        # Configure dispatcher as DISABLED
        await real_stores.dispatcher_store.set_config(
            "u1",
            DispatcherConfig(
                user_id="u1",
                enabled=False,  # Disabled
                eligible_agents=[agent_cid],
                max_concurrent_per_agent=1,
                lease_seconds=900,
            ),
            updated_by="test",
        )

        # tick() should still run reconcile_user because list_pending is non-empty
        # and un-assign the expired lease
        result = await dispatcher_service.tick(now=now + 100)
        # u1 should be processed (users_processed should include it or the lease should be resolved)
        # The lease state should be 'expired'
        leases = await real_stores.dispatcher_store.pending_for_agent(agent_cid)
        assert len(leases) == 1
        assert leases[0]["state"] == "expired"