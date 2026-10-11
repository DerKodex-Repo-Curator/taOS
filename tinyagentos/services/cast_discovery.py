"""Chromecast/AirPlay device discovery and paired device registry for screencast.

Uses the existing zeroconf.AsyncZeroconf instance from MdnsPublisher to avoid
competing Zeroconf instances. Persists paired devices (id, friendly name, kind,
address, last-seen) separately from discovery results.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

from tinyagentos.cast_device_store import CastDeviceStore
from tinyagentos.services.mdns_publisher import MdnsPublisher

logger = logging.getLogger(__name__)

SERVICE_TYPES = {
    "googlecast": "_googlecast._tcp.local.",
    "airplay": "_airplay._tcp.local.",
    "raop": "_raop._tcp.local.",
}


class CastDiscovery:
    """Manages discovery and registry of paired Chromecast/AirPlay devices.

    The core discovery loop runs inside MdnsPublisher's existing AsyncZeroconf
    instance. A lightweight wrapper provides the API to browse for cast services
    and maintain the paired device registry.
    """

    def __init__(self, publisher: MdnsPublisher, store: CastDeviceStore) -> None:
        self._publisher = publisher
        self._store = store
        self._browser: AsyncServiceBrowser | None = None
        # Runtime-only discovered-but-unpaired devices
        self._discovered: dict[str, dict] = {}
        # Runtime online flags for paired devices (keyed by device_id)
        self._paired_online: dict[str, bool] = {}

    @property
    def _zc(self) -> AsyncZeroconf | None:
        return self._publisher.async_zeroconf

    async def start(self) -> None:
        """Start browsing for all cast service types using the existing AsyncZeroconf."""
        azc = self._zc
        if azc is None:
            logger.warning("cast discovery: AsyncZeroconf not available in MdnsPublisher")
            return

        # Create ONE browser for all three service types
        self._browser = AsyncServiceBrowser(
            azc.zeroconf,
            list(SERVICE_TYPES.values()),
            handlers=[self._on_state_change],
        )
        logger.info("cast discovery: started browsing for %s", ", ".join(SERVICE_TYPES.values()))

    async def stop(self) -> None:
        """Stop the browser. Does not touch the publisher."""
        if self._browser is not None:
            await self._browser.async_cancel()
            self._browser = None
        # Keep _discovered and _paired_online across restarts? Per spec, _discovered is runtime-only.
        # But paired online flags should persist across stop/start? The spec says online is runtime state.
        # On stop, we clear the discovered cache but keep paired online flags.
        self._discovered.clear()

    def _on_state_change(
        self,
        zc: Any,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Sync callback from zeroconf for service state changes."""
        # This runs on zeroconf's thread/loop; schedule async work
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            asyncio.ensure_future(self._resolve(service_type, name))
        elif state_change == ServiceStateChange.Removed:
            asyncio.ensure_future(self._mark_absent(name, service_type))

    async def _resolve(self, service_type: str, name: str) -> None:
        """Resolve a service name to full info and update discovered/paired state."""
        azc = self._zc
        if azc is None:
            return

        try:
            info = await azc.async_get_service_info(service_type, name, timeout=3000)
        except Exception as exc:  # noqa: BLE001 - network I/O can raise various exceptions
            logger.debug("cast discovery: async_get_service_info failed for %s: %s", name, exc)
            return

        if info is None:
            logger.debug("cast discovery: no info for %s", name)
            return

        # Derive device_id from name (strip service_type suffix)
        # name format: "instance._googlecast._tcp.local."
        device_id = name[:-len(service_type)].removesuffix(".")

        # Determine kind from service_type
        kind = next((k for k, st in SERVICE_TYPES.items() if st == service_type), "unknown")

        # Friendly name from properties (fn = Chromecast friendly name)
        friendly_name = device_id
        properties = info.properties or {}
        if b"fn" in properties:
            try:
                friendly_name = properties[b"fn"].decode("utf-8")
            except UnicodeDecodeError:
                logger.debug("cast discovery: failed to decode fn property for %s", name)

        # Address from parsed_addresses
        addresses = info.parsed_addresses()
        if not addresses:
            logger.debug("cast discovery: no addresses for %s", name)
            return
        address = addresses[0]

        # Port
        port = info.port or 0

        now_iso = datetime.now(UTC).isoformat()

        # Update runtime discovered cache
        self._discovered[device_id] = {
            "id": device_id,
            "friendly_name": friendly_name,
            "kind": kind,
            "address": address,
            "port": port,
            "last_seen": now_iso,
        }

        # If this device is paired, update its online status and persist last_seen
        paired_rows = await self._store.list_all()
        paired_ids = {row["device_id"] for row in paired_rows}
        if device_id in paired_ids:
            self._paired_online[device_id] = True
            await self._store.touch_seen(device_id, now_iso)

        logger.debug("cast discovery: resolved %s (%s) at %s:%d", device_id, kind, address, port)

    async def _mark_absent(self, name: str, service_type: str) -> None:
        """Mark a device as absent (Removed event)."""
        device_id = name[:-len(service_type)].removesuffix(".")

        # Remove from discovered cache
        self._discovered.pop(device_id, None)

        # If paired, mark runtime offline (but keep in registry)
        paired_rows = await self._store.list_all()
        paired_ids = {row["device_id"] for row in paired_rows}
        if device_id in paired_ids:
            self._paired_online[device_id] = False
            logger.debug("cast discovery: paired device %s marked offline", device_id)

    async def devices(self) -> list[dict]:
        """Return all devices: paired (from store) + discovered-but-unpaired (async)."""
        result: list[dict] = []

        # Paired devices from store
        paired_rows = await self._store.list_all()
        for row in paired_rows:
            result.append({
                "id": row["device_id"],
                "friendly_name": row["friendly_name"],
                "kind": row["kind"],
                "address": row["address"],
                "port": row["port"],
                "last_seen": row["last_seen"],
                "paired": True,
                "online": self._paired_online.get(row["device_id"], False),
            })

        # Discovered but unpaired devices
        paired_ids = {row["device_id"] for row in paired_rows}
        for device_id, info in self._discovered.items():
            if device_id not in paired_ids:
                result.append({
                    "id": info["id"],
                    "friendly_name": info["friendly_name"],
                    "kind": info["kind"],
                    "address": info["address"],
                    "port": info["port"],
                    "last_seen": info["last_seen"],
                    "paired": False,
                    "online": True,  # discovered means currently online
                })

        return result

    async def pair(
        self,
        device_id: str,
        friendly_name: str,
        kind: str,
        address: str,
        port: int,
    ) -> None:
        """Pair a device (write through store)."""
        now_iso = datetime.now(UTC).isoformat()
        await self._store.upsert(
            device_id=device_id,
            friendly_name=friendly_name,
            kind=kind,
            address=address,
            port=port,
            last_seen=now_iso,
            added_by_address=0,
        )
        self._paired_online[device_id] = True

    async def unpair(self, device_id: str) -> None:
        """Unpair a device (remove from store)."""
        await self._store.remove(device_id)
        self._paired_online.pop(device_id, None)

    async def add_by_address(
        self,
        device_id: str,
        friendly_name: str,
        kind: str,
        address: str,
        port: int,
    ) -> None:
        """Manually add a device by static address (marks as paired and online)."""
        now_iso = datetime.now(UTC).isoformat()
        await self._store.upsert(
            device_id=device_id,
            friendly_name=friendly_name,
            kind=kind,
            address=address,
            port=port,
            last_seen=now_iso,
            added_by_address=1,
        )
        self._paired_online[device_id] = True