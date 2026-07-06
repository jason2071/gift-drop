"""tkinter GUI for the gift-send macro bot.

The bot loop runs on a background thread; log messages come back through a queue
that the Tk main loop drains, keeping the UI responsive and thread-safe.

The look is a hand-rolled light theme (Catppuccin Latte palette) built on ttk's
``clam`` base theme, which -- unlike the native Windows themes -- honours custom
background/foreground colours on widgets.
"""

from __future__ import annotations

import queue
import re
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import bot
from . import capture
from . import gifts
from . import matcher

APP_TITLE = "GiftDrop"


# --- palette (Catppuccin Latte) ------------------------------------------
BG = "#eff1f5"        # window base
SURFACE = "#ffffff"   # card background
SURFACE2 = "#e6e9ef"  # inputs / raised
BORDER = "#bcc0cc"
TEXT = "#4c4f69"
MUTED = "#7c7f93"
ACCENT = "#1e66f5"    # blue
ACCENT_HI = "#3b7bff"
BTN_FG = "#ffffff"    # text on coloured buttons
GREEN = "#2f8132"     # deep enough for white button text + log (WCAG AA)
GREEN_HI = "#3d9e3f"
RED = "#d20f39"
RED_HI = "#e11d48"
CROSSHAIR = "#d20f39"
LOG_INFO = "#5a5d70"  # readable muted on the white log surface

FONT = ("Segoe UI", 10)
FONT_SM = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_TITLE = ("Segoe UI Semibold", 16)
FONT_MONO = ("Cascadia Mono", 9)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(APP_TITLE)
        root.geometry("580x620")
        root.minsize(520, 520)
        root.configure(bg=BG)

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.windows: list[tuple[int, str]] = []

        self.gifts: list[gifts.Gift] = gifts.discover()
        self.current_gift: gifts.Gift | None = self.gifts[0] if self.gifts else None
        self._thumb_photo = None          # keep a ref for the current-gift thumbnail
        self._picker_photos: list = []    # keep refs for picker thumbnails
        self._running = False             # a send worker is active -> lock inputs

        self._setup_style()
        self._build_ui()
        self.refresh_windows()
        self.root.after(100, self._drain_log)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- styling ---------------------------------------------------------
    def _setup_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=TEXT, font=FONT)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=SURFACE)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=FONT)
        style.configure(
            "Field.TLabel", background=SURFACE, foreground=MUTED, font=FONT_SM
        )
        style.configure(
            "Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE
        )
        style.configure(
            "Subtitle.TLabel", background=BG, foreground=MUTED, font=FONT_SM
        )
        style.configure(
            "Heading.TLabel", background=SURFACE, foreground=ACCENT, font=FONT_BOLD
        )
        style.configure(
            "Status.TLabel", background=SURFACE2, foreground=MUTED, font=FONT_SM
        )

        # Entry / Combobox
        style.configure(
            "TEntry",
            fieldbackground=SURFACE2,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            borderwidth=1,
            padding=4,
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure(
            "TCombobox",
            fieldbackground=SURFACE2,
            background=SURFACE2,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            borderwidth=1,
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", SURFACE2)],
            bordercolor=[("focus", ACCENT), ("hover", ACCENT)],
            foreground=[("readonly", TEXT)],
        )

        # Buttons
        style.configure(
            "TButton",
            background=SURFACE2,
            foreground=TEXT,
            bordercolor=BORDER,
            focuscolor=SURFACE2,
            borderwidth=0,
            padding=(12, 7),
            font=FONT_BOLD,
        )
        style.map(
            "TButton",
            background=[("active", BORDER), ("disabled", SURFACE)],
            foreground=[("disabled", MUTED)],
            focuscolor=[("focus", ACCENT)],  # visible keyboard-focus ring
        )
        style.configure("Accent.TButton", background=ACCENT, foreground=BTN_FG)
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_HI), ("disabled", SURFACE2)],
            foreground=[("disabled", MUTED)],
            focuscolor=[("focus", BTN_FG)],
        )
        style.configure("Start.TButton", background=GREEN, foreground=BTN_FG)
        style.map(
            "Start.TButton",
            background=[("active", GREEN_HI), ("disabled", SURFACE2)],
            foreground=[("disabled", MUTED)],
            focuscolor=[("focus", BTN_FG)],
        )
        style.configure("Stop.TButton", background=RED, foreground=BTN_FG)
        style.map(
            "Stop.TButton",
            background=[("active", RED_HI), ("disabled", SURFACE2)],
            foreground=[("disabled", MUTED)],
            focuscolor=[("focus", BTN_FG)],
        )

        # Scrollbar
        style.configure(
            "Vertical.TScrollbar",
            background=SURFACE2,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=MUTED,
            borderwidth=0,
        )
        style.map("Vertical.TScrollbar", background=[("active", BORDER)])

        # The Combobox popdown is a plain Tk Listbox that ignores ttk styling;
        # theme it via the option database so it matches the palette.
        self.root.option_add("*TCombobox*Listbox.background", SURFACE2)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", BTN_FG)
        self.root.option_add("*TCombobox*Listbox.font", FONT_SM)

    def _card(self, parent: tk.Widget) -> tk.Widget:
        """A rounded-ish padded surface. tk lacks true rounded corners, so we
        fake depth with a padded frame on a distinct background."""
        outer = tk.Frame(parent, bg=BORDER, bd=0)
        outer.pack(fill="x", padx=14, pady=6)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=12)
        inner.pack(fill="x", padx=1, pady=1)
        return inner

    # ---- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        # Header --------------------------------------------------------
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=14, pady=(14, 4))
        ttk.Label(header, text="🎁  GiftDrop", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Label(
            header,
            text="TikTok gift-send macro",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(10, 0), pady=(8, 0))

        self.status_pill = tk.Frame(header, bg=SURFACE2)
        self.status_pill.pack(side="right", ipadx=8, ipady=3)
        self.status_dot = tk.Canvas(
            self.status_pill, width=10, height=10, bg=SURFACE2, highlightthickness=0
        )
        self.status_dot.pack(side="left", padx=(6, 4))
        self.status_label = ttk.Label(
            self.status_pill, text="Idle", style="Status.TLabel"
        )
        self.status_label.pack(side="left", padx=(0, 6))
        self._set_status("idle")

        # Gift card -----------------------------------------------------
        gift_card = self._card(self.root)
        ttk.Label(gift_card, text="GIFT TO SEND", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        self.gift_thumb = tk.Label(gift_card, bg=SURFACE2, cursor="hand2", bd=0)
        self.gift_thumb.grid(row=1, column=0, rowspan=2, padx=(0, 12))
        self.gift_name_lbl = ttk.Label(
            gift_card, text="", style="Card.TLabel", font=FONT_BOLD, cursor="hand2"
        )
        self.gift_name_lbl.grid(row=1, column=1, sticky="sw")
        self.gift_hint_lbl = ttk.Label(
            gift_card, text="", style="Field.TLabel", cursor="hand2"
        )
        self.gift_hint_lbl.grid(row=2, column=1, sticky="nw")
        gift_card.columnconfigure(1, weight=1)
        for w in (self.gift_thumb, self.gift_name_lbl, self.gift_hint_lbl):
            w.bind(
                "<Button-1>",
                lambda _e: None if self._running else self._open_gift_picker(),
            )
        self._render_current_gift()

        # Target card ---------------------------------------------------
        target = self._card(self.root)
        ttk.Label(target, text="TARGET WINDOW", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )
        self.window_var = tk.StringVar()
        self.window_combo = ttk.Combobox(
            target, textvariable=self.window_var, state="readonly"
        )
        self.window_combo.grid(row=1, column=0, columnspan=3, sticky="we")
        self.refresh_btn = ttk.Button(
            target, text="⟳ Refresh", command=self.refresh_windows
        )
        self.refresh_btn.grid(row=1, column=3, sticky="e", padx=(8, 0))
        target.columnconfigure(0, weight=1)

        # Parameters card ----------------------------------------------
        params = self._card(self.root)
        ttk.Label(params, text="PARAMETERS", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 8)
        )

        self.interval_var = tk.StringVar(value="2")
        self.count_var = tk.StringVar(value="1")
        self.threshold_var = tk.StringVar(value="0.8")
        self.retries_var = tk.StringVar(value="3")

        self._param_entries: list[ttk.Entry] = []
        self._field(params, "Interval (s)", self.interval_var, row=1, col=0)
        self._field(params, "Count", self.count_var, row=1, col=2)
        self._field(params, "Threshold", self.threshold_var, row=2, col=0)
        self._field(params, "Retries", self.retries_var, row=2, col=2)
        for c in (1, 3):
            params.columnconfigure(c, weight=1)

        # Action buttons -----------------------------------------------
        buttons = ttk.Frame(self.root)
        buttons.pack(fill="x", padx=14, pady=(6, 4))
        self.start_btn = ttk.Button(
            buttons, text="▶  Start", style="Start.TButton", command=self.start
        )
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            buttons,
            text="■  Stop",
            style="Stop.TButton",
            command=self.stop,
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=8)
        self.dry_btn = ttk.Button(
            buttons, text="🔍  Dry-run", style="Accent.TButton", command=self.dry_run
        )
        self.dry_btn.pack(side="left")

        # Log card ------------------------------------------------------
        log_outer = tk.Frame(self.root, bg=BORDER)
        log_outer.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        log_inner = tk.Frame(log_outer, bg=SURFACE)
        log_inner.pack(fill="both", expand=True, padx=1, pady=1)

        log_head = ttk.Frame(log_inner, style="Card.TFrame")
        log_head.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(log_head, text="ACTIVITY LOG", style="Heading.TLabel").pack(
            side="left"
        )
        ttk.Button(log_head, text="Clear", command=self._clear_log).pack(side="right")

        body = ttk.Frame(log_inner, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_text = tk.Text(
            body,
            height=12,
            state="disabled",
            wrap="word",
            bg=SURFACE,
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground=BORDER,
            relief="flat",
            font=FONT_MONO,
            padx=8,
            pady=6,
            highlightthickness=0,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            body, style="Vertical.TScrollbar", command=self.log_text.yview
        )
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        # Coloured log tags (contrast-checked against the white log surface)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("err", foreground=RED)
        self.log_text.tag_configure("info", foreground=LOG_INFO)

    def _field(
        self, parent: tk.Widget, label: str, var: tk.StringVar, *, row: int, col: int
    ) -> None:
        ttk.Label(parent, text=label, style="Field.TLabel").grid(
            row=row, column=col, sticky="w", padx=(0, 6), pady=4
        )
        entry = ttk.Entry(parent, textvariable=var, width=8)
        entry.grid(row=row, column=col + 1, sticky="w", padx=(0, 16), pady=4)
        self._param_entries.append(entry)

    def _set_status(self, state: str) -> None:
        colors = {
            "idle": (MUTED, "Idle"),
            "running": (GREEN, "Running"),
            "stopped": (RED, "Stopped"),
        }
        color, text = colors.get(state, (MUTED, "Idle"))
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
        self.status_label.configure(text=text)

    # ---- gift selection --------------------------------------------------
    def _load_thumb(self, path, size: int = 56):
        """Load ``path`` as a square-ish thumbnail PhotoImage (caller keeps ref)."""
        from PIL import Image, ImageTk

        img = Image.open(path).convert("RGBA")
        img.thumbnail((size, size))
        return ImageTk.PhotoImage(img)

    def _render_current_gift(self) -> None:
        if self.current_gift is None:
            self.gift_thumb.configure(
                image="", text="🎁", font=("Segoe UI", 26), fg=MUTED
            )
            self.gift_name_lbl.configure(text="No gift selected")
            self.gift_hint_lbl.configure(text="click to add one  ›")
            return
        self._thumb_photo = self._load_thumb(self.current_gift.icon_path, 56)
        self.gift_thumb.configure(image=self._thumb_photo, text="")
        self.gift_name_lbl.configure(text=self.current_gift.name)
        self.gift_hint_lbl.configure(text="click to change  ›")

    def _set_gift(self, gift: "gifts.Gift") -> None:
        self.current_gift = gift
        self._render_current_gift()
        self.log(f"Selected gift: {gift.name}")

    def _open_gift_picker(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Choose a gift")
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        win.bind("<Escape>", lambda _e: win.destroy())

        header = ttk.Frame(win)
        header.pack(fill="x", padx=16, pady=(14, 8))
        ttk.Label(header, text="Choose a gift", style="Title.TLabel").pack(side="left")
        ttk.Button(
            header,
            text="＋  Add gift",
            style="Accent.TButton",
            command=lambda: self._open_add_gift_dialog(win),
        ).pack(side="right")

        grid = ttk.Frame(win)
        grid.pack(padx=16, pady=(0, 16))

        if not self.gifts:
            ttk.Label(
                grid,
                text="No gifts yet.  Click  ＋ Add gift  to upload one.",
                style="Subtitle.TLabel",
            ).pack(padx=30, pady=30)

        self._picker_photos = []
        cols = 3
        cell_w, cell_h = 116, 138
        for i, g in enumerate(self.gifts):
            photo = self._load_thumb(g.icon_path, 72)
            self._picker_photos.append(photo)
            selected = g == self.current_gift
            border = ACCENT if selected else BORDER

            # Fixed-size tile so the grid stays even regardless of name length.
            cell = tk.Frame(
                grid,
                bg=SURFACE,
                cursor="hand2",
                highlightthickness=2,
                highlightbackground=border,
                highlightcolor=border,
                width=cell_w,
                height=cell_h,
            )
            cell.grid(row=i // cols, column=i % cols, padx=7, pady=7)
            cell.pack_propagate(False)

            thumb = tk.Label(cell, image=photo, bg=SURFACE)
            thumb.pack(pady=(16, 8))
            caption = tk.Label(
                cell,
                text=("✓  " + g.name) if selected else g.name,
                bg=SURFACE,
                fg=(ACCENT if selected else TEXT),
                font=(FONT_BOLD if selected else FONT_SM),
                wraplength=cell_w - 16,
                justify="center",
            )
            caption.pack()

            def on_enter(_e, c=cell, sel=selected):
                if not sel:
                    c.configure(highlightbackground=ACCENT, highlightcolor=ACCENT)

            def on_leave(_e, c=cell, sel=selected):
                if not sel:
                    c.configure(highlightbackground=BORDER, highlightcolor=BORDER)

            for child in (cell, thumb, caption):
                child.bind(
                    "<Button-1>",
                    lambda _e, gg=g, ww=win: (self._set_gift(gg), ww.destroy()),
                )
                child.bind("<Enter>", on_enter)
                child.bind("<Leave>", on_leave)

        # Centre the picker over the main window.
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        win.geometry(f"+{rx + (rw - w) // 2}+{ry + (rh - h) // 2}")

    # ---- add / upload a gift ---------------------------------------------
    def _open_add_gift_dialog(self, picker: "tk.Toplevel | None" = None) -> None:
        """Dialog to browse an icon PNG + a send-popup PNG and register a gift."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Add a gift")
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text="Add a gift", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 4)
        )
        ttk.Label(
            dlg,
            text="Two PNGs: the gift icon, and the hover popup with the Send button.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 10))

        name_var = tk.StringVar()
        icon_var = tk.StringVar()
        send_var = tk.StringVar()

        ttk.Label(dlg, text="Name", style="TLabel").grid(
            row=2, column=0, sticky="w", padx=16, pady=6
        )
        name_entry = ttk.Entry(dlg, textvariable=name_var, width=32)
        name_entry.grid(
            row=2, column=1, columnspan=2, sticky="we", padx=(0, 16), pady=6
        )

        def browse_row(row: int, label: str, var: tk.StringVar) -> None:
            ttk.Label(dlg, text=label, style="TLabel").grid(
                row=row, column=0, sticky="w", padx=16, pady=6
            )
            entry = ttk.Entry(dlg, textvariable=var, width=26, state="readonly")
            entry.grid(row=row, column=1, sticky="we", padx=(0, 8), pady=6)
            ttk.Button(
                dlg,
                text="Browse…",
                command=lambda: self._browse_png(var, name_var),
            ).grid(row=row, column=2, sticky="e", padx=(0, 16), pady=6)

        browse_row(3, "Gift icon", icon_var)
        browse_row(4, "Send popup", send_var)

        def save() -> None:
            self._save_gift(
                name_var.get(), icon_var.get(), send_var.get(), dlg, picker
            )

        btns = ttk.Frame(dlg)
        btns.grid(row=5, column=0, columnspan=3, sticky="e", padx=16, pady=(12, 14))
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="right")
        ttk.Button(
            btns, text="Save gift", style="Start.TButton", command=save
        ).pack(side="right", padx=(0, 8))
        dlg.columnconfigure(1, weight=1)

        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.bind("<Return>", lambda _e: save())
        name_entry.focus_set()

        # Centre over the main window.
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
        rw, rh = self.root.winfo_width(), self.root.winfo_height()
        dlg.geometry(f"+{rx + (rw - w) // 2}+{ry + (rh - h) // 2}")

    def _browse_png(self, var: tk.StringVar, name_var: tk.StringVar) -> None:
        path = filedialog.askopenfilename(
            title="Select a PNG",
            filetypes=[("PNG image", "*.png"), ("All files", "*.*")],
        )
        if not path:
            return
        var.set(path)
        # Prefill the name from the first file chosen, if still blank.
        if not name_var.get():
            stem = Path(path).stem
            if stem.endswith("-send"):
                stem = stem[: -len("-send")]
            name_var.set(stem.replace("-", " ").replace("_", " ").title())

    @staticmethod
    def _slug(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
        return slug

    def _save_gift(
        self,
        name: str,
        icon_path: str,
        send_path: str,
        dlg: "tk.Toplevel",
        picker: "tk.Toplevel | None",
    ) -> None:
        if not name.strip():
            messagebox.showwarning(APP_TITLE, "Enter a gift name.", parent=dlg)
            return
        if not icon_path or not send_path:
            messagebox.showwarning(
                APP_TITLE, "Choose both the icon and the send PNG.", parent=dlg
            )
            return
        slug = self._slug(name)
        if not slug:
            messagebox.showwarning(APP_TITLE, "Name has no usable characters.", parent=dlg)
            return

        dest_icon = gifts.ASSETS_DIR / f"{slug}.png"
        dest_send = gifts.ASSETS_DIR / f"{slug}-send.png"
        if dest_icon.exists() or dest_send.exists():
            if not messagebox.askyesno(
                APP_TITLE, f"'{slug}' already exists. Overwrite?", parent=dlg
            ):
                return
        try:
            gifts.ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(icon_path, dest_icon)
            shutil.copyfile(send_path, dest_send)
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not save gift:\n{exc}", parent=dlg)
            return

        self.gifts = gifts.discover()
        new = next((g for g in self.gifts if g.icon_path == dest_icon), None)
        if new is not None:
            self._set_gift(new)
        dlg.destroy()
        if picker is not None:
            picker.destroy()
            self._open_gift_picker()  # reopen to show the new gift

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
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n", self._tag_for(msg))
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        # Re-enable Start when the worker finishes.
        if self.worker is not None and not self.worker.is_alive():
            self.worker = None
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self._set_running(False)
            self._set_status("idle")
        self.root.after(100, self._drain_log)

    def refresh_windows(self) -> None:
        self.windows = capture.list_windows(skip_titles=(APP_TITLE,))
        labels = [f"{title}  [hwnd {hwnd}]" for hwnd, title in self.windows]
        self.window_combo["values"] = labels
        if labels:
            if self.window_combo.current() < 0:  # nothing valid selected yet
                self.window_combo.current(0)
        else:
            self.window_var.set("— no windows found — click ⟳ Refresh")

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
    def _set_running(self, running: bool) -> None:
        """Lock inputs that must not change while a send worker is active."""
        self._running = running
        state = "disabled" if running else "normal"
        self.window_combo.configure(state="disabled" if running else "readonly")
        self.refresh_btn.configure(state=state)
        self.dry_btn.configure(state=state)
        for entry in self._param_entries:
            entry.configure(state=state)

    def start(self) -> None:
        if self.worker is not None:
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

        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_running(True)
        self._set_status("running")
        self.log(
            f"Starting: gift={self.current_gift.name} count={count} "
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

    def stop(self) -> None:
        self.stop_event.set()
        self._set_status("stopped")
        self.log("Stop requested...")

    def dry_run(self) -> None:
        """Capture the selected window, detect without clicking, show an overlay.

        Capture + match run on a background thread so the UI stays responsive;
        the preview window is created back on the Tk thread via ``after``.
        """
        if self._running:
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
        self.dry_btn.configure(state="disabled")
        self.log(f"Dry-run ({gift.name}): detecting icon (no click)...")

        def work() -> None:
            try:
                image, _ = capture.capture_window(hwnd)
                icon_tpl = matcher.load_template(gift.icon_path)
                match = matcher.find(image, icon_tpl, threshold=threshold)
            except Exception as exc:  # noqa: BLE001 - surface any capture/match error
                self.log(f"Dry-run error: {exc}")
                self.root.after(0, lambda: self.dry_btn.configure(state="normal"))
                return
            if match is None:
                self.log("Dry-run: icon NOT found. Lower Threshold or check the window.")
                self.root.after(0, lambda: self.dry_btn.configure(state="normal"))
                return
            self.log(
                f"Dry-run: icon found at window ({match.cx},{match.cy}) "
                f"score {match.score:.2f}."
            )
            self.root.after(0, lambda: self._finish_dry_run(image, match))

        threading.Thread(target=work, daemon=True).start()

    def _finish_dry_run(self, image, match) -> None:
        self.dry_btn.configure(state="normal")
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

        win = tk.Toplevel(self.root)
        win.title("Dry-run preview")
        win.configure(bg=BG)
        photo = ImageTk.PhotoImage(preview)
        label = tk.Label(win, image=photo, bg=BG, bd=0)
        label.image = photo  # keep a reference
        label.pack(padx=10, pady=10)

    def _on_close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def launch() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
