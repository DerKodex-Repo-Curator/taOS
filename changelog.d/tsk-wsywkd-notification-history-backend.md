### Added
- `GET /api/notifications/history` — searchable, filterable notification history with keyset paging (q, source, level, since, until, state, before, limit). Returns `{items, next_before}`. Server-side search with user scoping (own + broadcasts, per-user broadcast read/archive state).
- `GET /api/notifications/history/sources` — distinct notification sources visible to the user, sorted.
- `NotificationStore.search()` and `NotificationStore.history_sources()` backend methods.