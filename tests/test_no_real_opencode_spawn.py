"""Test that no real opencode spawn can happen during tests.

This test ensures the autouse fixture in conftest.py makes a real opencode
spawn impossible by forcing resolve_opencode_binary() to return a non-existent
path and setting TAOS_OPENCODE_BIN to a non-existent path.
"""
from __future__ import annotations

import pytest

from tinyagentos.opencode_runtime import (
    OpenCodeServer,
    OpenCodeServerConfig,
    OpenCodeBinaryNotFoundError,
)


def _make_server_cfg(tmp_path, port: int = 5900) -> OpenCodeServerConfig:
    """Mirror the config construction from test_opencode_runtime.py."""
    return OpenCodeServerConfig(
        home=str(tmp_path),
        port=port,
        server_password=None,
        litellm_base_url="http://127.0.0.1:4000/v1",
        litellm_key="sk-test",
        model_ids=["gpt-4o"],
    )


@pytest.mark.asyncio
async def test_no_real_opencode_spawn_raises_binary_not_found(tmp_path):
    """Building OpenCodeServer with default binary and calling ensure_running
    must raise OpenCodeBinaryNotFoundError, and no process must be started.
    """
    cfg = _make_server_cfg(tmp_path)
    server = OpenCodeServer(cfg)

    # With the autouse fixture active, resolve_opencode_binary() returns a
    # non-existent path and TAOS_OPENCODE_BIN points to a non-existent path,
    # so the spawn attempt hits FileNotFoundError which ensure_running maps to
    # OpenCodeBinaryNotFoundError.
    with pytest.raises(OpenCodeBinaryNotFoundError):
        await server.ensure_running(deadline_s=0.05, poll_s=0.01)

    # Verify no process was started
    assert not server.is_running()
