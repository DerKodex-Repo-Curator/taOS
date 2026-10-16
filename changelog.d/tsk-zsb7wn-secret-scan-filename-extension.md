### Fixed
- Extended secret scan to refuse files with extensions `.pem`, `.key` and filenames starting with `id_rsa` or `id_ed25519` when they contain environment variable assignments.
- The secret scan now catches a sentence-final IPv4 address, `*.env` and `.envrc` files, PGP private key blocks and JWTs.
- A write without a data dir is refused instead of skipping the data-dir check.
- `upstream` must be a plain `owner/repo` (validated with regex).
- `push_branch` checks that it is writing to the user's fork of upstream.