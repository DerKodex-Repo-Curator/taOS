"""Persistent store for paired cast devices (Chromecast/AirPlay/RAOP)."""
from __future__ import annotations

from tinyagentos.base_store import BaseStore


class CastDeviceStore(BaseStore):
    """SQLite-backed store for paired cast devices.

    Schema:
      - id: unique device identifier (derived from mDNS instance name)
      - friendly_name: user-visible name (from `fn` property or mDNS name)
      - kind: one of "googlecast", "airplay", "raop"
      - address: IP address (first from parsed_addresses)
      - port: service port
      - last_seen: ISO timestamp of last advertisement or manual update
      - added_by_address: 1 if manually added by IP (no mDNS), 0 if discovered
    """
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS cast_devices (
        id TEXT PRIMARY KEY,
        friendly_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        address TEXT NOT NULL,
        port INTEGER NOT NULL,
        last_seen TEXT NOT NULL,
        added_by_address INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cast_devices_kind ON cast_devices(kind);
    """

    async def upsert(
        self,
        *,
        device_id: str,
        friendly_name: str,
        kind: str,
        address: str,
        port: int,
        last_seen: str,
        added_by_address: int,
    ) -> None:
        """Insert or update a paired device."""
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO cast_devices (id, friendly_name, kind, address, port, last_seen, added_by_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                friendly_name = excluded.friendly_name,
                kind = excluded.kind,
                address = excluded.address,
                port = excluded.port,
                last_seen = excluded.last_seen,
                added_by_address = excluded.added_by_address
            """,
            (device_id, friendly_name, kind, address, port, last_seen, added_by_address),
        )
        await self._db.commit()

    async def remove(self, device_id: str) -> None:
        """Remove a paired device from the registry."""
        assert self._db is not None
        await self._db.execute(
            "DELETE FROM cast_devices WHERE id = ?",
            (device_id,),
        )
        await self._db.commit()

    async def list_all(self) -> list[dict]:
        """Return all paired devices."""
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT id, friendly_name, kind, address, port, last_seen, added_by_address "
            "FROM cast_devices ORDER BY last_seen DESC, id DESC"
        )
        rows = await cur.fetchall()
        return [
            {
                "device_id": row[0],
                "friendly_name": row[1],
                "kind": row[2],
                "address": row[3],
                "port": row[4],
                "last_seen": row[5],
                "added_by_address": row[6],
            }
            for row in rows
        ]

    async def touch_seen(self, device_id: str, when_iso: str) -> None:
        """Update the last_seen timestamp for a paired device."""
        assert self._db is not None
        await self._db.execute(
            "UPDATE cast_devices SET last_seen = ? WHERE id = ?",
            (when_iso, device_id),
        )
        await self._db.commit()