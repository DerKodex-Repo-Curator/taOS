from __future__ import annotations

from pathlib import Path

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

    # NodeSource deb key curl around line 290-292
    deb_curl = lines[289] if len(lines) > 289 else ""
    assert "--retry" in deb_curl, f"missing --retry in deb curl: {deb_curl}"

    # NodeSource rpm key curl around line 324-326
    rpm_curl = lines[323] if len(lines) > 323 else ""
    assert "--retry" in rpm_curl, f"missing --retry in rpm curl: {rpm_curl}"

    # Zabbly key curl around line 1019
    zabbly_curl = lines[1018] if len(lines) > 1018 else ""
    assert "--retry" in zabbly_curl, f"missing --retry in zabbly curl: {zabbly_curl}"

    # Docker key curl around line 1365
    docker_curl = lines[1364] if len(lines) > 1364 else ""
    assert "--retry" in docker_curl, f"missing --retry in docker curl: {docker_curl}"
