# What `GET /api/decisions/agent` returns (grant scoping)

<!-- Route module `tinyagentos/routes/decisions.py`, scope `decisions_write`. Lists the decisions THIS agent raised; the store layer enforces the `from_agent` binding, so there is no cross-agent leakage regardless of grants -->

## Grant shaping which decisions come back

- **Global (null-project) grant**: null-project decisions, plus granted projects
- **Exactly one granted scope**: those decisions, filtered in the store query
- **Two or more scopes**: fetched by agent, filtered in Python

### Limit interaction

- The single-scope path pushes the project filter into the store query, so the 500 limit applies AFTER scoping (issue #2194)
- The two-or-more-scope path still fetches up to 500 rows then filters in Python, so an agent with several grants and more than 500 decisions in total can still lose allowed-project rows to the limit (same shape as the original bug, narrower blast radius)
