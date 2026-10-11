"""Tests for cast discovery and paired device registry.

RED-FIRST: these tests must fail before the implementation is added.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from tinyagentos.base_store import BaseStore
from tinyagentos.cast_device_store import CastDeviceStore
from tinyagentos.services.cast_discovery import CastDiscovery
from tinyagentos.services.mdns_publisher import MdnsPublisher


@pytest_asyncio.fixture
async def cast_store(tmp_path):
    """Fixture for CastDeviceStore."""
    s = CastDeviceStore(tmp_path / "cast.db")
    await s.init()
    yield s
    await s.close()


@pytest_asyncio.fixture
async def cast_store_2(tmp_path):
    """Second fixture for CastDeviceStore (same path for restart test)."""
    s = CastDeviceStore(tmp_path / "cast.db")
    await s.init()
    yield s
    await s.close()


class FakeServiceInfo:
    """Fake AsyncServiceInfo for testing."""
    def __init__(self, addresses, port, properties, server="test.local."):
        self._addresses = addresses
        self.port = port
        self.properties = properties
        self.server = server

    def parsed_addresses(self, version=None):
        return self._addresses


class FakeAsyncZeroconf:
    """Fake AsyncZeroconf for testing."""
    def __init__(self):
        self.zeroconf = object()  # sync core
        self.async_get_service_info = AsyncMock()


class FakeMdnsPublisher:
    """Fake MdnsPublisher with a fake AsyncZeroconf."""
    def __init__(self):
        self._zc = FakeAsyncZeroconf()


@pytest.fixture
def fake_publisher():
    """Fixture for a fake publisher with mocked AsyncZeroconf."""
    publisher = MdnsPublisher(port=6969)
    publisher._zc = FakeAsyncZeroconf()
    return publisher


class FakeAsyncServiceBrowser:
    """Fake AsyncServiceBrowser that records its arguments."""
    def __init__(self, zeroconf, type_, handlers=None, **kwargs):
        self.zeroconf = zeroconf
        self.type_ = type_
        self.handlers = handlers
        self.async_cancel = AsyncMock()

    @classmethod
    def reset(cls):
        cls.last_instance = None
        cls.last_zeroconf = None
        cls.last_handlers = None

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        cls.last_instance = instance
        cls.last_zeroconf = args[0] if args else None
        cls.last_handlers = kwargs.get('handlers')
        return instance


@pytest.fixture
def fake_browser_class(monkeypatch):
    """Monkeypatch AsyncServiceBrowser with our fake."""
    FakeAsyncServiceBrowser.reset()
    monkeypatch.setattr(
        "tinyagentos.services.cast_discovery.AsyncServiceBrowser",
        FakeAsyncServiceBrowser
    )
    yield FakeAsyncServiceBrowser


# ---------------------------------------------------------------------------
# CastDeviceStore tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cast_device_store_upsert_and_list(cast_store):
    """Test upsert and list_all operations."""
    await cast_store.upsert(
        device_id="test-1",
        friendly_name="Test Device",
        kind="googlecast",
        address="192.168.1.100",
        port=8008,
        last_seen="2026-01-01T00:00:00+00:00",
        added_by_address=0,
    )
    rows = await cast_store.list_all()
    assert len(rows) == 1
    row = rows[0]
    assert row["device_id"] == "test-1"
    assert row["friendly_name"] == "Test Device"
    assert row["kind"] == "googlecast"
    assert row["address"] == "192.168.1.100"
    assert row["port"] == 8008
    assert row["added_by_address"] == 0


@pytest.mark.asyncio
async def test_cast_device_store_remove(cast_store):
    """Test remove operation."""
    await cast_store.upsert(
        device_id="test-1",
        friendly_name="Test Device",
        kind="googlecast",
        address="192.168.1.100",
        port=8008,
        last_seen="2026-01-01T00:00:00+00:00",
        added_by_address=0,
    )
    await cast_store.remove("test-1")
    rows = await cast_store.list_all()
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_cast_device_store_touch_seen(cast_store):
    """Test touch_seen updates last_seen."""
    await cast_store.upsert(
        device_id="test-1",
        friendly_name="Test Device",
        kind="googlecast",
        address="192.168.1.100",
        port=8008,
        last_seen="2026-01-01T00:00:00+00:00",
        added_by_address=0,
    )
    await cast_store.touch_seen("test-1", "2026-01-02T00:00:00+00:00")
    rows = await cast_store.list_all()
    assert rows[0]["last_seen"] == "2026-01-02T00:00:00+00:00"


@pytest.mark.asyncio
async def test_cast_device_store_persists_across_restart(cast_store, cast_store_2):
    """Test that data persists across store restart."""
    await cast_store.upsert(
        device_id="persist-1",
        friendly_name="Persist Device",
        kind="airplay",
        address="192.168.1.200",
        port=7000,
        last_seen="2026-01-01T00:00:00+00:00",
        added_by_address=0,
    )
    rows = await cast_store_2.list_all()
    assert len(rows) == 1
    assert rows[0]["device_id"] == "persist-1"
    assert rows[0]["friendly_name"] == "Persist Device"


# ---------------------------------------------------------------------------
# CastDiscovery tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paired_device_persists_when_it_stops_advertising(fake_publisher, fake_browser_class, tmp_path):
    """RED test: A PAIRED device that stops advertising remains in GET /api/cast/devices marked offline.

    A paired TV that is asleep silently vanishes from discovery and does NOT
    revert to unpaired. The registry must persist across absence.
    """
    # Create a store and discovery
    store = CastDeviceStore(tmp_path / "cast.db")
    await store.init()

    discovery = CastDiscovery(fake_publisher, store)
    await discovery.start()

    # Pair a device
    await discovery.pair("living-room", "Living Room TV", "googlecast", "192.168.1.100", 8008)

    # Let the handler for Added be recorded
    assert fake_browser_class.last_handlers is not None
    handler = fake_browser_class.last_handlers[0] if isinstance(fake_browser_class.last_handlers, list) else fake_browser_class.last_handlers

    # Simulate device discovery (Added) - create a fake service info
    fake_info = FakeServiceInfo(
        addresses=["192.168.1.100"],
        port=8008,
        properties={b"fn": b"Living Room TV", b"md": b"Chromecast"},
        server="living-room.local."
    )
    fake_publisher._zc.async_get_service_info.return_value = fake_info

    # Call the handler for Added
    from zeroconf import ServiceStateChange
    handler(fake_publisher._zc.zeroconf, "_googlecast._tcp.local.", "living-room._googlecast._tcp.local.", ServiceStateChange.Added)
    await asyncio.sleep(0.1)  # let the async task run

    # Check device is online
    devices = await discovery.devices()
    living_room = next((d for d in devices if d["id"] == "living-room"), None)
    assert living_room is not None, "paired device 'living-room' missing from device list"
    assert living_room["paired"] is True, "paired device should be marked as paired"
    assert living_room["online"] is True, "paired device should be marked as online after discovery"

    # Simulate device stopping advertising (Removed)
    handler(fake_publisher._zc.zeroconf, "_googlecast._tcp.local.", "living-room._googlecast._tcp.local.", ServiceStateChange.Removed)
    await asyncio.sleep(0.1)

    # Device should still be in the registry, marked offline
    devices = await discovery.devices()
    living_room = next((d for d in devices if d["id"] == "living-room"), None)
    assert living_room is not None, "paired device 'living-room' missing from device list after removal"
    assert living_room["paired"] is True, "paired device should remain paired"
    assert living_room["online"] is False, "paired device should be marked as offline"

    await store.close()


@pytest.mark.asyncio
async def test_paired_device_survives_restart_as_offline(fake_publisher, fake_browser_class, tmp_path):
    """RED test: A paired device survives a full restart of CastDiscovery and CastDeviceStore as offline."""
    # First store and discovery
    store1 = CastDeviceStore(tmp_path / "cast.db")
    await store1.init()
    discovery1 = CastDiscovery(fake_publisher, store1)
    await discovery1.start()

    # Pair a device
    await discovery1.pair("bedroom-tv", "Bedroom TV", "airplay", "192.168.1.50", 7000)

    # Stop the first discovery
    await discovery1.stop()
    await store1.close()

    # Create NEW store and discovery on the SAME path
    store2 = CastDeviceStore(tmp_path / "cast.db")
    await store2.init()

    discovery2 = CastDiscovery(fake_publisher, store2)
    await discovery2.start()

    # Device should be listed as paired=True, online=False (not seen since restart)
    devices = await discovery2.devices()
    bedroom = next((d for d in devices if d["id"] == "bedroom-tv"), None)
    assert bedroom is not None, "paired device should survive restart"
    assert bedroom["paired"] is True, "device should remain paired after restart"
    assert bedroom["online"] is False, "device should be offline after restart until seen again"

    await store2.close()


@pytest.mark.asyncio
async def test_discovery_uses_the_publishers_zeroconf_and_never_makes_its_own(fake_publisher, fake_browser_class, tmp_path, monkeypatch):
    """RED test: Discovery must use the publisher's zeroconf and NEVER create its own AsyncZeroconf/Zeroconf."""
    # Monkeypatch AsyncZeroconf and Zeroconf __init__ to raise if called
    import zeroconf.asyncio
    import zeroconf

    original_azc_init = zeroconf.asyncio.AsyncZeroconf.__init__
    original_zc_init = zeroconf.Zeroconf.__init__

    def boom_azc_init(self, *args, **kwargs):
        raise AssertionError("second Zeroconf instance (AsyncZeroconf)")

    def boom_zc_init(self, *args, **kwargs):
        raise AssertionError("second Zeroconf instance (Zeroconf)")

    monkeypatch.setattr(zeroconf.asyncio.AsyncZeroconf, "__init__", boom_azc_init)
    monkeypatch.setattr(zeroconf.Zeroconf, "__init__", boom_zc_init)

    try:
        store = CastDeviceStore(tmp_path / "cast.db")
        await store.init()
        discovery = CastDiscovery(fake_publisher, store)
        await discovery.start()

        # The fake browser should have received the publisher's zeroconf (identity check)
        assert fake_browser_class.last_zeroconf is fake_publisher._zc.zeroconf, \
            "AsyncServiceBrowser must receive publisher._zc.zeroconf (identity check)"

        # Publisher's _zc should be unchanged
        assert fake_publisher._zc is not None, "publisher's _zc must not be replaced"

        await discovery.stop()
        await store.close()
    finally:
        monkeypatch.setattr(zeroconf.asyncio.AsyncZeroconf, "__init__", original_azc_init)
        monkeypatch.setattr(zeroconf.Zeroconf, "__init__", original_zc_init)


# ---------------------------------------------------------------------------
# Cast route auth tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthenticated_cast_routes_are_refused(tmp_path):
    """RED test: Unauthenticated requests to cast routes must return 401."""
    from tinyagentos.app import create_app
    from httpx import AsyncClient, ASGITransport

    app = create_app(data_dir=tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/cast/devices")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"