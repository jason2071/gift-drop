"""tkinter GUI for the gift-send macro bot.

The bot loop runs on a background thread; log messages come back through a queue
that the Tk main loop drains, keeping the UI responsive and thread-safe.

The look is a minimal light theme built on ttk's ``clam`` base theme, which --
unlike the native Windows themes -- honours custom colours on widgets. Design
intent: flat surfaces separated by whitespace (no nested borders), one accent
colour, weight over colour for hierarchy, and colour reserved for state
(status, errors) rather than decoration.
"""

from __future__ import annotations

import queue
import re
import shutil
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import win32api
import win32gui

from . import bot
from . import capture
from . import config
from . import gifts
from . import matcher

APP_TITLE = "GiftDrop"


# --- palette --------------------------------------------------------------
BG = "#eff1f5"        # window base
SURFACE = "#ffffff"   # card / tile surface
SURFACE2 = "#e6e9ef"  # input fill
BORDER = "#cdd0da"    # hairline separators / tile edges
TEXT = "#4c4f69"      # primary text
MUTED = "#8c8fa1"     # secondary text
ACCENT = "#1e66f5"    # single accent (primary action, selection, focus)
ACCENT_HI = "#3b7bff"
BTN_FG = "#ffffff"
GREEN = "#2f8132"     # state only: running
RED = "#d20f39"       # state only: stopped / error
LOG_INFO = "#5a5d70"

FONT = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_TITLE = ("Segoe UI Semibold", 13)
FONT_MONO = ("Cascadia Mono", 9)

PAD = 12   # base spacing unit
GAP = 6    # gap between stacked cards


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.configure(bg=BG)
        root.resizable(False, False)  # fixed size; _fit_window drives the size
        self._set_app_icon()

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.windows: list[tuple[int, str]] = []

        # Log lives in a modal; buffer entries so it survives open/close.
        self._log_lines: list[tuple[str, str]] = []  # (message, tag)
        self._log_text: tk.Text | None = None        # set while the modal is open
        self._log_win: tk.Toplevel | None = None

        # Worker threads never touch Tk directly: they queue a callable here and
        # _drain_log (on the Tk thread) runs it. Keeps all widget access on-thread.
        self._ui_queue: "queue.Queue" = queue.Queue()
        self._dry_busy = False   # a dry-run capture/match thread is in flight
        self._run_gen = 0        # per-run token so a stale Esc watcher exits
        self._preview_win: tk.Toplevel | None = None

        self._saved = config.load()
        # store  = every gift found in assets/ (the full library)
        # shortcuts = the curated subset pinned to the main "Gift to send" bar
        self.store: list[gifts.Gift] = gifts.discover()
        self.shortcuts: list[gifts.Gift] = self._load_shortcuts()
        saved_gift = self._saved.get("gift")
        self.current_gift: gifts.Gift | None = next(
            (g for g in self.shortcuts if g.icon_path.stem == saved_gift), None
        ) or (self.shortcuts[0] if self.shortcuts else None)

        self._list_photos: list = []      # keep refs for shortcut-bar thumbnails
        self._store_photos: list = []     # keep refs for store-modal thumbnails
        self._store_win: tk.Toplevel | None = None
        self._store_body: tk.Widget | None = None
        self._running = False             # a send worker is active -> lock inputs

        self._setup_style()
        self._build_ui()
        self.refresh_windows()
        self._fit_window()
        self.root.after(100, self._drain_log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Esc cancels a run when GiftDrop has focus; _watch_escape covers the
        # case where the target window is on top. Bound to root only (not
        # bind_all) so modal Esc-to-close doesn't also abort the run.
        self.root.bind("<Escape>", lambda _e: self._esc_stop())

    # ---- styling ---------------------------------------------------------
    def _setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=TEXT, font=FONT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=FONT)
        # Section heading: weight, not colour or caps.
        style.configure(
            "Heading.TLabel", background=SURFACE, foreground=TEXT, font=FONT_BOLD
        )
        style.configure(
            "Field.TLabel", background=SURFACE, foreground=MUTED, font=FONT_SM
        )
        style.configure(
            "Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE
        )
        style.configure(
            "Subtitle.TLabel", background=BG, foreground=MUTED, font=FONT_SM
        )
        # Title on a card surface (dialogs sit on BG; picker titles reuse Title).
        style.configure(
            "CardHint.TLabel", background=SURFACE, foreground=MUTED, font=FONT_SM
        )

        # Entry / Combobox: filled field, border only on focus.
        style.configure(
            "TEntry",
            fieldbackground=SURFACE2,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=SURFACE2,
            lightcolor=SURFACE2,
            darkcolor=SURFACE2,
            borderwidth=1,
            padding=5,
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
        style.configure(
            "TCombobox",
            fieldbackground=SURFACE2,
            background=SURFACE2,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=SURFACE2,
            lightcolor=SURFACE2,
            darkcolor=SURFACE2,
            borderwidth=1,
            padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", SURFACE2)],
            bordercolor=[("focus", ACCENT), ("hover", ACCENT)],
            lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
            foreground=[("readonly", TEXT)],
        )

        # Buttons: one primary (accent), everything else quiet.
        style.configure(
            "TButton",
            background=SURFACE2,
            foreground=TEXT,
            borderwidth=0,
            focuscolor=SURFACE2,
            padding=(10, 5),
            font=FONT_SM,
        )
        style.map(
            "TButton",
            background=[("active", BORDER), ("disabled", SURFACE)],
            foreground=[("disabled", MUTED)],
            focuscolor=[("focus", ACCENT)],
        )
        style.configure("Primary.TButton", background=ACCENT, foreground=BTN_FG)
        style.map(
            "Primary.TButton",
            background=[("active", ACCENT_HI), ("disabled", SURFACE2)],
            foreground=[("disabled", MUTED)],
            focuscolor=[("focus", BTN_FG)],
        )

        # Checkbutton on a card surface
        style.configure(
            "Card.TCheckbutton",
            background=SURFACE,
            foreground=TEXT,
            focuscolor=SURFACE,
            font=FONT_SM,
        )
        style.map(
            "Card.TCheckbutton",
            background=[("active", SURFACE)],
            foreground=[("disabled", MUTED)],
        )

        # Scrollbar
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE2,
            troughcolor=SURFACE,
            bordercolor=SURFACE,
            arrowcolor=MUTED,
            borderwidth=0,
        )
        style.map("Vertical.TScrollbar", background=[("active", BORDER)])

        # The Combobox popdown is a plain Tk Listbox that ignores ttk styling.
        self.root.option_add("*TCombobox*Listbox.background", SURFACE2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BTN_FG)
        self.root.option_add("*TCombobox*Listbox.font", FONT_SM)

    def _set_app_icon(self) -> None:
        """Set the title-bar / taskbar icon. Best-effort — never fatal."""
        ico = gifts.ASSETS_DIR / "app.ico"
        try:
            if ico.exists():
                self.root.iconbitmap(default=str(ico))
        except Exception:  # noqa: BLE001 - a missing/odd icon must not crash the UI
            pass

    def _fit_window(self, *, grow_only: bool = False) -> None:
        """Size the window to its natural content so the action buttons are never
        clipped, regardless of display scaling. The window is not user-resizable,
        so it always matches content exactly. ``grow_only`` is accepted for call
        compatibility but ignored."""
        self.root.update_idletasks()
        w = max(self.root.winfo_reqwidth(), 540)
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{h}")

    def _card(self, *, expand: bool = False) -> ttk.Frame:
        """A flat white card on the base background. Separation comes from the
        surface/background contrast plus whitespace -- no borders."""
        card = ttk.Frame(self.root, style="Card.TFrame", padding=PAD)
        card.pack(
            fill="both" if expand else "x",
            padx=PAD,
            pady=(0, GAP),
            expand=expand,
        )
        return card

    # ---- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        # Header --------------------------------------------------------
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=PAD, pady=(PAD, GAP))
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(side="left")
        ttk.Label(
            header, text="TikTok gift-send macro", style="Subtitle.TLabel"
        ).pack(side="left", padx=(10, 0))
        self.status_label = tk.Label(header, bg=BG, font=FONT_SM, fg=MUTED)
        self.status_label.pack(side="right")
        self._set_status("idle")

        # Gift card: inline list, click a gift to make it active ---------
        gift_card = self._card()
        gift_head = ttk.Frame(gift_card, style="Card.TFrame")
        gift_head.pack(fill="x", pady=(0, 8))
        ttk.Label(gift_head, text="Gift to send", style="Heading.TLabel").pack(
            side="left"
        )
        self.store_btn = ttk.Button(
            gift_head, text="Store gift", command=self._open_store_modal
        )
        self.store_btn.pack(side="right")
        self.gift_list = ttk.Frame(gift_card, style="Card.TFrame")
        self.gift_list.pack(fill="x")
        self._list_photos: list = []
        self._render_gift_list()

        # Target card ---------------------------------------------------
        target = self._card()
        ttk.Label(target, text="Target window", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        self.window_var = tk.StringVar()
        self.window_combo = ttk.Combobox(
            target, textvariable=self.window_var, state="readonly"
        )
        self.window_combo.grid(row=1, column=0, columnspan=3, sticky="we")
        self.refresh_btn = ttk.Button(
            target, text="Refresh", command=self.refresh_windows
        )
        self.refresh_btn.grid(row=1, column=3, sticky="e", padx=(GAP, 0))
        target.columnconfigure(0, weight=1)

        # Parameters card ----------------------------------------------
        params = self._card()
        ttk.Label(params, text="Parameters", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.unlimited_var = tk.BooleanVar(value=bool(self._saved.get("unlimited")))
        self.unlimited_chk = ttk.Checkbutton(
            params,
            text="Unlimited count (send until Stop)",
            style="Card.TCheckbutton",
            variable=self.unlimited_var,
            command=self._toggle_unlimited,
        )
        self.unlimited_chk.grid(row=0, column=1, columnspan=3, sticky="e", pady=(0, 8))

        self.interval_var = tk.StringVar(value=str(self._saved.get("interval", "2")))
        self.count_var = tk.StringVar(value=str(self._saved.get("count", "1")))
        self.threshold_var = tk.StringVar(
            value=str(self._saved.get("threshold", "0.8"))
        )
        self.retries_var = tk.StringVar(value=str(self._saved.get("retries", "3")))

        self._param_entries: list[ttk.Entry] = []
        self._field(params, "Interval (s)", self.interval_var, row=1, col=0)
        self.count_entry = self._field(params, "Count", self.count_var, row=1, col=2)
        self._field(params, "Threshold", self.threshold_var, row=2, col=0)
        self._field(params, "Retries", self.retries_var, row=2, col=2)
        for c in (1, 3):
            params.columnconfigure(c, weight=1)
        self._apply_unlimited()  # reflect the loaded value on the Count field

        # Action buttons -----------------------------------------------
        buttons = ttk.Frame(self.root)
        buttons.pack(fill="x", padx=PAD, pady=(0, GAP))
        self.start_btn = ttk.Button(
            buttons, text="Start", style="Primary.TButton", command=self.start
        )
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            buttons, text="Stop", command=self.stop, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=GAP)
        self.dry_btn = ttk.Button(buttons, text="Dry-run", command=self.dry_run)
        self.dry_btn.pack(side="left")
        ttk.Button(buttons, text="Log", command=self._open_log_modal).pack(
            side="left", padx=GAP
        )

    def _field(
        self, parent: tk.Widget, label: str, var: tk.StringVar, *, row: int, col: int
    ) -> ttk.Entry:
        ttk.Label(parent, text=label, style="Field.TLabel").grid(
            row=row, column=col, sticky="w", padx=(0, GAP), pady=4
        )
        entry = ttk.Entry(parent, textvariable=var, width=8)
        entry.grid(row=row, column=col + 1, sticky="w", padx=(0, PAD), pady=4)
        self._param_entries.append(entry)
        return entry

    def _set_status(self, state: str) -> None:
        colors = {
            "idle": (MUTED, "Idle"),
            "running": (GREEN, "Running"),
            "stopped": (RED, "Stopped"),
        }
        color, text = colors.get(state, (MUTED, "Idle"))
        self.status_label.configure(text=f"● {text}", fg=color)

    # ---- gift selection --------------------------------------------------
    def _load_thumb(self, path, size: int = 56):
        """Load ``path`` as a square-ish thumbnail PhotoImage (caller keeps ref)."""
        from PIL import Image, ImageTk

        img = Image.open(path).convert("RGBA")
        img.thumbnail((size, size))
        return ImageTk.PhotoImage(img)

    def _load_shortcuts(self) -> list["gifts.Gift"]:
        """Resolve saved shortcut slugs against the store. First run (no saved
        list) pins every gift, up to the cap."""
        by_stem = {g.icon_path.stem: g for g in self.store}
        saved = self._saved.get("shortcuts")
        if saved is None:
            return self.store[: self.MAX_SHORTCUTS]
        picked = [by_stem[s] for s in saved if s in by_stem]
        return picked[: self.MAX_SHORTCUTS]

    def _render_gift_list(self) -> None:
        """(Re)build the shortcut-bar tiles. The active gift is the one that
        will be sent; clicking makes it active, right-click unpins it."""
        for w in self.gift_list.winfo_children():
            w.destroy()
        self._list_photos = []

        if not self.shortcuts:
            ttk.Label(
                self.gift_list,
                text="No shortcuts — click Store gift to pin one.",
                style="CardHint.TLabel",
            ).grid(row=0, column=0, sticky="w", pady=4)
            return

        # Thumbnail-only tiles, tight enough that the full bar (up to
        # MAX_SHORTCUTS) fits on one row. Active gift = tile border. No labels.
        side = 58
        for i, g in enumerate(self.shortcuts):
            photo = self._load_thumb(g.icon_path, side - 18)
            self._list_photos.append(photo)
            active = g == self.current_gift

            tile = tk.Frame(
                self.gift_list,
                bg=SURFACE,
                cursor="hand2",
                highlightthickness=2,
                highlightbackground=(ACCENT if active else BORDER),
                highlightcolor=(ACCENT if active else BORDER),
                width=side,
                height=side,
            )
            tile.grid(row=0, column=i, padx=2, pady=2)
            tile.grid_propagate(False)
            tile.pack_propagate(False)

            thumb = tk.Label(tile, image=photo, bg=SURFACE)
            thumb.pack(expand=True)

            def on_enter(_e, t=tile, a=active):
                if not a:
                    t.configure(highlightbackground=MUTED, highlightcolor=MUTED)

            def on_leave(_e, t=tile, a=active):
                if not a:
                    t.configure(highlightbackground=BORDER, highlightcolor=BORDER)

            for child in (tile, thumb):
                child.bind("<Button-1>", lambda _e, gg=g: self._set_gift(gg))
                child.bind("<Button-3>", lambda _e, gg=g: self._remove_shortcut(gg))
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)

        # Grow the window if the bar just got taller (e.g. first pin).
        if hasattr(self, "start_btn"):
            self._fit_window(grow_only=True)

    def _add_shortcut(self, gift: "gifts.Gift") -> bool:
        """Pin a store gift to the bar. Returns False if the bar is full."""
        if self._running:
            return True  # no change while sending
        if any(g.icon_path == gift.icon_path for g in self.shortcuts):
            return True
        if len(self.shortcuts) >= self.MAX_SHORTCUTS:
            return False
        self.shortcuts.append(gift)
        if self.current_gift is None:
            self.current_gift = gift
        self._render_gift_list()
        self._save_settings()
        return True

    def _remove_shortcut(self, gift: "gifts.Gift") -> None:
        """Unpin a gift from the bar. The gift stays in the store."""
        if self._running:
            return
        self.shortcuts = [
            g for g in self.shortcuts if g.icon_path != gift.icon_path
        ]
        if self.current_gift == gift:
            self.current_gift = self.shortcuts[0] if self.shortcuts else None
        self._render_gift_list()
        self._fit_window()  # bar shrank -> reclaim the space
        self._save_settings()
        if self._store_win is not None and self._store_win.winfo_exists():
            self._render_store_body()

    def _delete_gift(self, gift: "gifts.Gift") -> None:
        """Permanently remove a gift from the store (deletes its PNGs) and drop
        it from the shortcut bar."""
        if self._running:
            return
        if not messagebox.askyesno(
            APP_TITLE,
            f"Delete '{gift.name}' from the store?\n\n"
            f"Removes {gift.icon_path.name} and {gift.popup_path.name} "
            "from assets/. This cannot be undone.",
            parent=self._store_win or self.root,
        ):
            return
        for p in (gift.icon_path, gift.popup_path):
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                messagebox.showerror(APP_TITLE, f"Could not delete:\n{exc}")
                return

        stem = self.current_gift.icon_path.stem if self.current_gift else None
        self.store = gifts.discover()
        self.shortcuts = [
            g for g in self.shortcuts if g.icon_path != gift.icon_path
        ]
        self.current_gift = next(
            (g for g in self.shortcuts if g.icon_path.stem == stem), None
        ) or (self.shortcuts[0] if self.shortcuts else None)
        self._render_gift_list()
        self._fit_window()  # bar may have shrunk
        self._save_settings()
        if self._store_win is not None and self._store_win.winfo_exists():
            self._render_store_body()
        self.log(f"Deleted gift: {gift.name}")

    def _set_gift(self, gift: "gifts.Gift") -> None:
        if self._running:
            return  # don't switch the gift mid-send
        self.current_gift = gift
        self._render_gift_list()
        self._save_settings()
        self.log(f"Selected gift: {gift.name}")

    def _save_settings(self) -> None:
        config.save(
            {
                "interval": self.interval_var.get(),
                "count": self.count_var.get(),
                "threshold": self.threshold_var.get(),
                "retries": self.retries_var.get(),
                "unlimited": self.unlimited_var.get(),
                "gift": self.current_gift.icon_path.stem if self.current_gift else None,
                "shortcuts": [g.icon_path.stem for g in self.shortcuts],
            }
        )

    def _apply_unlimited(self) -> None:
        """Grey out the Count field when Unlimited is on (unless a run locked it)."""
        if self._running:
            return
        self.count_entry.configure(
            state="disabled" if self.unlimited_var.get() else "normal"
        )

    def _toggle_unlimited(self) -> None:
        self._apply_unlimited()
        self._save_settings()

    # ---- gift store modal ------------------------------------------------
    def _open_store_modal(self) -> None:
        """Modal to manage the whole gift library: add, delete, pin/unpin."""
        if self._store_win is not None and self._store_win.winfo_exists():
            self._store_win.lift()
            self._store_win.focus_force()
            return

        win = tk.Toplevel(self.root)
        win.title("Gift store")
        win.configure(bg=BG)
        win.transient(self.root)
        win.geometry("460x460")
        self._store_win = win

        head = ttk.Frame(win)
        head.pack(fill="x", padx=PAD, pady=(PAD, GAP))
        titles = ttk.Frame(head)
        titles.pack(side="left", anchor="w")
        ttk.Label(titles, text="Gift store", style="Title.TLabel").pack(anchor="w")
        self.store_count = ttk.Label(titles, text="", style="Subtitle.TLabel")
        self.store_count.pack(anchor="w")
        ttk.Button(
            head, text="Add gift", style="Primary.TButton",
            command=self._open_add_gift_dialog,
        ).pack(side="right", anchor="n")

        # Scrollable list of every stored gift.
        outer = tk.Frame(win, bg=SURFACE)
        outer.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))
        canvas = tk.Canvas(outer, bg=SURFACE, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(
            outer, style="Vertical.TScrollbar", command=canvas.yview
        )
        sb.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=sb.set)
        inner = tk.Frame(canvas, bg=SURFACE)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")

        def _resize(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig("inner", width=canvas.winfo_width())

        inner.bind("<Configure>", _resize)
        canvas.bind("<Configure>", _resize)
        canvas.bind(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"),
        )
        self._store_body = inner

        def on_close() -> None:
            self._store_win = None
            self._store_body = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.bind("<Escape>", lambda _e: on_close())

        self._render_store_body()

        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"+{rx + (rw - w) // 2}+{ry + (rh - h) // 2}")

    def _render_store_body(self) -> None:
        body = self._store_body
        if body is None:
            return
        for w in body.winfo_children():
            w.destroy()
        self._store_photos = []
        self.store_count.configure(
            text=f"{len(self.store)}/{self.MAX_STORE} in store · "
            f"{len(self.shortcuts)}/{self.MAX_SHORTCUTS} pinned"
        )

        if not self.store:
            ttk.Label(
                body,
                text="No gifts yet. Click Add gift to upload one.",
                style="CardHint.TLabel",
            ).pack(anchor="w", padx=8, pady=14)
            return

        pinned = {g.icon_path.stem for g in self.shortcuts}
        bar_full = len(self.shortcuts) >= self.MAX_SHORTCUTS
        for g in self.store:
            row = tk.Frame(body, bg=SURFACE)
            row.pack(fill="x", padx=4, pady=3)
            photo = self._load_thumb(g.icon_path, 40)
            self._store_photos.append(photo)
            tk.Label(row, image=photo, bg=SURFACE).pack(side="left", padx=(2, 12))
            tk.Label(row, text=g.name, bg=SURFACE, fg=TEXT, font=FONT).pack(
                side="left"
            )
            ttk.Button(
                row, text="Delete", command=lambda gg=g: self._delete_gift(gg)
            ).pack(side="right", padx=(6, 0))
            if g.icon_path.stem in pinned:
                ttk.Button(
                    row, text="Unpin", command=lambda gg=g: self._remove_shortcut(gg)
                ).pack(side="right")
            else:
                pin_btn = ttk.Button(
                    row, text="Pin", style="Primary.TButton",
                    command=lambda gg=g: self._pin_from_store(gg),
                )
                if bar_full:
                    pin_btn.configure(state="disabled")
                pin_btn.pack(side="right")

    def _pin_from_store(self, gift: "gifts.Gift") -> None:
        if not self._add_shortcut(gift):
            messagebox.showinfo(
                APP_TITLE,
                f"Shortcut bar is full ({self.MAX_SHORTCUTS} max). Unpin one first.",
                parent=self._store_win,
            )
            return
        self._render_store_body()

    # ---- add / upload a gift ---------------------------------------------
    MAX_SHORTCUTS = 8   # tiles that fit on the one-row shortcut bar
    MAX_STORE = 20      # total gifts kept in the library

    def _open_add_gift_dialog(self) -> None:
        """Dialog to browse an icon PNG + a send-popup PNG and store a gift."""
        if len(self.store) >= self.MAX_STORE:
            messagebox.showinfo(
                APP_TITLE,
                f"Store is full ({self.MAX_STORE} max). Delete a gift first.",
                parent=self._store_win or self.root,
            )
            return
        parent = (
            self._store_win
            if self._store_win is not None and self._store_win.winfo_exists()
            else self.root
        )
        dlg = tk.Toplevel(parent)
        dlg.title("Add a gift")
        dlg.configure(bg=BG)
        dlg.transient(parent)
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text="Add a gift", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=PAD, pady=(PAD, 2)
        )
        ttk.Label(
            dlg,
            text="Two PNGs: the gift icon, and the hover popup with the Send button.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=PAD, pady=(0, 14))

        icon_var = tk.StringVar()
        send_var = tk.StringVar()

        def browse_row(row: int, label: str, var: tk.StringVar) -> None:
            ttk.Label(dlg, text=label, style="TLabel").grid(
                row=row, column=0, sticky="w", padx=PAD, pady=6
            )
            entry = ttk.Entry(dlg, textvariable=var, width=26, state="readonly")
            entry.grid(row=row, column=1, sticky="we", padx=(0, GAP), pady=6)
            ttk.Button(
                dlg, text="Browse", command=lambda: self._browse_png(var)
            ).grid(row=row, column=2, sticky="e", padx=(0, PAD), pady=6)

        browse_row(2, "Gift icon", icon_var)
        browse_row(3, "Send popup", send_var)

        def save() -> None:
            self._save_gift(icon_var.get(), send_var.get(), dlg)

        btns = ttk.Frame(dlg)
        btns.grid(row=4, column=0, columnspan=3, sticky="e", padx=PAD, pady=(14, PAD))
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right")
        ttk.Button(
            btns, text="Save gift", style="Primary.TButton", command=save
        ).pack(side="right", padx=(0, GAP))
        dlg.columnconfigure(1, weight=1)

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: save())

        # Centre over the parent window.
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = parent.winfo_rootx(), parent.winfo_rooty()
        rw, rh = parent.winfo_width(), parent.winfo_height()
        dlg.geometry(f"+{rx + (rw - w) // 2}+{ry + (rh - h) // 2}")

    def _browse_png(self, var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            title="Select a PNG",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if path:
            var.set(path)

    @staticmethod
    def _slug(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")

    def _auto_slug(self, icon_path: str) -> str:
        """Derive a unique, filesystem-safe slug for a new gift. Uses the icon's
        filename, falling back to gift-N, and appends -N to avoid collisions."""
        stem = Path(icon_path).stem
        if stem.endswith("-send"):
            stem = stem[: -len("-send")]
        base = self._slug(stem) or "gift"
        slug, n = base, 2
        while (
            (gifts.ASSETS_DIR / f"{slug}.png").exists()
            or (gifts.ASSETS_DIR / f"{slug}-send.png").exists()
        ):
            slug, n = f"{base}-{n}", n + 1
        return slug

    def _save_gift(
        self,
        icon_path: str,
        send_path: str,
        dlg: "tk.Toplevel",
    ) -> None:
        if not icon_path or not send_path:
            messagebox.showwarning(
                APP_TITLE, "Choose both the icon and the send PNG.", parent=dlg
            )
            return
        if len(self.store) >= self.MAX_STORE:
            messagebox.showinfo(
                APP_TITLE, f"Store is full ({self.MAX_STORE} max).", parent=dlg
            )
            return

        slug = self._auto_slug(icon_path)  # auto-generated, always unique
        dest_icon = gifts.ASSETS_DIR / f"{slug}.png"
        dest_send = gifts.ASSETS_DIR / f"{slug}-send.png"
        try:
            gifts.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(icon_path, dest_icon)
            shutil.copyfile(send_path, dest_send)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not save gift:\n{exc}", parent=dlg)
            return

        self.store = gifts.discover()
        new = next((g for g in self.store if g.icon_path == dest_icon), None)
        dlg.destroy()
        if new is not None:
            pinned = self._add_shortcut(new)  # pin to the bar if there's room
            self.log(
                f"Stored gift: {new.name}"
                + ("" if pinned else "  (bar full — pin it from the store)")
            )
        if self._store_win is not None and self._store_win.winfo_exists():
            self._render_store_body()

    # ---- helpers ---------------------------------------------------------
    def log(self, msg: str) -> None:
        """Thread-safe: push to queue; drained on the Tk thread."""
        self.log_queue.put(msg)

    def _tag_for(self, msg: str) -> str:
        low = msg.lower()
        if "error" in low or "not found" in low or "fail" in low:
            return "err"
        if "found" in low or "sent" in low or "done" in low or "success" in low:
            return "ok"
        return "info"

    def _clear_log(self) -> None:
        self._log_lines.clear()
        if self._log_text is not None:
            self._log_text.configure(state="normal")
            self._log_text.delete("1.0", "end")
            self._log_text.configure(state="disabled")

    def _append_log(self, msg: str, tag: str) -> None:
        """Append one line to the buffer and, if the modal is open, to its view."""
        self._log_lines.append((msg, tag))
        if self._log_text is not None:
            self._log_text.configure(state="normal")
            self._log_text.insert("end", msg + "\n", tag)
            self._log_text.see("end")
            self._log_text.configure(state="disabled")

    def _drain_log(self) -> None:
        if not self.root.winfo_exists():  # window closed; stop the after-loop
            return
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg, self._tag_for(msg))
        except queue.Empty:
            pass
        # Run any UI work queued by worker threads (Tk touched only here).
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        # Re-enable Start when the worker finishes.
        if self.worker is not None and not self.worker.is_alive():
            self.worker = None
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self._set_running(False)
            # Keep "Stopped" visible when the run was cancelled; a clean finish
            # (stop_event never set) returns to "Idle".
            self._set_status("stopped" if self.stop_event.is_set() else "idle")
        self.root.after(100, self._drain_log)

    def _open_log_modal(self) -> None:
        # Bring an already-open log window to the front instead of duplicating.
        if self._log_win is not None and self._log_win.winfo_exists():
            self._log_win.lift()
            self._log_win.focus_force()
            return

        win = tk.Toplevel(self.root)
        win.title("Activity log")
        win.configure(bg=BG)
        win.transient(self.root)
        win.geometry("560x420")

        head = ttk.Frame(win)
        head.pack(fill="x", padx=PAD, pady=(PAD, GAP))
        ttk.Label(head, text="Activity log", style="Title.TLabel").pack(side="left")
        ttk.Button(head, text="Clear", command=self._clear_log).pack(side="right")

        body = tk.Frame(win, bg=SURFACE)
        body.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))
        text = tk.Text(
            body,
            state="disabled",
            wrap="word",
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=SURFACE2,
            relief="flat",
            font=FONT_MONO,
            padx=8,
            pady=6,
            highlightthickness=0,
        )
        text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            body, style="Vertical.TScrollbar", command=text.yview
        )
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        text.tag_configure("ok", foreground=TEXT)
        text.tag_configure("err", foreground=RED)
        text.tag_configure("info", foreground=LOG_INFO)

        # Load the buffered history.
        text.configure(state="normal")
        for msg, tag in self._log_lines:
            text.insert("end", msg + "\n", tag)
        text.see("end")
        text.configure(state="disabled")

        self._log_win = win
        self._log_text = text  # live-append target while open

        def on_close() -> None:
            self._log_text = None
            self._log_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.bind("<Escape>", lambda _e: on_close())

        # Centre over the main window.
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"+{rx + (rw - w) // 2}+{ry + (rh - h) // 2}")

    def refresh_windows(self) -> None:
        prev_hwnd = self._selected_hwnd_quiet()
        self.windows = capture.list_windows(skip_titles=(APP_TITLE,))
        labels = [f"{title}  [hwnd {hwnd}]" for hwnd, title in self.windows]
        self.window_combo["values"] = labels
        if not labels:
            self.window_var.set("No windows found — click Refresh")
            return
        # Keep the same target across refreshes; only default to 0 on first load.
        hwnds = [hwnd for hwnd, _ in self.windows]
        if prev_hwnd in hwnds:
            self.window_combo.current(hwnds.index(prev_hwnd))
        elif prev_hwnd is None:
            self.window_combo.current(0)  # first load / nothing was selected
        else:
            # Previous target vanished; clear rather than silently retarget.
            self.window_combo.set("")

    def _selected_hwnd_quiet(self) -> int | None:
        """Currently selected hwnd, or None — without warning popups."""
        idx = self.window_combo.current()
        if 0 <= idx < len(self.windows):
            return self.windows[idx][0]
        return None

    def _selected_hwnd(self) -> int | None:
        idx = self.window_combo.current()
        if idx < 0 or idx >= len(self.windows):
            messagebox.showwarning(APP_TITLE, "Select a target window first.")
            return None
        return self.windows[idx][0]

    def _read_params(self) -> tuple[int | None, float, int, float] | None:
        unlimited = self.unlimited_var.get()
        try:
            count = None if unlimited else int(self.count_var.get())
            interval = float(self.interval_var.get())
            retries = int(self.retries_var.get())
            threshold = float(self.threshold_var.get())
        except ValueError:
            messagebox.showerror(APP_TITLE, "Interval/Count/Retries/Threshold must be numbers.")
            return None
        bad_count = count is not None and count < 1
        if bad_count or interval < 0 or retries < 1 or not (0 < threshold <= 1):
            messagebox.showerror(
                APP_TITLE,
                "Count>=1, Interval>=0, Retries>=1, 0<Threshold<=1.",
            )
            return None
        return count, interval, retries, threshold

    # ---- actions ---------------------------------------------------------
    def _set_running(self, running: bool) -> None:
        """Lock inputs that must not change while a send worker is active."""
        self._running = running
        state = "disabled" if running else "normal"
        self.window_combo.configure(state="disabled" if running else "readonly")
        self.refresh_btn.configure(state=state)
        self.dry_btn.configure(state=state)
        self.store_btn.configure(state=state)
        self.unlimited_chk.configure(state=state)
        for entry in self._param_entries:
            entry.configure(state=state)
        if not running:
            self._apply_unlimited()  # keep Count greyed if Unlimited is still on

    def start(self) -> None:
        if self.worker is not None or self._dry_busy:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        if self.current_gift is None:
            messagebox.showwarning(APP_TITLE, "Add and select a gift first.")
            return
        params = self._read_params()
        if params is None:
            return
        count, interval, retries, threshold = params
        self._save_settings()  # remember these values for next launch

        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_running(True)
        self._set_status("running")
        count_str = "unlimited" if count is None else count
        self.log(
            f"Starting: gift={self.current_gift.name} count={count_str} "
            f"interval={interval}s retries={retries} threshold={threshold}"
        )

        self.worker = threading.Thread(
            target=bot.run,
            args=(
                hwnd,
                count,
                interval,
                retries,
                threshold,
                self.stop_event,
                self.log,
                self.current_gift,
            ),
            daemon=True,
        )
        self.worker.start()
        self._run_gen += 1
        threading.Thread(
            target=self._watch_escape, args=(hwnd, self._run_gen), daemon=True
        ).start()

    def _watch_escape(self, hwnd: int, gen: int) -> None:
        """Poll Esc so a run can be aborted while the target window is on top.
        Runs on a worker thread, so it must NOT touch Tk: it only sets the
        thread-safe ``stop_event`` (and ``log`` is queue-backed). ``gen`` retires
        a stale watcher if a new run starts. Esc is honoured only while the
        target window is foreground, so unrelated app Esc-presses don't cancel."""
        VK_ESCAPE = 0x1B
        while (
            self._run_gen == gen
            and self._running
            and not self.stop_event.is_set()
        ):
            if (
                win32gui.GetForegroundWindow() == hwnd
                and win32api.GetAsyncKeyState(VK_ESCAPE) & 0x8000
            ):
                self.log("Esc pressed — cancelling.")
                self.stop_event.set()  # thread-safe; worker exits, _drain_log reacts
                return
            time.sleep(0.05)

    def _esc_stop(self) -> None:
        """Esc handler on the Tk thread (root binding), for when GiftDrop has focus."""
        if self._running:
            self.log("Esc pressed — cancelling.")
            self.stop()

    def stop(self) -> None:
        self.stop_event.set()
        self._set_status("stopped")
        self.log("Stop requested...")

    def dry_run(self) -> None:
        """Capture the selected window, detect without clicking, show an overlay.

        Capture + match run on a background thread so the UI stays responsive.
        The thread never touches Tk: it queues the result on ``_ui_queue`` for
        ``_drain_log`` to render on the Tk thread.
        """
        if self._running or self._dry_busy:
            return
        hwnd = self._selected_hwnd()
        if hwnd is None:
            return
        if self.current_gift is None:
            messagebox.showwarning(APP_TITLE, "Add and select a gift first.")
            return
        params = self._read_params()
        if params is None:
            return
        _, _, _, threshold = params
        gift = self.current_gift
        self._dry_busy = True
        self.dry_btn.configure(state="disabled")
        self.log(f"Dry-run ({gift.name}): detecting icon (no click)...")

        def work() -> None:
            try:
                image, _ = capture.capture_window(hwnd)
                icon_tpl = matcher.load_template(gift.icon_path)
                match = matcher.find(image, icon_tpl, threshold=threshold)
            except Exception as exc:  # noqa: BLE001 - surface any capture/match error
                self.log(f"Dry-run error: {exc}")
                self._ui_queue.put(self._end_dry_run)
                return
            if match is None:
                self.log("Dry-run: icon NOT found. Lower Threshold or check the window.")
                self._ui_queue.put(self._end_dry_run)
                return
            self.log(
                f"Dry-run: icon found at window ({match.cx},{match.cy}) "
                f"score {match.score:.2f}."
            )
            self._ui_queue.put(lambda: self._end_dry_run(image, match))

        threading.Thread(target=work, daemon=True).start()

    def _end_dry_run(self, image=None, match=None) -> None:
        """Runs on the Tk thread. Clears the busy flag; re-enables Dry-run only
        if a real run hasn't since taken over the button state."""
        self._dry_busy = False
        if not self._running:
            self.dry_btn.configure(state="normal")
        if image is not None and match is not None:
            self._show_preview(image, match)

    def _show_preview(self, image, match) -> None:
        from PIL import ImageDraw, ImageTk

        preview = image.convert("RGB").copy()
        draw = ImageDraw.Draw(preview)
        draw.rectangle(
            [match.left, match.top, match.left + match.w, match.top + match.h],
            outline=(210, 15, 57),
            width=3,
        )
        # Scale down large captures to fit a preview window.
        max_side = 900
        scale = min(1.0, max_side / max(preview.width, preview.height))
        if scale < 1.0:
            preview = preview.resize(
                (int(preview.width * scale), int(preview.height * scale))
            )

        # Reuse one preview window instead of piling up Toplevels/PhotoImages.
        if self._preview_win is not None and self._preview_win.winfo_exists():
            self._preview_win.destroy()
        win = tk.Toplevel(self.root)
        win.title("Dry-run preview")
        win.configure(bg=BG)
        win.bind("<Escape>", lambda _e: win.destroy())
        photo = ImageTk.PhotoImage(preview)
        label = tk.Label(win, image=photo, bg=BG, bd=0)
        label.image = photo  # keep a reference
        label.pack(padx=PAD, pady=PAD)
        self._preview_win = win

    def _on_close(self) -> None:
        self._save_settings()
        self.stop_event.set()
        self.root.destroy()


def launch() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
