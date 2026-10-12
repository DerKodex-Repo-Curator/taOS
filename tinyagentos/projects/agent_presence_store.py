from __future__ import annotations

import logging
import time

import aiosqlite

from tinyagentos.base_store import BaseStore

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_presence (
    handle      TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    transport   TEXT NOT NULL,
    last_seen_at REAL NOT NULL,
    PRIMARY KEY (handle, project_id)
);
"""

VALID_TRANSPORTS = frozenset({"stream", "poll", "mcp", "rest"})
STAMP_THROTTLE_SECS = 60


class AgentPresenceStore(BaseStore):
    SCHEMA = SCHEMA

    def __init__(self, db_path):
        super().__init__(db_path)
        self._last_write: dict[tuple[str, str], float] = {}

    async def init(self) -> None:
        await super().init()
        if self._db is not None:
            self._db.row_factory = aiosqlite.Row

    def _now(self) -> float:
        return time.time()

    async def stamp(self, handle: str, project_id: str, transport: str) -> None:
        """Record agent presence for (handle, project_id) with the given transport.

        Writes at most once per 60s per (handle, project_id) pair.
        Transport is always updated immediately if it changed.
        Never raises; failures are logged and swallowed.
        """
        if self._db is None:
            return
        if transport not in VALID_TRANSPORTS:
            logger.warning("agent_presence: invalid transport %r for handle=%s project=%s",
                           transport, handle, project_id)
            return

        key = (handle, project_id)
        now = self._now()
        last_write = self._last_write.get(key, 0)

        # Always update transport if it changed, even within throttle window
        transport_changed = False
        try:
            cursor = await self._db.execute(
                "SELECT transport FROM agent_presence WHERE handle = ? AND project_id = ?",
                (handle, project_id),
            )
            row = await cursor.fetchone()
            if row and row["transport"] != transport:
                transport_changed = True
        except Exception:
            pass  # If we can't read, we'll just try the write

        # Throttle: skip write if not enough time passed AND transport didn't change
        if not transport_changed and (now - last_write) < STAMP_THROTTLE_SECS:
            return

        try:
            await self._db.execute(
                """
                INSERT INTO agent_presence (handle, project_id, transport, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(handle, project_id) DO UPDATE SET
                    transport = excluded.transport,
                    last_seen_at = excluded.last_seen_at
                """,
                (handle, project_id, transport, now),
            )
            await self._db.commit()
            self._last_write[key] = now
        except Exception as exc:  # noqa: BLE001 - best effort, never fails the request
            logger.warning("agent_presence: stamp failed for handle=%s project=%s: %s",
                           handle, project_id, exc)

    async def get_presence(self, handle: str, project_id: str) -> dict | None:
        """Return presence dict for a member, or None if no row exists."""
        if self._db is None:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT transport, last_seen_at FROM agent_presence WHERE handle = ? AND project_id = ?",
                (handle, project_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {"transport": row["transport"], "last_seen_at": row["last_seen_at"]}
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.warning("agent_presence: get failed for handle=%s project=%s: %s",
                           handle, project_id, exc)
            return None