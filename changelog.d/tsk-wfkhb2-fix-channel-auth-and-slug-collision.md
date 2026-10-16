### Fixed
- Add channel membership checks to `/api/agents/self/chat/reply` to prevent registry agents from posting into channels they're not members of
- Add slug collision detection to prevent multiple registry agents from sharing the same session slug
- Update `_resolve_slug` to check for other active registry agents with the same slug
- Update test suite with comprehensive tests for channel membership validation and slug collision detection