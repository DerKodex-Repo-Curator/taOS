### Added

- `AgentTraceStore.import_envelopes()` bulk-imports pre-built v1 envelopes into the bucket DBs by `created_at` bucket, using `INSERT OR IGNORE` on `id` so re-runs are idempotent. Historical import now lands in the bucket DB instead of the sealed-bucket `.late.jsonl` fallback, so `list()` search over months of history is no longer degraded. Does not seal/unseal buckets or touch the live registry bucket.
- `AgentTraceStore.search_text(query, *, since, until, limit)` adds FTS5 text search across the agent's buckets in a time range, powered by a new `trace_events_fts` virtual table (`id UNINDEXED, text`) populated by both `record()` and `import_envelopes()`.

### Fixed

- `search_text()` now accepts plain-text queries (not FTS5 syntax); card IDs like `tsk-abc123` and apostrophes like `it's` no longer raise FTS5 syntax errors.
- `import_envelopes()` now pre-checks sealed (read-only) buckets: re-importing existing ids reports them as duplicates without raising "readonly database", and importing new envelopes into a sealed bucket raises `ValueError` before any write occurs (no partial commit across buckets).