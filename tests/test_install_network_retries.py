from __future__ import annotations

import os
import subprocess
from pathlib import Path
from textwrap import dedent

INSTALL = Path("scripts/install-server.sh")


def test_pip_install_has_retries():
    text = INSTALL.read_text()
    pip_lines = [line for line in text.splitlines() if "./.venv/bin/pip install" in line]
    assert len(pip_lines) >= 2, f"expected >=2 pip install lines, got {len(pip_lines)}"
    for line in pip_lines:
        assert "--retries" in line, f"missing --retries in: {line}"


def test_key_download_curls_have_retries():
    text = INSTALL.read_text()
    lines = text.splitlines()

    # NodeSource deb key curl (line ~296)
    deb_curl = lines[295] if len(lines) > 295 else ""
    assert "--retry" in deb_curl or "${CURL_RETRY[@]}" in deb_curl, f"missing retries in deb curl: {deb_curl}"

    # NodeSource rpm key curl
    rpm_curl = lines[329] if len(lines) > 329 else ""
    assert "--retry" in rpm_curl or "${CURL_RETRY[@]}" in rpm_curl, f"missing retries in rpm curl: {rpm_curl}"

    # Zabbly key curl
    zabbly_curl = lines[1024] if len(lines) > 1024 else ""
    assert "--retry" in zabbly_curl or "${CURL_RETRY[@]}" in zabbly_curl, f"missing retries in zabbly curl: {zabbly_curl}"

    # Docker key curl
    docker_curl = lines[1370] if len(lines) > 1370 else ""
    assert "--retry" in docker_curl or "${CURL_RETRY[@]}" in docker_curl, f"missing retries in docker curl: {docker_curl}"
