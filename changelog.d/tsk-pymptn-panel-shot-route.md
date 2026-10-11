### Added

- `POST /api/desktop/panel-shot` returns a PNG of what is actually on the handset glass by running the on-device `taos-shot`, instead of the DOM raster that `/api/desktop/screenshot` produces. Gated like `/screenshot` (native agent token or signed-in session); 404 without `taos-shot`, 429 while a capture runs, 504 on timeout, 502 on failure.
- The native agent's token is refused on the desktop-control routes once it has been superseded by a token rotation, and a cancelled panel capture now stops taos-shot before the next capture can start.
