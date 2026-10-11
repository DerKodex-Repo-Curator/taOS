### Added

- Cast (Chromecast/AirPlay) device discovery and paired device registry
  - Service browser for _googlecast._tcp.local., _airplay._tcp.local., and _raop._tcp.local.
  - Reuses existing AsyncZeroconf instance from MdnsPublisher to avoid port conflicts
  - Persists paired devices across absence (offline devices remain in registry)
  - Routes:
    - GET /api/cast/devices - List all cast devices (discovered + paired)
    - POST /api/cast/devices/{id}/pair - Pair with a device (approval via Decisions enforced by C5)
    - DELETE /api/cast/devices/{id}/unpair - Remove from paired registry
    - POST /api/cast/devices - Manual add-by-address for hosts without multicast
  - Fixes:
    - Paired devices remain in registry when offline (doesn't disappear)
    - Browser startup doesn't interfere with existing mDNS publication
