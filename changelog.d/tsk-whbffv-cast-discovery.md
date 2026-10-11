### Added
- Cast device discovery (Chromecast/AirPlay/RAOP) via mDNS using the existing AsyncZeroconf instance
- Persisted paired device registry with online/offline runtime state
- REST API: GET /api/cast/devices, POST /api/cast/devices/{id}/pair, DELETE /api/cast/devices/{id}, POST /api/cast/devices (manual add-by-address)