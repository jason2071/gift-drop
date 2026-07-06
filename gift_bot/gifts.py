"""Gift catalogue.

A *gift* is a pair of PNG templates in the assets directory:

* ``<name>.png``       -- the gift icon as it appears in the gift tray, and
* ``<name>-send.png``  -- the hover popup that carries the Send button.

Drop a new pair into the assets dir and it shows up automatically; no code
change required.

When running from source, the assets dir is ``<repo>/assets``. In a packaged
(PyInstaller) build the source tree is read-only, so the writable assets dir
moves to ``%APPDATA%/GiftDrop/assets`` and :func:`seed` copies the bundled
defaults there on first run.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent


def _bundled_assets_dir() -> Path:
    """Read-only assets shipped with the app."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:  # PyInstaller onefile/onedir
        return Path(meipass) / "assets"
    if getattr(sys, "frozen", False):  # cx_Freeze / other: assets sit next to the exe
        return Path(sys.executable).resolve().parent / "assets"
    return _PKG_DIR.parent / "assets"


def _writable_assets_dir() -> Path:
    """Where user gifts live. Frozen builds use a per-user, writable location."""
    if getattr(sys, "frozen", False):
        root = os.environ.get("APPDATA") or str(Path.home())
        return Path(root) / "GiftDrop" / "assets"
    return _PKG_DIR.parent / "assets"


BASE_DIR = _PKG_DIR
ASSETS_DIR = _writable_assets_dir()
BUNDLED_ASSETS_DIR = _bundled_assets_dir()

_POPUP_SUFFIX = "-send"


def seed() -> None:
    """Copy bundled default assets into the writable dir on first run. No-op
    when source and writable dirs are the same (running from source)."""
    if ASSETS_DIR == BUNDLED_ASSETS_DIR:
        return
    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for src in BUNDLED_ASSETS_DIR.glob("*.png"):
            dst = ASSETS_DIR / src.name
            if not dst.exists():
                shutil.copyfile(src, dst)
    except OSError:
        pass


@dataclass(frozen=True)
class Gift:
    name: str          # human-friendly label, e.g. "Love You"
    icon_path: Path    # <name>.png
    popup_path: Path   # <name>-send.png


def _pretty(stem: str) -> str:
    return stem.replace("-", " ").replace("_", " ").title()


def discover(assets_dir: Path = ASSETS_DIR) -> list[Gift]:
    """Return all gifts found in ``assets_dir``, sorted by name."""
    gifts: list[Gift] = []
    for icon in sorted(assets_dir.glob("*.png")):
        if icon.stem.endswith(_POPUP_SUFFIX):
            continue  # this is a popup, not an icon
        popup = assets_dir / f"{icon.stem}{_POPUP_SUFFIX}.png"
        if popup.exists():
            gifts.append(Gift(_pretty(icon.stem), icon, popup))
    return gifts


def default() -> Gift | None:
    """First available gift, or ``None`` if the catalogue is empty."""
    gifts = discover()
    return gifts[0] if gifts else None
