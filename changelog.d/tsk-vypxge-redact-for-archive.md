### Added
- `redact_for_archive()` function in `tinyagentos/log_redaction.py` that extends `redact()` with additional masking for tailnet IPs, tailnet hostnames, invite URLs, and PIN values following PIN/pin within 3 tokens.
- `is_secret_file_read()` function in `tinyagentos/log_redaction.py` that identifies secret file reads (`.cred`, `.env`/`.env.*`, `config` under `.taos-team`) that should be dropped entirely by the transcript importer.

### Changed
- Fixed IPv4 redaction regex: second-octet `6[4-9]` instead of `6[0-9]` to exclude 100.60-100.63 (outside 100.64.0.0/10), added `\b` word boundary.
- Fixed PIN masking regex: allows up to 3 intervening tokens between `PIN`/`pin` and the 6-8 digit value, using `(?i)(PIN|pin)(?:\s+\S+){0,3}\s+\d{6,8}`.
- Fixed `is_secret_file_read()`: `config` under `.taos-team` now matches nested paths (e.g., `.taos-team/sub/config`), not just immediate children.

### Fixed
- Known values pass-through in `redact_for_archive()` now works when `known_values` argument is provided.