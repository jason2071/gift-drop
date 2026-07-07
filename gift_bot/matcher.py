"""Multi-scale template matching with OpenCV.

Templates are saved at one DPI/render scale, but the live window may be rendered
at a different scale (Windows display scaling, browser zoom). Trying several
scales makes detection robust to that drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

DEFAULT_SCALES = (1.0, 0.9, 1.1, 0.8, 1.25, 0.75, 1.5)


@dataclass(frozen=True)
class Match:
    """A template match result, in the coordinate space of the searched image."""

    cx: int  # center x
    cy: int  # center y
    left: int  # matched region top-left x
    top: int  # matched region top-left y
    w: int  # matched (scaled) template width
    h: int  # matched (scaled) template height
    score: float


def load_template(path: str | Path) -> np.ndarray:
    """Load a template image as a grayscale numpy array."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"template not found or unreadable: {path}")
    return img


def _to_gray(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def find(
    haystack: Image.Image,
    template: np.ndarray,
    threshold: float = 0.8,
    scales: tuple[float, ...] = DEFAULT_SCALES,
    roi_top: float = 0.0,
    prefer: str = "score",
) -> Match | None:
    """Find ``template`` in ``haystack``; return one :class:`Match` or ``None``.

    Only matches whose correlation score meets ``threshold`` are considered.

    ``roi_top`` (0.0-1.0) restricts the search to the bottom band of the image,
    starting at that fraction of the height, so callers can drop the live-stream
    overlay near the top of the window. Match coordinates are always returned in
    full-image space.

    ``prefer`` chooses which qualifying match wins:

    * ``"score"`` -- the single highest-scoring match (default).
    * ``"bottom"`` -- the lowest match on screen. The same gift appears in the
      top overlay and in the "X sent <gift>" toasts, but the interactive gift
      tray is always docked at the very bottom, so the bottom-most instance is
      the real target regardless of which scores highest.
    """
    hay = _to_gray(haystack)
    full_h = hay.shape[0]
    y0 = max(0, min(full_h - 1, int(full_h * roi_top))) if roi_top > 0.0 else 0
    if y0:
        hay = hay[y0:, :]
    hay_h, hay_w = hay.shape[:2]

    candidates: list[Match] = []
    for scale in scales:
        t_w = max(1, int(round(template.shape[1] * scale)))
        t_h = max(1, int(round(template.shape[0] * scale)))
        if t_w > hay_w or t_h > hay_h:
            continue
        scaled = (
            template
            if scale == 1.0
            else cv2.resize(template, (t_w, t_h), interpolation=cv2.INTER_AREA)
        )
        res = cv2.matchTemplate(hay, scaled, cv2.TM_CCOEFF_NORMED)

        if prefer == "bottom":
            peaks = _peaks(res, threshold, t_w, t_h)
        else:
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            peaks = [(int(max_loc[1]), int(max_loc[0]), float(max_val))]

        for top_local, left, score in peaks:
            top = top_local + y0
            candidates.append(
                Match(
                    cx=left + t_w // 2,
                    cy=top + t_h // 2,
                    left=left,
                    top=top,
                    w=t_w,
                    h=t_h,
                    score=score,
                )
            )

    qualifying = [c for c in candidates if c.score >= threshold]
    if not qualifying:
        return None

    if prefer == "bottom":
        # Lowest instance wins; among its per-scale duplicates keep the best score.
        max_cy = max(c.cy for c in qualifying)
        band = [c for c in qualifying if max_cy - c.cy <= c.h * 0.5]
        return max(band, key=lambda c: c.score)
    return max(qualifying, key=lambda c: c.score)


def _peaks(
    res: np.ndarray, threshold: float, t_w: int, t_h: int
) -> list[tuple[int, int, float]]:
    """Distinct match peaks ``>= threshold`` as ``(top, left, score)``.

    Greedy non-max suppression collapses the correlation blob around each real
    match (and near-duplicate hits at adjacent scales) to one point, so multiple
    on-screen instances are reported separately instead of as one big smear.
    """
    ys, xs = np.where(res >= threshold)
    if ys.size == 0:
        return []
    scores = res[ys, xs]
    order = np.argsort(scores)[::-1]
    min_dy, min_dx = t_h * 0.6, t_w * 0.6
    kept: list[tuple[int, int, float]] = []
    for i in order:
        y, x, s = int(ys[i]), int(xs[i]), float(scores[i])
        if any(abs(ky - y) < min_dy and abs(kx - x) < min_dx for ky, kx, _ in kept):
            continue
        kept.append((y, x, s))
    return kept
