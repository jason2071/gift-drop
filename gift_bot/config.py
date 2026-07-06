"""Persist the user's last-used settings between runs.

Stored as JSON in a per-user location (``%APPDATA%/GiftDrop`` on Windows, an
XDG/dotfile fallback elsewhere) so it survives reinstalls and never lands in the
repo. All I/O is best-effort: a missing or corrupt file just yields defaults,
and write failures are swallowed -- settings are a convenience, not critical.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "GiftDrop"


def _config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


CONFIG_PATH = _config_dir() / "settings.json"


def load() -> dict:
    """Return the saved settings, or an empty dict if none/unreadable."""
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    """Write ``data`` as JSON. Silently no-ops on any I/O error."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass
