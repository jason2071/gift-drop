"""tkinter GUI for the gift-send macro bot.

The bot loop runs on a background thread; log messages come back through a queue
that the Tk main loop drains, keeping the UI responsive and thread-safe.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import bot
from . import capture
from . import matcher

APP_TITLE = "GiftDrop"


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.geometry("560x520")
        root.minsize(480, 420)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.windows: list[tuple[int, str]] = []

        self._build_ui()
        self.refresh_windows()
        self.root.after(100, self._drain_log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="Target window:").grid(row=0, column=0, sticky="w")
        self.window_var = tk.StringVar()
        self.window_combo = ttk.Combobox(
            top, textvariable=self.window_var, state="readonly", width=48
        )
        self.window_combo.grid(row=0, column=1, columnspan=2, sticky="we", padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_windows).grid(
            row=0, column=3, sticky="e"
        )
        top.columnconfigure(1, weight=1)

        params = ttk.Frame(self.root)
        params.pack(fill="x", **pad)

        ttk.Label(params, text="Interval (s):").grid(row=0, column=0, sticky="w")
        self.interval_var = tk.StringVar(value="2")
        ttk.Entry(params, textvariable=self.interval_var, width=8).grid(
            row=0, column=1, sticky="w", padx=4
        )

        ttk.Label(params, text="Count:").grid(row=0, column=2, sticky="w")
        self.count_var = tk.StringVar(value="1")
        ttk.Entry(params, textvariable=self.count_var, width=8).grid(
            row=0, column=3, sticky="w", padx=4
        )

        ttk.Label(params, text="Threshold:").grid(row=0, column=4, sticky="w")
        self.threshold_var = tk.StringVar(value="0.8")
        ttk.Entry(params, textvariable=self.threshold_var, width=8).grid(
            row=0, column=5, sticky="w", padx=4
        )

        ttk.Label(params, text="Retries:").grid(row=1, column=0, sticky="w")
        self.retries_var = tk.StringVar(value="3")
        ttk.Entry(params, textvariable=self.retries_var, width=8).grid(
            row=1, column=1, sticky="w", padx=4
        )

        buttons = ttk.Frame(self.root)
        buttons.pack(fill="x", **pad)
        self.start_btn = ttk.Button(buttons, text="Start", command=self.start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(
            buttons, text="Stop", command=self.stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(buttons, text="Dry-run", command=self.dry_run).pack(
            side="left", padx=4
        )

        ttk.Label(self.root, text="Log:").pack(anchor="w", padx=6)
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.log_text = tk.Text(log_frame, height=14, state="disabled", wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

    # ---- helpers ---------------------------------------------------------
    def log(self, msg: str) -> None:
        """Thread-safe: push to queue; drained on the Tk thread."""
        self.log_queue.put(msg)

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        # Re-enable Start when the worker finishes.
        if self.worker is not None and not self.worker.is_alive():
            self.worker = None
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
        self.root.after(100, self._drain_log)

    def refresh_windows(self) -> None:
        self.windows = capture.list_windows(skip_titles=(APP_TITLE,))
        labels = [f"{title}  [hwnd {hwnd}]" for hwnd, title in self.windows]
        self.window_combo["values"] = labels
        if labels and not self.window_var.get():
            self.window_combo.current(0)
        elif not labels:
            self.window_var.set("")

    def _selected_hwnd(self) -> int | None:
        idx = self.window_combo.current()
        if idx < 0 or idx >= len(self.windows):
            messagebox.showwarning(APP_TITLE, "Select a target window first.")
            return None
        return self.windows[idx][0]

    def _read_params(self) -> tuple[int, float, int, float] | None:
        try:
            count = int(self.count_var.get())
            interval = float(self.interval_var.get())
            retries = int(self.retries_var.get())
            threshold = float(self.threshold_var.get())
        except ValueError:
            messagebox.showerror(APP_TITLE, "Interval/Count/Retries/Threshold must be numbers.")
            return None
        if count < 1 or interval < 0 or retries < 1 or not (0 < threshold <= 1):
            messagebox.showerror(
                APP_TITLE,
                "Count>=1, Interval>=0, Retries>=1, 0<Threshold<=1.",
            )
            return None
        return count, interval, retries, threshold

    # ---- actions ---------------------------------------------------------
    def start(self) -> None:
        if self.worker is not None:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        params = self._read_params()
        if params is None:
            return
        count, interval, retries, threshold = params

        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.log(f"Starting: count={count} interval={interval}s retries={retries} threshold={threshold}")

        self.worker = threading.Thread(
            target=bot.run,
            args=(hwnd, count, interval, retries, threshold, self.stop_event, self.log),
            daemon=True,
        )
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.log("Stop requested...")

    def dry_run(self) -> None:
        """Capture the selected window, detect without clicking, show an overlay."""
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        params = self._read_params()
        if params is None:
            return
        _, _, _, threshold = params
        self.log("Dry-run: detecting icon (no click)...")
        try:
            image, _ = capture.capture_window(hwnd)
            icon_tpl = matcher.load_template(bot.ICON_TEMPLATE_PATH)
            match = matcher.find(image, icon_tpl, threshold=threshold)
        except Exception as exc:  # noqa: BLE001 - surface any capture/match error
            self.log(f"Dry-run error: {exc}")
            return
        if match is None:
            self.log("Dry-run: icon NOT found. Lower Threshold or check the window.")
            return
        self.log(
            f"Dry-run: icon found at window ({match.cx},{match.cy}) score {match.score:.2f}."
        )
        self._show_preview(image, match)

    def _show_preview(self, image, match) -> None:
        from PIL import ImageDraw, ImageTk

        preview = image.convert("RGB").copy()
        draw = ImageDraw.Draw(preview)
        draw.rectangle(
            [match.left, match.top, match.left + match.w, match.top + match.h],
            outline=(255, 0, 0),
            width=3,
        )
        # Scale down large captures to fit a preview window.
        max_side = 900
        scale = min(1.0, max_side / max(preview.width, preview.height))
        if scale < 1.0:
            preview = preview.resize(
                (int(preview.width * scale), int(preview.height * scale))
            )

        win = tk.Toplevel(self.root)
        win.title("Dry-run preview")
        photo = ImageTk.PhotoImage(preview)
        label = ttk.Label(win, image=photo)
        label.image = photo  # keep a reference
        label.pack()

    def _on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def launch() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
