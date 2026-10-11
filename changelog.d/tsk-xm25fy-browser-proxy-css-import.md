### Fixed

- Fixed CSS url() regex backtracking vulnerability. Rewrote `_CSS_URL_RE` to prevent overlapping adjacent matches and nested quantifiers. Stylesheets over 512 KiB are refused with a 502 instead of being served with unproxied references, and `text/css` is matched case-insensitively.
