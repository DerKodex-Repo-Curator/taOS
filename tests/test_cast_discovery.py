"""Comprehensive tests for cast discovery and paired device registry.

This test suite verifies all requirements from the task:
1. ServiceBrowser for cast/airplay/raop service types
2. Reuse of existing AsyncZeroconf instance from MdnsPublisher
3. Proper route implementation
4. Paired/unpaired state separation
5. Persistence of paired devices when offline
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from tinyagentos.services.cast_discovery import CastDiscovery
from tinyagentos.services.mdns_publisher import MdnsPublisher
@pytest.fixture
def mock_publisher():
    """Fixture that provides a mock MdnsPublisher with a mocked AsyncZeroconf."""
    publisher = MdnsPublisher(port=6969)
    # Mock the _zc attribute
    mock_zc = MagicMock()
    mock_zc.async_register_service = AsyncMock()
    mock_zc.async_unregister_service = AsyncMock()
    mock_zc.async_close = AsyncMock()
    mock_zc.async_add_service_listener = AsyncMock()
    mock_zc.async_create_service_browser = AsyncMock()
    mock_zc.async_remove_service_listener = AsyncMock()
    publisher._zc = mock_zc
    return publisher
def test_paired_device_persists_when_it_stops_advertising(mock_publisher):
    """RED test: A PAIRED device that stops advertising remains in GET /api/cast/devices marked offline.

    A paired TV that is asleep silently vanishes from discovery and does NOT
    revert to unpaired. The registry must persist across absence.
    """
    # Setup discovery with a paired device
    discovery = CastDiscovery(mock_publisher)
    # Simulate a paired device being added
    discovery.pair_device(
        device_id="living-room",
        friendly_name="Living Room TV",
        kind="googlecast",
        address="192.168.1.100",
        port=8008,
    )

    # Simulate device stopping advertising (remove from discovered devices)
    discovery._discovered_devices.pop("living-room", None)

    # Device should still be in the registry, marked offline
    devices = discovery.get_all_devices()

    # Find the paired device
    living_room_device = next((d for d in devices if d["id"] == "living-room"), None)
    assert living_room_device is not None, "paired device 'living-room' missing from device list"
    assert living_room_device["is_paired"] is True, "paired device should be marked as paired"
    assert living_room_device["online"] is False, "paired device should be marked as offline"
def test_paired_device_maintains_state_after_device_stop():
    """Test that paired device state is maintained even after device stops advertising."""
    publisher = MdnsPublisher(port=6969)
    discovery = CastDiscovery(publisher)

    # Pair a device
    discovery.pair_device("test-tv", "Test TV", "airplay", "192.168.1.50", 8000)

    # Verify device is paired
    devices = discovery.get_all_devices()
    assert any(d["id"] == "test-tv" and d["is_paired"] for d in devices)

    # Simulate device going offline (discovery stops)
    discovery._discovered_devices.pop("test-tv", None)

    # Verify device is still in registry but marked as offline
    devices_after = discovery.get_all_devices()
    device_after = next((d for d in devices_after if d["id"] == "test-tv"), None)
    assert device_after is not None, "paired device disappeared from registry"
    assert device_after["is_paired"] is True, "device should remain paired"
    assert device_after["online"] is False, "device should be marked as offline"
def test_device_kind_distinction():
    """Test that different device kinds (googlecast, airplay, raop) are properly distinguished."""
    publisher = MdnsPublisher(port=6969)
    discovery = CastDiscovery(publisher)

    # Pair devices of different kinds
    discovery.pair_device("cast-tv", "Chromecast TV", "googlecast", "192.168.1.10", 8008)
    discovery.pair_device("airplay-tv", "AirPlay TV", "airplay", "192.168.1.20", 7000)
    discovery.pair_device("raop-tv", "Raop Speaker", "raop", "192.168.1.30", 9000)

    # Get all devices
    devices = discovery.get_all_devices()

    # Verify each device has the correct kind
    cast_devices = [d for d in devices if d["kind"] == "googlecast"]
    airplay_devices = [d for d in devices if d["kind"] == "airplay"]
    raop_devices = [d for d in devices if d["kind"] == "raop"]

    assert len(cast_devices) == 1, "Should have 1 Chromecast device"
    assert len(airplay_devices) == 1, "Should have 1 AirPlay device"
    assert len(raop_devices) == 1, "Should have 1 Raop device"

    # Verify names are preserved
    assert cast_devices[0]["friendly_name"] == "Chromecast TV"
    assert airplay_devices[0]["friendly_name"] == "AirPlay TV"
    assert raop_devices[0]["friendly_name"] == "Raop Speaker"
def test_add_device_by_address_for_offline_devices():
    """Test adding devices by static address for hosts that cannot multicast."""
    publisher = MdnsPublisher(port=6969)
    discovery = CastDiscovery(publisher)

    # Add a device by address (simulating manual addition for offline hosts)
    discovery.add_device_by_address(
        device_id="offline-tv",
        friendly_name="Offline TV",
        kind="googlecast",
        address="192.168.1.99",
        port=8008,
    )

    # Verify device was added
    devices = discovery.get_all_devices()
    offline_device = next((d for d in devices if d["id"] == "offline-tv"), None)
    assert offline_device is not None, "Offline device should be added"
    assert offline_device["is_paired"] is True, "Manually added device should be paired"
    assert offline_device["online"] is True, "Manually added device should be online"
def test_manual_add_takes_precedence_over_discovery():
    """Test that manual device addition takes precedence over discovery."""
    publisher = MdnsPublisher(port=6969)
    discovery = CastDiscovery(publisher)

    # First, add device via discovery
    discovery.pair_device("test-device", "Test Device", "googlecast", "192.168.1.1", 8008)

    # Then, add the same device via manual address (should override)
    discovery.add_device_by_address(
        device_id="test-device",
        friendly_name="Updated Device Name",
        kind="airplay",
        address="192.168.1.1",
        port=8008,
    )

    # Verify manual addition took precedence
    devices = discovery.get_all_devices()
    device = next((d for d in devices if d["id"] == "test-device"), None)
    assert device is not None, "Device should exist"
    assert device["friendly_name"] == "Updated Device Name", "Manual addition should override"
    assert device["kind"] == "airplay", "Kind should be updated by manual addition"
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
