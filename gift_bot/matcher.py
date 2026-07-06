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
) -> Match | None:
    """Find ``template`` in ``haystack``; return the best :class:`Match` or ``None``.

    The best match across all scales is returned only if its correlation score
    meets ``threshold``.
    """
    hay = _to_gray(haystack)
    hay_h, hay_w = hay.shape[:2]
    best: Match | None = None

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
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if best is None or max_val > best.score:
            left, top = int(max_loc[0]), int(max_loc[1])
            best = Match(
                cx=left + t_w // 2,
                cy=top + t_h // 2,
                left=left,
                top=top,
                w=t_w,
                h=t_h,
                score=float(max_val),
            )

    if best is not None and best.score >= threshold:
        return best
    return None
