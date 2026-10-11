```text
FFFF.                                                                    [100%]
=================================== FAILURES ===================================
___________________ test_list_channels_returns_last_preview ____________________

client = <httpx.AsyncClient object at 0x7a706d2d6f90>

    @pytest.mark.asyncio
    async def test_list_channels_returns_last_preview(client):
        """GET /api/chat/channels includes last_preview with the latest message text."""
        ch = await _create_channel(client, "preview-ch")
    
        # Send two messages
        await _send_message(client, ch["id"], "user-1", "First message")
        msg2 = await _send_message(client, ch["id"], "user-2", "Second message")
    
        # GET channels
        resp = await client.get("/api/chat/channels")
        assert resp.status_code == 200
        channels = resp.json()["channels"]
    
        # Find our channel
        target = next(c for c in channels if c["id"] == ch["id"])
>       assert "last_preview" in target, "Channel should have last_preview key"
E       AssertionError: Channel should have last_preview key
E       assert 'last_preview' in {'id': '12d7b1774b10', 'name': 'preview-ch', 'type': 'text', 'description': '', ...}

tests/test_chat_last_preview.py:45: AssertionError
------------------------------ Captured log setup ------------------------------
WARNING  tinyagentos.containers.backend:backend.py:320 No container backend detected (Incus / Docker / Podman / Apple / Native). Cluster features and worker containers will be disabled. Install one (e.g. 'sudo apt install incus' on Ubuntu/Debian, 'sudo dnf install incus' on Fedora) and restart taOS.
_______________ test_last_preview_falls_back_when_newest_deleted _______________

client = <httpx.AsyncClient object at 0x7a7062043e50>

    @pytest.mark.asyncio
    async def test_last_preview_falls_back_when_newest_deleted(client):
        """Deleted newest message -> preview falls back to the previous one."""
        ch = await _create_channel(client, "fallback-ch")
    
        msg1 = await _send_message(client, ch["id"], "user-1", "First message")
        msg2 = await _send_message(client, ch["id"], "user-2", "Second message")
    
        # Soft-delete the newest message
        msg_store = client._transport.app.state.chat_messages
        await msg_store.soft_delete_message(msg2["id"])
    
        resp = await client.get("/api/chat/channels")
        assert resp.status_code == 200
        channels = resp.json()["channels"]
        target = next(c for c in channels if c["id"] == ch["id"])
    
>       assert target["last_preview"] == "First message", "Preview should fall back to previous non-deleted message"
               ^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'last_preview'

tests/test_chat_last_preview.py:67: KeyError
------------------------------ Captured log setup ------------------------------
WARNING  tinyagentos.containers.backend:backend.py:320 No container backend detected (Incus / Docker / Podman / Apple / Native). Cluster features and worker containers will be disabled. Install one (e.g. 'sudo apt install incus' on Ubuntu/Debian, 'sudo dnf install incus' on Fedora) and restart taOS.
___________________ test_last_preview_ignores_thread_replies ___________________

client = <httpx.AsyncClient object at 0x7a7060d71220>

    @pytest.mark.asyncio
    async def test_last_preview_ignores_thread_replies(client):
        """Thread reply (thread_id set) newer than top-level -> preview is top-level message."""
        ch = await _create_channel(client, "thread-ch")
    
        # Send top-level message
        parent = await _send_message(client, ch["id"], "user-1", "Parent message")
        # Send thread reply (newer)
        await _send_message(client, ch["id"], "user-2", "Thread reply", thread_id=parent["id"])
    
        resp = await client.get("/api/chat/channels")
        assert resp.status_code == 200
        channels = resp.json()["channels"]
        target = next(c for c in channels if c["id"] == ch["id"])
    
>       assert target["last_preview"] == "Parent message", "Preview should be top-level message, not thread reply"
               ^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'last_preview'

tests/test_chat_last_preview.py:86: KeyError
------------------------------ Captured log setup ------------------------------
WARNING  tinyagentos.containers.backend:backend.py:320 No container backend detected (Incus / Docker / Podman / Apple / Native). Cluster features and worker containers will be disabled. Install one (e.g. 'sudo apt install incus' on Ubuntu/Debian, 'sudo dnf install incus' on Fedora) and restart taOS.
___________________ test_last_preview_truncates_at_120_chars ___________________

client = <httpx.AsyncClient object at 0x7a7053944bb0>

    @pytest.mark.asyncio
    async def test_last_preview_truncates_at_120_chars(client):
        """A 300-char message -> preview length is 120."""
        ch = await _create_channel(client, "truncate-ch")
    
        long_content = "x" * 300
        await _send_message(client, ch["id"], "user-1", long_content)
    
        resp = await client.get("/api/chat/channels")
        assert resp.status_code == 200
        channels = resp.json()["channels"]
        target = next(c for c in channels if c["id"] == ch["id"])
    
>       assert len(target["last_preview"]) == 120, "Preview should be truncated to 120 chars"
                   ^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'last_preview'

tests/test_chat_last_preview.py:103: KeyError
------------------------------ Captured log setup ------------------------------
WARNING  tinyagentos.containers.backend:backend.py:320 No container backend detected (Incus / Docker / Podman / Apple / Native). Cluster features and worker containers will be disabled. Install one (e.g. 'sudo apt install incus' on Ubuntu/Debian, 'sudo dnf install incus' on Fedora) and restart taOS.
=========================== short test summary info ============================
FAILED tests/test_chat_last_preview.py::test_list_channels_returns_last_preview
FAILED tests/test_chat_last_preview.py::test_last_preview_falls_back_when_newest_deleted
FAILED tests/test_chat_last_preview.py::test_last_preview_ignores_thread_replies
FAILED tests/test_chat_last_preview.py::test_last_preview_truncates_at_120_chars
4 failed, 1 passed in 24.67s
```