### Added

- taOS Agent action gate: `/api/taos-agent/actions` stores a pending action, the signed-in user confirms or declines it, and execute refuses (409) anything not confirmed and runs a confirmed action once; a per-kind `ask|auto` policy in the `taos_agent` preferences lets `auto` skip the confirm card with `confirmed_by=auto`.
