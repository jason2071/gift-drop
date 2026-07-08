# GiftDrop

A Windows desktop bot that auto-sends a chosen gift on a TikTok Live gift page.
It detects the gift icon on any open window (even when the window is covered by
others), hovers it to reveal the popup, and clicks **Send** — repeated a
configurable number of times at a configurable interval.

Ships with the **Love You** gift, and you can **add your own gifts** from the UI
(no code change) — see [Gifts](#gifts).

## How it works

1. **Detect (occlusion-proof):** captures the chosen window with the Win32
   `PrintWindow` + `PW_RENDERFULLCONTENT` API, which grabs the content even when
   the window is behind others, then finds the selected gift's icon with
   multi-scale OpenCV template matching.
2. **Hover:** brings the window to the foreground and moves the real cursor onto
   the icon so the Send popup appears (a genuine hover is required for TikTok's
   web UI).
3. **Confirm + click:** re-detects the gift's popup template to confirm it, then
   clicks the **Send** button inside it.
4. Repeats `Count` times, `Interval` seconds apart. If the icon is not found
   after `Retries` (default 3) attempts, it **stops**.

## Install

```powershell
pip install -r requirements.txt
```

Requires Python 3.10+ on Windows.

## Run

```powershell
python main.py
```

1. Open the TikTok Live gift page (browser tab or app) so the gift icon is
   visible. It may be partially behind another window.
2. Pick the window in the **Target window** dropdown (click **Refresh** if it is
   not listed).
3. In the **Gift to send** card, confirm the gift — click a pinned thumbnail to
   select it, or click **Store gift** to pick from your library or add a new gift.
4. Click **Dry-run** first: it captures and detects the icon **without clicking**
   and shows a preview with a red box on the match. Lower **Threshold** if it
   reports "not found".
5. Set **Interval** and **Count**, then click **Start**. Use **Stop** to abort.

## Gifts

A *gift* is a pair of PNG templates in `assets/`:

| File | What it is |
|------|------------|
| `<name>.png` | The gift **icon** as it appears in the gift tray. |
| `<name>-send.png` | The hover **popup** that contains the Send button. |

Any pair found in `assets/` shows up automatically in the picker.

**Add a gift from the UI:** click **Store gift** → **Add gift** → **Browse** the
icon PNG and the send-popup PNG → **Save gift**. The files are copied into the
assets dir and the gift is pinned and ready. There's no name field — the gift's
label comes from the **icon file's name** (`rose.png` → **Rose**), so name that
file before uploading. Step-by-step walkthrough: [docs/add-a-gift.md](docs/add-a-gift.md).

**Capturing templates:** screenshot the gift page at the zoom you'll run at, crop
the gift icon tightly for `<name>.png`, and crop the hover popup (icon + Send
button) for `<name>-send.png`.

## Controls

| Field | Meaning |
|-------|---------|
| Target window | Which window to search/click. |
| Gift to send | The gift to detect and send; click to change or add. |
| Interval (s) | Delay between each Send. |
| Count | How many gifts to send. |
| Threshold | Match confidence 0–1 (default 0.8). Lower = more lenient. |
| Retries | Detection attempts before stopping (default 3). |
| Dry-run | Detect + preview only, no clicking. |

## Updating

The packaged app checks GitHub for a newer release on launch (and when you click
the version label in the header). If one is found it offers to download the new
`.exe` and restart into it — no manual re-download or re-install. Your gifts and
settings live under `%APPDATA%/GiftDrop/` and are kept across updates.

## Notes & safety

- **Foreground clicking takes over the mouse** while running. Do not use the PC
  during a run. **Failsafe:** slam the cursor into any screen corner to abort
  instantly; or click **Stop**.
- **If detection misses**, it is almost always display scaling. The bot already
  tries several scales; use **Dry-run** to tune **Threshold**, or make sure the
  gift icon is fully visible at the same zoom as when the templates were captured.
- **More precise Send click (optional):** drop a cropped `send-button.png` (just
  the Send button) into `assets/`. If present, the bot matches it directly instead
  of clicking a computed offset inside the popup.

## Project layout

```
gift-drop/
├─ main.py                    # Entry point; sets DPI awareness, launches GUI.
├─ requirements.txt
├─ README.md
├─ assets/                    # Gift templates: <name>.png + <name>-send.png pairs.
│  ├─ love-you.png            # Gift icon template.
│  └─ love-you-send.png       # Popup + Send template.
└─ gift_bot/                  # Application package.
   ├─ __init__.py             # Exposes launch().
   ├─ gui.py                  # tkinter UI (light theme, gift picker, Start/Stop, Dry-run, log).
   ├─ gifts.py                # Gift catalogue: discovers icon/popup pairs in assets/.
   ├─ bot.py                  # Orchestration: detect → hover → confirm → click Send.
   ├─ capture.py              # Window enumeration + occlusion-proof PrintWindow capture.
   ├─ matcher.py              # Multi-scale OpenCV template matching.
   └─ clicker.py              # Foreground handling + real mouse hover/click.
```
