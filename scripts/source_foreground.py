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


def unmix(
    image: np.ndarray,
    background: tuple[int, int, int],
    low: int = 18,
    high: int = 250,
) -> tuple[np.ndarray, int]:
    """Remove background colour from partial-alpha pixels. Alpha is untouched.

    A soft edge pixel holds `C = aF + (1-a)B`: the character's colour mixed
    with whatever was behind it. Solving for `F` recovers the colour the pixel
    would have had against nothing, which is what a transparent PNG is supposed
    to store. Without this the rim keeps the screen's colour and reads as a
    fringe over any dark background -- invisible on the checkerboard the proof
    is usually reviewed on.

    Only the `low < alpha < high` band is touched. Fully opaque pixels have no
    background in them to remove, and fully transparent ones are not drawn.
    """
    out = image.copy()
    alpha = image[:, :, 3].astype(np.float32) / 255.0
    band = (image[:, :, 3] > low) & (image[:, :, 3] < high)
    if not band.any():
        return out, 0

    a = alpha[band][:, None]
    observed = image[:, :, :3][band].astype(np.float32)
    screen = np.array(background, dtype=np.float32)[None, :]
    recovered = (observed - (1.0 - a) * screen) / np.maximum(a, 1e-3)

    # Unmixing amplifies noise as alpha falls, so a thin rim can solve to an
    # impossible colour. Clamp to gamut, then cap green against the pixel's own
    # red and blue: the character never out-greens itself the way the screen
    # does, and an uncapped solve leaves a lime edge on the darkest pixels.
    recovered = np.clip(recovered, 0.0, 255.0)
    cap = np.maximum(recovered[:, 0], recovered[:, 2])
    recovered[:, 1] = np.minimum(recovered[:, 1], cap)

    out[:, :, :3][band] = np.rint(recovered).astype(np.uint8)
    moved = int((np.abs(recovered - observed) > 1.0).any(axis=1).sum())
    return out, moved


def parse_background(raw: str) -> tuple[int, int, int]:
    """Parse "R,G,B", rejecting anything that is not three 0-255 integers."""
    parts = [piece.strip() for piece in raw.split(",")]
    if len(parts) != 3:
        raise ValueError(f"background must be R,G,B; got {raw!r}")
    values = []
    for piece in parts:
        value = int(piece)
        if not 0 <= value <= 255:
            raise ValueError(f"background channel out of range: {value}")
        values.append(value)
    return (values[0], values[1], values[2])
