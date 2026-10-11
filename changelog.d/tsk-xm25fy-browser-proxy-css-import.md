### Fixed

- Fixed CSS url() regex backtracking vulnerability. Rewrote `_CSS_URL_RE` to prevent overlapping adjacent matches and nested quantifiers. Added 512 KiB limit for CSS rewriting to skip processing oversized stylesheets.
