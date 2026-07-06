"""Send-gift orchestration: detect -> hover -> confirm popup -> click Send.

Detection works on a captured bitmap (occlusion-proof). Clicking uses the real
cursor after bringing the window forward, because the Send button is revealed by
a genuine hover.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from . import capture
from . import clicker
from . import matcher

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR.parent / "assets"
ICON_TEMPLATE_PATH = ASSETS_DIR / "love-you.png"
POPUP_TEMPLATE_PATH = ASSETS_DIR / "love-you-send.png"
# Optional: a user-cropped Send button for a more exact click.
SEND_BUTTON_TEMPLATE_PATH = ASSETS_DIR / "send-button.png"

# Send label sits in the bottom band of the 106x112 popup; center-x, ~86% down.
SEND_OFFSET_X_RATIO = 0.5
SEND_OFFSET_Y_RATIO = 0.86

Logger = Callable[[str], None]


class Result(str, Enum):
    SENT = "sent"
    NOT_FOUND = "icon-not-found"
    POPUP_NOT_FOUND = "popup-not-found"
    FOREGROUND_FAILED = "foreground-failed"


@dataclass
class Templates:
    icon: "matcher.np.ndarray"
    popup: "matcher.np.ndarray"
    send_button: "matcher.np.ndarray | None"

    @classmethod
    def load(cls) -> "Templates":
        icon = matcher.load_template(ICON_TEMPLATE_PATH)
        popup = matcher.load_template(POPUP_TEMPLATE_PATH)
        send_button = (
            matcher.load_template(SEND_BUTTON_TEMPLATE_PATH)
            if SEND_BUTTON_TEMPLATE_PATH.exists()
            else None
        )
        return cls(icon=icon, popup=popup, send_button=send_button)


def _detect(hwnd: int, template, threshold: float, retries: int, log: Logger):
    """Capture and match up to ``retries`` times; return (Match, origin) or (None, None)."""
    for attempt in range(1, retries + 1):
        image, origin = capture.capture_window(hwnd)
        match = matcher.find(image, template, threshold=threshold)
        if match is not None:
            log(f"  found (attempt {attempt}/{retries}, score {match.score:.2f})")
            return match, origin
        log(f"  not found (attempt {attempt}/{retries}, best below {threshold:.2f})")
        time.sleep(0.25)
    return None, None


def send_once(
    hwnd: int,
    templates: Templates,
    threshold: float,
    retries: int,
    log: Logger,
) -> Result:
    """Perform a single detect -> hover -> confirm -> click Send cycle."""
    # 1. Detect the gift icon (works while occluded).
    icon, origin = _detect(hwnd, templates.icon, threshold, retries, log)
    if icon is None:
        return Result.NOT_FOUND
    left, top = origin
    icon_screen = (left + icon.cx, top + icon.cy)

    # 2. Bring the window forward and hover the icon to reveal the popup.
    if not clicker.to_front(hwnd):
        log("  WARN: could not bring window to foreground")
        return Result.FOREGROUND_FAILED
    clicker.hover(*icon_screen)
    time.sleep(0.4)  # popup reveal animation

    # 3. Confirm the popup appeared (re-capture; window is now on top).
    popup, origin = _detect(hwnd, templates.popup, threshold, retries, log)
    if popup is None:
        return Result.POPUP_NOT_FOUND
    left, top = origin

    # 4. Compute the Send click point and click it.
    if templates.send_button is not None:
        image, origin = capture.capture_window(hwnd)
        btn = matcher.find(image, templates.send_button, threshold=threshold)
        if btn is not None:
            left, top = origin
            send_screen = (left + btn.cx, top + btn.cy)
        else:
            send_screen = _send_point_from_popup(left, top, popup)
    else:
        send_screen = _send_point_from_popup(left, top, popup)

    clicker.click(*send_screen)
    log(f"  clicked Send at {send_screen}")
    return Result.SENT


def _send_point_from_popup(left: int, top: int, popup: "matcher.Match") -> tuple[int, int]:
    x = left + popup.left + int(popup.w * SEND_OFFSET_X_RATIO)
    y = top + popup.top + int(popup.h * SEND_OFFSET_Y_RATIO)
    return x, y


def run(
    hwnd: int,
    count: int,
    interval: float,
    retries: int,
    threshold: float,
    stop_event: threading.Event,
    log: Logger,
) -> None:
    """Send the gift ``count`` times, ``interval`` seconds apart.

    Stops early if a detection fails (satisfies "retry N, else stop") or if
    ``stop_event`` is set.
    """
    try:
        templates = Templates.load()
    except FileNotFoundError as exc:
        log(f"ERROR: {exc}")
        return

    if templates.send_button is not None:
        log("Using send-button.png for precise Send clicks.")

    sent = 0
    for i in range(1, count + 1):
        if stop_event.is_set():
            log("Stopped by user.")
            break
        log(f"[{i}/{count}] sending...")
        result = send_once(hwnd, templates, threshold, retries, log)

        if result is Result.SENT:
            sent += 1
        else:
            log(f"Stopping: {result.value} after {retries} retries.")
            break

        if i < count and not stop_event.is_set():
            # Interruptible sleep so Stop is responsive during the interval.
            slept = 0.0
            while slept < interval and not stop_event.is_set():
                time.sleep(min(0.1, interval - slept))
                slept += 0.1

    log(f"Done. Gifts sent: {sent}/{count}.")
