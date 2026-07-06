"""Window enumeration and occlusion-proof screen capture.

Uses the Win32 ``PrintWindow`` API with the ``PW_RENDERFULLCONTENT`` flag so a
window's contents can be captured even when it is covered by other windows.
This is what lets the bot locate the gift icon on an occluded target window.
"""

from __future__ import annotations

from PIL import Image
import win32con
import win32gui
import win32ui

# Undocumented PrintWindow flag: render the full window content (including
# DWM/Chromium-composited surfaces) even when occluded. Supported Win 8.1+.
PW_RENDERFULLCONTENT = 0x00000002


def list_windows(skip_titles: tuple[str, ...] = ()) -> list[tuple[int, str]]:
    """Return ``[(hwnd, title)]`` for visible top-level windows with a title.

    ``skip_titles`` lets the caller drop its own window (matched by exact title)
    so the bot never targets itself.
    """
    windows: list[tuple[int, str]] = []

    def _enum(hwnd: int, _acc: list) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        if title in skip_titles:
            return
        windows.append((hwnd, title))

    win32gui.EnumWindows(_enum, None)
    return windows


def capture_window(hwnd: int) -> tuple[Image.Image, tuple[int, int]]:
    """Capture ``hwnd`` and return ``(image, (left, top))``.

    ``(left, top)`` is the window's screen-space top-left, so a match found at
    bitmap coordinate ``(mx, my)`` maps to screen ``(left + mx, top + my)``.

    Raises ``RuntimeError`` if the window handle is invalid or the capture fails.
    """
    if not win32gui.IsWindow(hwnd):
        raise RuntimeError(f"window handle {hwnd} is no longer valid")

    # PrintWindow returns a blank bitmap for a minimized window, so restore it.
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError(f"window {hwnd} has non-positive size {width}x{height}")

    window_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(window_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)

    try:
        # Call the raw user32.PrintWindow via win32gui if available; otherwise
        # fall back to ctypes for the flag argument.
        result = _print_window(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        if result != 1:
            # Retry without the flag (older systems); still usually works when
            # the window is not occluded.
            _print_window(hwnd, save_dc.GetSafeHdc(), 0)

        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (info["bmWidth"], info["bmHeight"]),
            bits,
            "raw",
            "BGRX",
            0,
            1,
        )
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)

    return image, (left, top)


def _print_window(hwnd: int, hdc: int, flags: int) -> int:
    """Call user32.PrintWindow with an explicit flags argument."""
    import ctypes

    return ctypes.windll.user32.PrintWindow(hwnd, hdc, flags)
