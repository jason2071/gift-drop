"""Entry point for the TikTok gift-send macro bot.

Sets per-monitor DPI awareness so window rects and pyautogui cursor coordinates
are both in physical pixels (and therefore consistent), then launches the GUI.
"""

from __future__ import annotations

import ctypes


def _set_dpi_awareness() -> None:
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Win 8.1+).
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # Vista+ fallback
        except Exception:
            pass


def main() -> None:
    _set_dpi_awareness()
    from gift_bot import gui  # imported after DPI awareness is set

    gui.launch()


if __name__ == "__main__":
    main()
