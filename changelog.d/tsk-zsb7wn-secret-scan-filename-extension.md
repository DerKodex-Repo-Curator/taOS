### Fixed
- Extended secret scan to refuse files with extensions `.pem`, `.key` and filenames starting with `id_rsa` or `id_ed25519` when they contain environment variable assignments.