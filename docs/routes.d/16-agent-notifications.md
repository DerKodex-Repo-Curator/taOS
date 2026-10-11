# Agent notifications (`notifications_write` grant)

`POST /api/notifications` body: `title` (max 120 chars), `message` (max 1000 chars), `level` (`info`/`warning`), `source` (ignored on agent path), `data.project_id` (optional).

- Admits `POST`/`GET /api/notifications` for agent bearers; `GET` lists only the agent's own posts. Mark-read stays session-only.
- `POST`: JWT + grant + project via `check_agent_scope_for_project`; `GET`: JWT + grant
- Global grant posts to instance admin(s). Per-project grant posts to that project's owner only.
- `source` from grant. Store row: `agent:<canonical_id>`. `data.from_agent` stamped to canonical_id.
- `info`/`warning` only. `error` returns 400.
- Caps: `title` <= 120, `message` <= 1000, `data` <= 4 KB. Violations return 422.
- Rate limit: 10 posts per 10 minutes per canonical_id. Exceeding returns 429 `{"error": "rate_limited", "retry_after": N}`.
- Delivery through `store.add`: SSE and web-push fire.
- Human path unchanged: `_require_admin` gate, any valid level, source from body.

---

# Notification history (session-only)

## GET /api/notifications/history

Searchable, filterable notification history with keyset paging.

Query parameters:
- `q` — search `title` OR `message` (literal `%` and `_` via `ESCAPE '\'`)
- `source` — repeatable, filter by source
- `level` — repeatable, filter by level (`info`, `success`, `warning`, `error`)
- `since` — epoch seconds, lower bound on `timestamp`
- `until` — epoch seconds, upper bound on `timestamp`
- `state` — `all` | `unread` | `read` | `archived` | `active` (default `all`)
- `before` — opaque cursor `"<timestamp>:<id>"` for keyset paging (strictly older)
- `limit` — page size 1..200 (default 50)

Returns: `{"items": [...], "next_before": "<cursor>" or null}`

Each item includes `archived` bool alongside the standard notification fields.

User scoping: own notifications + broadcasts (`user_id IS NULL`). Broadcast read/archive state is per-user via `notification_user_state`.

## GET /api/notifications/history/sources

Distinct notification sources visible to the calling user, sorted.

Returns: `{"sources": [...]}`

## GET /api/notifications/archived (legacy)

History view: dismissed notifications, newest first (nothing deleted). Returns a flat list (newest 50 only, no filters, no paging). The UI is migrating to `/history`.
