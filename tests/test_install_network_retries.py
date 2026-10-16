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

    # NodeSource deb key curl
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


def _write_curl(path: Path, help_output: str) -> Path:
    path.mkdir(exist_ok=True)
    curl = path / "curl"
    content = dedent(
        f"""
        #!/bin/sh
        if [ "$1" = "--help" ] && [ "$2" = "all" ]; then
            printf '%s\\n' "{help_output}"
            exit 0
        fi
        for arg in "$@"; do
            if [ "$arg" = "--retry-all-errors" ]; then
                exit 2
            fi
        done
        exit 0
        """
    )
    curl.write_text(content)
    curl.chmod(0o755)
    return path


def test_curl_retry_without_retry_all_errors(tmp_path):
    bin_path = _write_curl(tmp_path, "curl 7.68.0\nOptions:\n  --retry <num>")
    env = os.environ.copy()
    env["PATH"] = f"{bin_path}:{env['PATH']}"
    result = subprocess.run(
        ["/bin/bash", "-c", "CURL_RETRY=(--retry 5 --retry-delay 3 --connect-timeout 15 --max-time 60); if curl --help all 2>/dev/null | grep -q -- '--retry-all-errors'; then CURL_RETRY+=(--retry-all-errors); fi; echo \"${CURL_RETRY[*]}\""],
        cwd=str(Path.cwd()),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    curl_retry = result.stdout.strip().split()
    assert "--retry-all-errors" not in curl_retry


def test_curl_retry_with_retry_all_errors(tmp_path):
    bin_path = _write_curl(tmp_path, "curl 7.88.1\nOptions:\n  --retry <num>\n  --retry-all-errors")
    env = os.environ.copy()
    env["PATH"] = f"{bin_path}:{env['PATH']}"
    result = subprocess.run(
        ["/bin/bash", "-c", "CURL_RETRY=(--retry 5 --retry-delay 3 --connect-timeout 15 --max-time 60); if curl --help all 2>/dev/null | grep -q -- '--retry-all-errors'; then CURL_RETRY+=(--retry-all-errors); fi; echo \"${CURL_RETRY[*]}\""],
        cwd=str(Path.cwd()),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    curl_retry = result.stdout.strip().split()
    assert "--retry-all-errors" in curl_retry
