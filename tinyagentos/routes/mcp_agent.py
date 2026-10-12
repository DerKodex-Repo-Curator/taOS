from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_MCP_SERVER: Any = None
_MCP_TRANSPORT: Any = None


def _mcp_available() -> bool:
    """Check if mcp extra is installed at runtime."""
    try:
        from mcp.server import MCPServer
        from mcp.server.streamable_http import StreamableHTTPServerTransport
        return True
    except ImportError:
        return False


async def _get_mcp_server(request: Request = None):
    """Lazily create and return the MCP server instance."""
    global _MCP_SERVER, _MCP_TRANSPORT
    if _MCP_SERVER is not None:
        return _MCP_SERVER

    if not _mcp_available():
        raise HTTPException(
            status_code=503,
            detail={"error": "mcp extra not installed"},
        )

    from mcp.server import MCPServer
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    _MCP_SERVER = MCPServer(name="taos-agent-mcp")
    _MCP_TRANSPORT = StreamableHTTPServerTransport(
        mcp_session_id=None,
        is_json_response_enabled=False,
        stateless_http=True,
    )

    @asynccontextmanager
    async def lifespan(_server: MCPServer):
        async with _MCP_TRANSPORT.connect() as (read_stream, write_stream):
            yield

    _MCP_SERVER.settings.lifespan = lifespan

    @_MCP_SERVER.tool(description="Read messages from the A2A bus inbox since a cursor timestamp.")
    async def inbox(since: float = 0.0) -> dict:
        from tinyagentos.agent_token_auth import check_agent_scope
        from tinyagentos.routes.a2a_bus import _bus_url
        import httpx

        # Get request from context
        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        caller = await check_agent_scope(request, "a2a_receive")
        if caller is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        bus = _bus_url()
        try:
            token = request.headers.get("Authorization", "").split(" ", 1)[1]
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{bus}/a2a/messages",
                    params={"since": since, "limit": 500},
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("A2A bus inbox fetch failed: %s", exc)
            return {"messages": [], "available": False}

        messages = data.get("messages", []) if isinstance(data, dict) else []
        return {"messages": messages, "available": True}

    @_MCP_SERVER.tool(description="Send a message to an A2A bus thread as the authenticated agent.")
    async def send(thread: str, text: str, reply_to: int | None = None) -> dict:
        from tinyagentos.agent_token_auth import check_agent_scope
        from tinyagentos.routes.a2a_bus import _bus_url, _credential_may_cross
        import httpx

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        caller = await check_agent_scope(request, "a2a_send")
        if caller is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        bus = _bus_url()
        payload = {
            "from": caller,
            "thread": thread.strip(),
            "body": text.strip(),
        }
        if reply_to is not None:
            payload["reply_to"] = reply_to

        headers = {}
        token = request.headers.get("Authorization", "").split(" ", 1)[1]
        if _credential_may_cross(bus):
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{bus}/a2a/send",
                    json=payload,
                    headers=headers or None,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("A2A bus send failed: %s", exc)
            raise HTTPException(status_code=502, detail="a2a bus unavailable")

        return {"ok": True, "message": data}

    @_MCP_SERVER.tool(description="List all tasks on the project kanban board.")
    async def board() -> dict:
        from tinyagentos.agent_token_auth import check_agent_project_grants

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        canonical_id, grants = await check_agent_project_grants(request, "project_tasks")
        if canonical_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        if not grants:
            raise HTTPException(status_code=403, detail="no project_tasks grants")

        store = request.app.state.project_task_store

        items = []
        for project_id in grants:
            tasks = await store.list_tasks(project_id=project_id)
            project = await request.app.state.project_store.get_project(project_id)
            items.append({
                "project_id": project_id,
                "name": project.get("name") if project else None,
                "slug": project.get("slug") if project else None,
                "tasks": tasks,
            })

        return {"items": items}

    @_MCP_SERVER.tool(description="List ready (open, unclaimed, unblocked) tasks on the project.")
    async def ready(limit: int = 50) -> dict:
        from tinyagentos.agent_token_auth import check_agent_project_grants

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        canonical_id, grants = await check_agent_project_grants(request, "project_tasks")
        if canonical_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")
        if not grants:
            raise HTTPException(status_code=403, detail="no project_tasks grants")

        store = request.app.state.project_task_store

        items = []
        for project_id in grants:
            tasks = await store.list_ready_tasks(project_id=project_id, limit=limit)
            project = await request.app.state.project_store.get_project(project_id)
            items.append({
                "project_id": project_id,
                "name": project.get("name") if project else None,
                "slug": project.get("slug") if project else None,
                "tasks": tasks,
            })

        return {"items": items}

    @_MCP_SERVER.tool(description="Claim a task as the authenticated agent.")
    async def claim(task_id: str) -> dict:
        from tinyagentos.agent_token_auth import check_agent_project_grants

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        canonical_id, grants = await check_agent_project_grants(request, "project_tasks")
        if canonical_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        store = request.app.state.project_task_store
        pstore = request.app.state.project_store

        for project_id in grants:
            task = await store.get_task(task_id)
            if task and task["project_id"] == project_id:
                ok = await store.claim_task(task_id, canonical_id)
                if ok:
                    await pstore.log_activity(project_id, canonical_id, "task.claimed", {"task_id": task_id})
                    return await store.get_task(task_id)
                held = await store.held_task(canonical_id)
                if held and held != task_id:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "agent already holds an active task", "held_task": held},
                    )
                raise HTTPException(status_code=409, detail="already claimed")

        raise HTTPException(status_code=404, detail="not found")

    @_MCP_SERVER.tool(description="Release a claimed task back to the ready pool.")
    async def release(task_id: str, strike: bool = True) -> dict:
        from tinyagentos.agent_token_auth import check_agent_project_grants

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        canonical_id, grants = await check_agent_project_grants(request, "project_tasks")
        if canonical_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        store = request.app.state.project_task_store
        pstore = request.app.state.project_store

        for project_id in grants:
            task = await store.get_task(task_id)
            if task and task["project_id"] == project_id:
                ok = await store.release_task(task_id, canonical_id, strike=strike)
                if ok:
                    return await store.get_task(task_id)
                raise HTTPException(status_code=409, detail="not claimed by releaser")

        raise HTTPException(status_code=404, detail="not found")

    @_MCP_SERVER.tool(description="Close a task as the authenticated agent.")
    async def close(task_id: str, reason: str | None = None) -> dict:
        from tinyagentos.agent_token_auth import check_agent_project_grants

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        canonical_id, grants = await check_agent_project_grants(request, "project_tasks")
        if canonical_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        store = request.app.state.project_task_store
        pstore = request.app.state.project_store

        for project_id in grants:
            task = await store.get_task(task_id)
            if task and task["project_id"] == project_id:
                project = await pstore.get_project(project_id)
                force = (
                    project.get("lead_member_id") == canonical_id
                    or project.get("user_id") == canonical_id
                )
                ok = await store.close_task(task_id, closed_by=canonical_id, reason=reason, force=force)
                if ok:
                    await pstore.log_activity(project_id, canonical_id, "task.closed", {"task_id": task_id})
                    return await store.get_task(task_id)
                if task.get("claimed_by") and task["claimed_by"] != canonical_id:
                    raise HTTPException(status_code=409, detail="not claimed by you")
                raise HTTPException(status_code=409, detail="cannot close")

        raise HTTPException(status_code=404, detail="not found")

    @_MCP_SERVER.tool(description="Add a comment to a task as the authenticated agent.")
    async def comment(task_id: str, text: str, replies_to: str | None = None) -> dict:
        from tinyagentos.agent_token_auth import check_agent_project_grants

        from mcp.server.context import get_request_context
        ctx = get_request_context()
        request = ctx.request_context.request if ctx else None
        if request is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        canonical_id, grants = await check_agent_project_grants(request, "project_tasks")
        if canonical_id is None:
            raise HTTPException(status_code=401, detail="invalid or missing token")

        store = request.app.state.project_task_store

        for project_id in grants:
            task = await store.get_task(task_id)
            if task and task["project_id"] == project_id:
                if not text or not text.strip():
                    raise HTTPException(status_code=422, detail="comment body must not be empty")
                try:
                    return await store.add_comment(
                        task_id=task_id,
                        author_id=canonical_id,
                        body=text,
                        replies_to_comment_id=replies_to,
                    )
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))

        raise HTTPException(status_code=404, detail="not found")

    return _MCP_SERVER


@router.api_route("/api/mcp/agent", methods=["GET", "POST", "DELETE"])
async def mcp_agent_endpoint(request: Request):
    """Streamable-HTTP MCP server endpoint for external agents.

    Auth: Authorization Bearer = agent registry JWT, verified via check_agent_scope.
    No session cookie path, no local-token path.
    """
    if not _mcp_available():
        return JSONResponse({"error": "mcp extra not installed"}, status_code=503)

    server = await _get_mcp_server(request)

    # Use the transport directly to handle the request
    scope = request.scope
    receive = request._receive
    send = request._send

    await _MCP_TRANSPORT.handle_request(scope, receive, send)