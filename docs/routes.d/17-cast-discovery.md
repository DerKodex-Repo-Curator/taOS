# Cast device discovery and pairing (session-only)

## API endpoints

### GET /api/cast/devices

List all discovered and paired Chromecast/AirPlay/RAOP devices.

**Auth:** `CurrentUser` (session cookie + CSRF)

**Response:**
```json
{
  "devices": [
    {
      "id": "living-room",
      "friendly_name": "Living Room TV",
      "kind": "googlecast",
      "address": "192.168.1.100",
      "port": 8008,
      "last_seen": "2026-01-15T10:30:00+00:00",
      "paired": true,
      "online": true
    }
  ]
}
```

- `paired: true` — device is in the persistent registry (user paired it)
- `paired: false` — device discovered via mDNS but not yet paired
- `online: true` — device currently advertising (discovered) or paired with `added_by_address=1`
- `online: false` — paired device that has stopped advertising (asleep/offline)

### POST /api/cast/devices/{device_id}/pair

Pair with a discovered or already-paired device. Optional body can override `friendly_name`, `kind`, `address`, `port`.

**Auth:** `CurrentUser` (session cookie + CSRF)

**Body (optional):**
```json
{
  "friendly_name": "Living Room TV",
  "kind": "googlecast",
  "address": "192.168.1.100",
  "port": 8008
}
```

**Response:** `{"status": "paired", "device_id": "living-room"}`

**Errors:** `404` if device is neither discovered nor paired.

### DELETE /api/cast/devices/{device_id}

Remove a device from the paired registry (unpair). Does NOT remove discovered-but-unpaired devices.

**Auth:** `CurrentUser` (session cookie + CSRF)

**Response:** `{"status": "unpaired", "device_id": "living-room"}`

**Errors:** `404` if device is not in the paired registry.

### POST /api/cast/devices

Manually add a device by static IP/hostname for hosts that cannot multicast.

**Auth:** `CurrentUser` (session cookie + CSRF)

**Body:**
```json
{
  "device_id": "bedroom-tv",
  "friendly_name": "Bedroom TV",
  "kind": "airplay",
  "address": "192.168.1.50",
  "port": 7000
}
```

**Response:** `201 {"status": "added", "device_id": "bedroom-tv"}`

**Errors:** `400` if `device_id` or `address` missing; `422` if `kind` not in `googlecast|airplay|raop`.

## Discovery mechanics

- Runs on the **same** `AsyncZeroconf` instance as `MdnsPublisher` (no second Zeroconf process).
- Browses three service types: `_googlecast._tcp.local.`, `_airplay._tcp.local.`, `_raop._tcp.local.`.
- Uses `AsyncServiceBrowser` with a state-change handler (`Added`/`Updated`/`Removed`).
- On `Added`/`Updated`: resolves via `async_get_service_info`, extracts `fn` (friendly name), `md` (model), address, port.
- On `Removed`: marks paired device runtime `online=false`; NEVER removes from registry.
- Device ID derived from mDNS instance name: `"living-room._googlecast._tcp.local."` → `"living-room"`.
- Paired devices persist across restarts with `online=false` until re-discovered.
- Manual add-by-address creates a paired device with `added_by_address=1` and `online=true`.

## Persistence

- SQLite store at `data_dir/cast_devices.db` (`CastDeviceStore`).
- Schema: `id`, `friendly_name`, `kind`, `address`, `port`, `last_seen`, `added_by_address`.
- Online/offline is RUNTIME state — not a column.