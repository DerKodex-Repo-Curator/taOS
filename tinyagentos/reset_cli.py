"""``taos reset --onboarding`` -- offline re-arm of first-run onboarding.

Removes ONLY the identity + onboarding state so the next page load shows
onboarding again. Models, installed apps, agents and every store not listed in
``ONBOARDING_FILES`` / ``ONBOARDING_DBS`` are kept.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# Account files (AuthManager): users, legacy password, sessions.
ONBOARDING_FILES = (".auth_user.json", ".auth_password", ".auth_sessions")
# Onboarding-adjacent SQLite stores (plus their -wal/-shm sidecars).
ONBOARDING_DBS = ("auth_requests.db", "password_resets.db")
_SIDECARS = ("", "-wal", "-shm")


def _controller_port(data_dir: Path) -> int:
    """The port the controller binds, mirroring ``tinyagentos.__main__``:
    ``TAOS_PORT`` (or a bare ``TAOS_HOST``) wins, else ``server.port`` from the
    data dir's config.yaml, else 6969. Read-only: ``load_config`` may rewrite
    config.yaml, which a safety probe must never do."""
    env_port = os.environ.get("TAOS_PORT")
    if env_port or os.environ.get("TAOS_HOST"):
        return int(env_port) if env_port else 6969
    try:
        import yaml

        data = yaml.safe_load((data_dir / "config.yaml").read_text())
        return int((data or {}).get("server", {}).get("port", 6969))
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError):
        return 6969


def _backup_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def controller_is_up(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _targets(data_dir: Path) -> list[Path]:
    names = list(ONBOARDING_FILES) + [d + s for d in ONBOARDING_DBS for s in _SIDECARS]
    return [data_dir / n for n in names if (data_dir / n).exists()]


def _setup_pref_row(data_dir: Path):
    db = data_dir / "desktop.db"
    if not db.exists():
        return None
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT value FROM desktop_settings WHERE user_id = 'user' AND key = 'pref:setup'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


def reset_cli(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="taos reset",
        description="Re-arm first-run onboarding (offline). Keeps models, apps and agents.",
    )
    parser.add_argument("--onboarding", action="store_true", required=True,
                        help="Clear accounts, sessions and the setup checklist state only.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    parser.add_argument("--no-backup", action="store_true", help="Do not back up what is removed.")
    parser.add_argument("--force", action="store_true", help="Run even if the controller is up.")
    parser.add_argument("--data-dir", help="Data directory (default: TAOS_DATA_DIR, else <project>/data).")
    ns = parser.parse_args(argv)

    from tinyagentos.app import resolve_data_dir

    override = ns.data_dir or os.environ.get("TAOS_DATA_DIR")
    data_dir = resolve_data_dir(Path(override) if override else None)

    port = _controller_port(data_dir)
    if not ns.force and controller_is_up(port):
        print(f"The taOS controller is running on port {port}. Stop it first "
              "(sudo systemctl stop tinyagentos) or pass --force.", file=sys.stderr)
        return 1

    targets = _targets(data_dir)
    pref = _setup_pref_row(data_dir)
    print("This will remove:")
    for t in targets:
        print(f"  {t}")
    if pref is not None:
        print(f"  setup checklist state in {data_dir / 'desktop.db'}")
    if not targets and pref is None:
        print("Nothing to reset.")
        return 0
    if not ns.yes and input("Type 'yes' to continue: ").strip().lower() != "yes":
        print("Aborted; nothing was removed.")
        return 1

    backup_dir = None
    if not ns.no_backup:
        base = data_dir / "backups" / f"reset-{_backup_stamp()}"
        backup_dir = base
        for n in range(1, 1000):
            try:
                backup_dir.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                backup_dir = base.with_name(f"{base.name}-{n}")
        else:
            raise FileExistsError(f"no free backup directory next to {base}")
        for t in targets:
            shutil.copy2(t, backup_dir / t.name)
        if pref is not None:
            (backup_dir / "setup_pref.json").write_text(json.dumps({"value": pref[0]}))
    for t in targets:
        t.unlink()
    if pref is not None:
        con = sqlite3.connect(data_dir / "desktop.db")
        try:
            con.execute("DELETE FROM desktop_settings WHERE user_id = 'user' AND key = 'pref:setup'")
            con.commit()
        finally:
            con.close()
    if backup_dir is not None:
        print(f"Backup written to {backup_dir}")
    print("Onboarding reset. Start the controller and reload the page.")
    return 0