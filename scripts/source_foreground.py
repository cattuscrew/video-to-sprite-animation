#!/usr/bin/env python3
"""Where the character is in a native source frame -- for measurement only.

A native frame is opaque everywhere, so nothing in it says which pixels are
character and which are screen. Registration needs that answer to know what to
align, and the identity gate needs it to know which frame an output resembles.

This is not background removal and must never write a delivered alpha channel.
Built-in GPT Image decides transparency; this only decides what to *measure*.
Keeping the two apart matters: a keyer good enough to measure with is not good
enough to ship, and the moment one is used for the other the skill has quietly
grown the background-removal branch it forbids.

The test is green excess, `G - max(R, B)`, not distance to the background
colour, because the character wears green. On the reference source those two
populations separate cleanly: the tunic reaches 77 at the 99th percentile while
the screen sits at 162 at its 1st, so a threshold of 120 misreads 0.06% of
character pixels and 0.20% of screen pixels.
"""

from __future__ import annotations

import numpy as np

# Measured on rebuild-24fps/source-square, all 48 frames: border median
# (16, 245, 50), varying by at most 2 levels across the batch.
REFERENCE_BACKGROUND = (16, 245, 50)
GREEN_EXCESS_THRESHOLD = 120.0


def green_excess(rgb: np.ndarray) -> np.ndarray:
    """How much greener than its own red and blue each pixel is."""
    values = rgb[:, :, :3].astype(np.int16)
    return values[:, :, 1] - np.maximum(values[:, :, 0], values[:, :, 2])


def is_flat_background(image: np.ndarray) -> bool:
    """True when the image carries no usable alpha, i.e. a native frame.

    A native frame converted to RGBA is opaque everywhere, so its alpha channel
    cannot be used as a silhouette. Detecting that here keeps every caller from
    having to know which kind of image it was handed.
    """
    return bool((image[:, :, 3] >= 255).all())


def foreground_mask(
    image: np.ndarray, threshold: float = GREEN_EXCESS_THRESHOLD
) -> np.ndarray:
    """The character's silhouette, from alpha when there is one, else chroma."""
    if not is_flat_background(image):
        return image[:, :, 3] > 18
    return green_excess(image) <= threshold
