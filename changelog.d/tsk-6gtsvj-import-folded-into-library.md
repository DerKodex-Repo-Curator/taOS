### Added
- Library: local-file ingestion (drag-and-drop + file picker) for .txt, .md, .pdf, .html, .json, .csv with keyboard-accessible drop zone and progress indicator
- Library: "Embed now" action on file-type items opens agent picker and calls /api/import/embed backend

### Removed
- Import app (standalone launchpad tile, upload icon) — functionality folded into Library
- ImportApp.tsx deleted

### Changed
- Library is now the single universal ingestion surface for both URLs and local files
- Registry: removed "import" app id; launchpadOrder compacted for subsequent apps
