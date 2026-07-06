"""Gift catalogue.

A *gift* is a pair of PNG templates in the assets directory:

* ``<name>.png``       -- the gift icon as it appears in the gift tray, and
* ``<name>-send.png``  -- the hover popup that carries the Send button.

Drop a new pair into ``assets/`` and it shows up in the picker automatically;
no code change required.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR.parent / "assets"

_POPUP_SUFFIX = "-send"


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
