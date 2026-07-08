# Add a custom gift

Teach GiftDrop to send any gift by giving it two screenshots: the **icon** (as it
sits in the gift tray) and the **hover popup** (the box with the **Send** button).
Flow: `crop 2 PNGs → Store gift → Add gift → Save → it appears in the picker`.

## Prereqs

- GiftDrop running (`python main.py`, or the built `.exe`).
- A screenshot tool that crops (Windows **Snipping Tool**: `Win`+`Shift`+`S`).
- The gift page open at the **same zoom** you'll run the bot at.

## Worked example — add a "Rose" gift

### 1. Screenshot the gift tray

Open the TikTok Live gift page. Screenshot it at your normal zoom.

You get one image showing the Rose icon in the tray.

### 2. Crop the icon → `rose.png`

Crop **tightly** around just the Rose icon and save it as `rose.png`.

> The filename becomes the display name. `rose.png` shows as **Rose** in the app.
> `red-rose.png` shows as **Red Rose**. Underscores/dashes become spaces; only the
> first ~2 words (≤16 chars) are used.

### 3. Crop the hover popup → `rose-send.png`

Hover the Rose icon so its popup appears, screenshot again, and crop the whole
popup — **the icon plus the Send button** — saved as `rose-send.png`.

You now have two files: `rose.png` and `rose-send.png`. Any name works for the
popup file; only the icon file drives the display name.

### 4. In GiftDrop, click **Store gift**

Top of the gift panel, click the **Store gift** button.

The gift store window opens, listing every gift you have.

### 5. Click **Add gift**

The **Add a gift** dialog opens with two rows: **Gift icon** and **Send popup**.

### 6. Browse both PNGs

Click **Browse** on **Gift icon** → pick `rose.png`.
Click **Browse** on **Send popup** → pick `rose-send.png`.

Both file paths show in the dialog.

### 7. Click **Save gift**

GiftDrop copies both PNGs into its assets folder and closes the dialog.

You get a log line `Stored gift: Rose`, and **Rose** is now pinned to the gift bar
(or, if the bar is full, sitting in the store ready to pin). Select it and run.

## Alternative — drop files in, no dialog

Skip the UI entirely: copy the two PNGs straight into the assets folder, named
`<name>.png` and `<name>-send.png`. GiftDrop finds any such pair on the next
launch.

- **Running from source:** `assets/` in the repo.
- **Built `.exe`:** `%APPDATA%\GiftDrop\assets\`.

## Gotchas

- **Only the icon filename names the gift.** Want it called "Rose"? Name the icon
  file `rose.png`. The popup file's name is ignored (the `-send` is stripped).
- **The popup crop must include the Send button.** GiftDrop re-detects the popup
  to locate Send; crop too tight and the click target is missing.
- **Crop at run zoom.** Multi-scale matching tolerates some drift, but a template
  cropped at the same zoom you run at matches most reliably. If detection misses,
  re-crop at the zoom you actually use, or nudge **Threshold** down from `0.8`.
- **Both PNGs are required.** Leave one blank and Save warns "Choose both the icon
  and the send PNG."
- **Store cap is 20 gifts.** Full store blocks Add gift — delete one first.
- **Name collisions auto-rename.** A second `rose.png` is stored as `rose-2.png`
  (shown as **Rose 2**), so nothing overwrites.
