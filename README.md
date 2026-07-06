# GiftDrop

A Windows desktop bot that auto-sends the **love-you** gift on a TikTok Live gift
page. It detects the gift icon on any open window (even when the window is
covered by others), hovers it to reveal the popup, and clicks **Send** — repeated
a configurable number of times at a configurable interval.

## How it works

1. **Detect (occlusion-proof):** captures the chosen window with the Win32
   `PrintWindow` + `PW_RENDERFULLCONTENT` API, which grabs the content even when
   the window is behind others, then finds `love-you.png` with multi-scale
   OpenCV template matching.
2. **Hover:** brings the window to the foreground and moves the real cursor onto
   the icon so the Send popup appears (a genuine hover is required for TikTok's
   web UI).
3. **Confirm + click:** re-detects `love-you-send.png` to confirm the popup, then
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
3. Click **Dry-run** first: it captures and detects the icon **without clicking**
   and shows a preview with a red box on the match. Lower **Threshold** if it
   reports "not found".
4. Set **Interval** and **Count**, then click **Start**. Use **Stop** to abort.

## Controls

| Field | Meaning |
|-------|---------|
| Target window | Which window to search/click. |
| Interval (s) | Delay between each Send. |
| Count | How many gifts to send. |
| Threshold | Match confidence 0–1 (default 0.8). Lower = more lenient. |
| Retries | Detection attempts before stopping (default 3). |
| Dry-run | Detect + preview only, no clicking. |

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
macro-click/
├─ main.py                    # Entry point; sets DPI awareness, launches GUI.
├─ requirements.txt
├─ README.md
├─ assets/
│  ├─ love-you.png            # Gift icon template (38×38).
│  └─ love-you-send.png       # Popup + Send template (106×112).
└─ gift_bot/                  # Application package.
   ├─ __init__.py             # Exposes launch().
   ├─ gui.py                  # tkinter UI (dropdown, fields, Start/Stop, Dry-run, log).
   ├─ bot.py                  # Orchestration: detect → hover → confirm → click Send.
   ├─ capture.py              # Window enumeration + occlusion-proof PrintWindow capture.
   ├─ matcher.py              # Multi-scale OpenCV template matching.
   └─ clicker.py              # Foreground handling + real mouse hover/click.
```
