"""Foreground handling and real mouse input.

The gift's Send button only appears on a genuine hover, and clicking an occluded
window with synthetic messages is unreliable for Chromium-based UIs. So the bot
brings the target window to the foreground and drives the real cursor.
"""

from __future__ import annotations

import time

import pyautogui
import win32api
import win32con
import win32gui
import win32process

# Slamming the cursor into a screen corner aborts pyautogui as a safety hatch.
pyautogui.FAILSAFE = True
# We manage our own pacing; avoid pyautogui's per-call sleep.
pyautogui.PAUSE = 0.0


def to_front(hwnd: int, settle: float = 0.25) -> bool:
    """Bring ``hwnd`` to the foreground. Return ``True`` on success.

    Uses the ``AttachThreadInput`` workaround for the common case where Windows
    refuses ``SetForegroundWindow`` because our thread does not own the focus.
    """
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    fg = win32gui.GetForegroundWindow()
    if fg == hwnd:
        return True

    our_tid = win32api.GetCurrentThreadId()
    fg_tid, _ = win32process.GetWindowThreadProcessId(fg) if fg else (0, 0)
    target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)

    attached: list[int] = []
    try:
        for tid in (fg_tid, target_tid):
            if tid and tid != our_tid:
                try:
                    win32process.AttachThreadInput(our_tid, tid, True)
                    attached.append(tid)
                except Exception:
                    pass
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            return False
    finally:
        for tid in attached:
            try:
                win32process.AttachThreadInput(our_tid, tid, False)
            except Exception:
                pass

    time.sleep(settle)  # let the window repaint / hover states settle
    return win32gui.GetForegroundWindow() == hwnd


def hover(x: int, y: int, duration: float = 0.12) -> None:
    """Move the cursor to ``(x, y)`` to trigger a hover state."""
    pyautogui.moveTo(x, y, duration=duration)


def click(x: int, y: int, duration: float = 0.1) -> None:
    """Move to ``(x, y)`` and left-click."""
    pyautogui.moveTo(x, y, duration=duration)
    pyautogui.click()
