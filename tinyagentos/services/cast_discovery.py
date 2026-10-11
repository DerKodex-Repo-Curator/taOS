"""Chromecast/AirPlay device discovery and paired device registry for screencast.

Uses the existing zeroconf.AsyncZeroconf instance from MdnsPublisher to avoid
competing Zeroconf instances. Persists paired devices (id, friendly name, kind,
address, last-seen) separately from discovery results.
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf
from zeroconf import ServiceListener
from zeroconf import Zeroconf

from tinyagentos.services.mdns_publisher import MdnsPublisher

logger = logging.getLogger(__name__)

SERVICE_TYPES = {
    "googlecast": "_googlecast._tcp.local.",
    "airplay": "_airplay._tcp.local.",
    "raop": "_raop._tcp.local.",
}
@dataclass
class DiscoveredDevice:
    """Device discovered via mDNS."""
    id: str
    name: str
    kind: str
    address: str
    port: int
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    service_info: ServiceInfo | None = None
@dataclass
class PairedDevice:
    """Paired device that may be offline."""
    id: str
    friendly_name: str
    kind: str
    address: str
    port: int
    last_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_online: bool = True
    service_info: ServiceInfo | None = None
    added_by_address: bool = False
class CastDiscovery(ServiceListener):
    """Manages discovery and registry of paired Chromecast/AirPlay devices.

    The core discovery loop runs inside MdnsPublisher's existing AsyncZeroconf
    instance. A lightweight wrapper provides the API to browse for cast services
    and maintain the paired device registry.
    """

    def __init__(self, publisher: MdnsPublisher) -> None:
        self._publisher = publisher
        self._zc: AsyncZeroconf | None = None
        self._browsers: dict[str, Any] = {}
        self._discovered_devices: dict[str, DiscoveredDevice] = {}
        self._paired_devices: dict[str, PairedDevice] = {}

    async def start(self) -> None:
        """Start browsing for all cast service types using the existing AsyncZeroconf."""
        self._zc = self._publisher._zc if hasattr(self._publisher, '_zc') else None
        if self._zc is None:
            logger.warning("cast discovery: AsyncZeroconf not available in MdnsPublisher")
            return

        for kind, service_type in SERVICE_TYPES.items():
            # Use async_add_service_listener to create a service browser
            await self._zc.async_add_service_listener(
                self,
                service_type,
            )
            self._browsers[kind] = True  # Just track that we have a browser for this kind

    async def stop(self) -> None:
        """Stop all browsers and clear state."""
        # Remove listeners from the zeroconf instance
        if self._zc:
            for kind, service_type in SERVICE_TYPES.items():
                try:
                    await self._zc.async_remove_service_listener(self)
                except Exception:
                    logger.exception("cast discovery: failed to close browser for %s", kind)
        self._browsers.clear()
        self._discovered_devices.clear()
        # Reset added_by_address flag when stopping discovery
        # Note: This is intentional - when discovery stops, manually added devices
        # that were also discovered should become offline to reflect true state
        for device in self._paired_devices.values():
            device.added_by_address = False

    def add_service(self, zc: Any, type_: str, name: str) -> None:
        """Handle new service advertisement."""
        # This callback is called when a service is added
        # We need to trigger a discovery of the service details
        if self._zc:
            # Schedule the actual discovery to be handled later
            import asyncio
            asyncio.create_task(self._schedule_discovery_for_name(name, type_))

    def remove_service(self, zc: Any, type_: str, name: str) -> None:
        """Handle service removal."""
        device_id = name.split(".", 1)[0]

        # Remove from discovered devices if present
        if device_id in self._discovered_devices:
            del self._discovered_devices[device_id]

        # Mark paired device as offline if it was discovered
        if device_id in self._paired_devices and not self._paired_devices[device_id].added_by_address:
            self._paired_devices[device_id].is_online = False

    def update_service(self, zc: Any, type_: str, name: str) -> None:
        """Handle service updates."""
        # For ServiceListener.update_service, we need to get ServiceInfo from the zeroconf instance
        if self._zc:
            try:
                info = self._zc.get_service_info(type_, name)
                if not info:
                    return
            except Exception as e:
                logger.debug("Failed to get service info for %s: %s", name, e)
                return
        else:
            return

        # Handle zeroconf service updates (advertisements)
        # Check if this device is already paired
        # If it is, we should update the paired device state instead of creating discovered device entry
        service_type = None
        kind = None
        for k, st in SERVICE_TYPES.items():
            if info.name.endswith(st):
                service_type = st
                kind = k
                break
        if service_type is None:
            return

        # Check if this device is already paired
        device_id = info.name[:-len(service_type)] if info.name.endswith(service_type) else info.name
        if device_id in self._paired_devices:
            # Update paired device with current service info
            now = datetime.now(timezone.utc)
            self._paired_devices[device_id].is_online = True
            self._paired_devices[device_id].last_seen = now
            self._paired_devices[device_id].service_info = info
            logger.debug("cast discovery: paired device %s is online", device_id)
            return

        # Extract address from ServiceInfo addresses (bytes)
        if not info.addresses:
            logger.debug("cast discovery: ServiceInfo %s has no addresses", info.name)
            return
        
        # Use socket.inet_ntop for proper IPv4/IPv6 address formatting
        address_bytes = info.addresses[0]
        address = socket.inet_ntop(socket.AF_INET, address_bytes) if len(address_bytes) == 4 else socket.inet_ntop(socket.AF_INET6, address_bytes)

        device_id = info.name[:-len(service_type)] if info.name.endswith(service_type) else info.name

        # Update or create discovered device entry
        now = datetime.now(timezone.utc)
        if device_id in self._discovered_devices:
            dev = self._discovered_devices[device_id]
            dev.last_seen = now
            dev.service_info = info
            dev.kind = kind
            dev.address = address
            dev.port = info.port if info.port else 8008
        else:
            # Infer port/name from info if missing
            port = info.port if info.port else 8008
            name_str = device_id
            self._discovered_devices[device_id] = DiscoveredDevice(
                id=device_id,
                name=name_str,
                kind=kind,
                address=address,
                port=port,
                last_seen=now,
                service_info=info,
            )

        # Update paired device online status if this device is paired.
        if device_id in self._paired_devices:
            self._paired_devices[device_id].is_online = True
            self._paired_devices[device_id].last_seen = now
            self._paired_devices[device_id].service_info = info

        logger.debug("cast discovery: updated device %s (%s) online", device_id, kind)

    async def _schedule_discovery_for_name(self, name: str, type_: str) -> None:
        """Schedule discovery of a specific service name."""
        # Use the existing zeroconf instance to get service info
        if self._zc:
            try:
                info = self._zc.get_service_info(type_, name)
                if info and not info.addresses:
                    logger.debug("cast discovery: ServiceInfo %s has no addresses", info.name)
                    return
                
                # Check if this device is already paired
                # If it is, we should update the paired device state instead of creating discovered device entry
                # Determine service_type from info.name
                service_type = None
                for k, st in SERVICE_TYPES.items():
                    if info.name.endswith(st):
                        service_type = st
                        break
                if service_type is None:
                    return
                
                device_id = info.name[:-len(service_type)] if info.name.endswith(service_type) else info.name
                
                # If device is already paired, update paired device state
                if device_id in self._paired_devices:
                    # Update paired device with current service info
                    now = datetime.now(timezone.utc)
                    self._paired_devices[device_id].is_online = True
                    self._paired_devices[device_id].last_seen = now
                    self._paired_devices[device_id].service_info = info
                    logger.debug("cast discovery: paired device %s is online", device_id)
                    return

                # Extract address from ServiceInfo addresses (bytes)
                if info and info.addresses:
                    address_bytes = info.addresses[0]
                    address = socket.inet_ntop(socket.AF_INET, address_bytes) if len(address_bytes) == 4 else socket.inet_ntop(socket.AF_INET6, address_bytes)
                
                # Determine service type and kind from info.name
                service_type = None
                kind = None
                for k, st in SERVICE_TYPES.items():
                    if info.name.endswith(st):
                        service_type = st
                        kind = k
                        break
                if service_type is None:
                    return

                # Extract device_id from ServiceInfo.name by removing service type suffix
                device_id = info.name[:-len(service_type)] if info.name.endswith(service_type) else info.name
                
                # Update or create discovered device entry
                now = datetime.now(timezone.utc)
                if device_id in self._discovered_devices:
                    dev = self._discovered_devices[device_id]
                    dev.last_seen = now
                    dev.service_info = info
                    dev.kind = kind
                    dev.address = address
                    dev.port = info.port if info.port else 8008
                else:
                    # Infer port/name from info if missing
                    port = info.port if info.port else 8008
                    name_str = device_id
                    self._discovered_devices[device_id] = DiscoveredDevice(
                        id=device_id,
                        name=name_str,
                        kind=kind,
                        address=address,
                        port=port,
                        last_seen=now,
                        service_info=info,
                    )

                # Update paired device online status if this device is paired.
                if device_id in self._paired_devices:
                    self._paired_devices[device_id].is_online = True
                    self._paired_devices[device_id].last_seen = now
                    self._paired_devices[device_id].service_info = info

                logger.debug("cast discovery: scheduled device %s (%s) online", device_id, kind)
            except Exception as e:
                logger.debug("Failed to schedule discovery for %s: %s", name, e)

    def get_all_devices(self) -> list[dict[str, Any]]:
        """Return discovered + paired devices for the API."""
        # Update paired device online status based on current discovered devices
        # Devices in paired registry but not in discovered devices are considered offline
        # unless they were added by address (manually added and should remain online)
        for device_id in list(self._paired_devices.keys()):
            if device_id not in self._discovered_devices:
                # Only mark as offline if not added by address (manually added devices should stay online)
                if not self._paired_devices[device_id].added_by_address:
                    self._paired_devices[device_id].is_online = False

        result: list[dict[str, Any]] = []

        # Discovered (unpaired or newly appeared)
        for dev in self._discovered_devices.values():
            result.append({
                "id": dev.id,
                "friendly_name": dev.name,
                "kind": dev.kind,
                "address": dev.address,
                "port": dev.port,
                "last_seen": dev.last_seen.isoformat(),
                "is_online": True,
                "is_paired": self._paired_devices.get(dev.id) is not None,
                "online": True,
            })

        # Paired (including offline)
        for dev in self._paired_devices.values():
            result.append({
                "id": dev.id,
                "friendly_name": dev.friendly_name,
                "kind": dev.kind,
                "address": dev.address,
                "port": dev.port,
                "last_seen": dev.last_seen.isoformat(),
                "is_online": dev.is_online,
                "is_paired": True,
                "online": dev.is_online,
            })

        return result

    def pair_device(self, device_id: str, friendly_name: str, kind: str, address: str, port: int) -> None:
        """Mark a device as paired (create or update registry)."""
        # If device exists as discovered, migrate its info.
        if device_id in self._discovered_devices:
            disc = self._discovered_devices.pop(device_id)
            friendly_name = disc.name if friendly_name == "" else friendly_name
            kind = disc.kind if kind == "" else kind
            address = disc.address if address == "" else address
            port = disc.port if port == 0 else port

        self._paired_devices[device_id] = PairedDevice(
            id=device_id,
            friendly_name=friendly_name,
            kind=kind,
            address=address,
            port=port,
            last_seen=datetime.now(timezone.utc),
            is_online=True,
            added_by_address=False,
        )

    def unpair_device(self, device_id: str) -> None:
        """Remove a device from the paired registry."""
        self._paired_devices.pop(device_id, None)

    def add_device_by_address(self, device_id: str, friendly_name: str, kind: str, address: str, port: int) -> None:
        """Manually add a device by its static address (for hosts that cannot multicast)."""
        self.pair_device(device_id, friendly_name, kind, address, port)
        if device_id in self._paired_devices:
            self._paired_devices[device_id].added_by_address = True
