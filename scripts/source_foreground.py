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


# --------------------------------------------------------------------- materials

# Colour flicker is per material, not per frame. The tunic drifts one way while
# the shield drifts the other, so any measure that averages the character
# cancels them: on a delivered sequence the materials swung up to 16.4 levels
# between neighbours while the interior mean moved 1.47. Everything below works
# per material for that reason.

MATERIAL_BIN = 24          # quantisation step when discovering materials
MIN_MATERIAL_PIXELS = 300  # below this a region cannot give a stable mean
MATERIAL_MERGE_DISTANCE = 30.0  # centres closer than this are one material


def discover_materials(
    natives: "list[np.ndarray]", limit: int = 8, erode_radius: int = 3
) -> np.ndarray:
    """Material colours, taken from the native frames rather than the outputs.

    Clustering the output is what makes a per-material fit dangerous: a
    mis-clustered region gets recoloured, which is a worse defect than the
    flicker being corrected. The native frames are the authority, they are
    stable, and registration already pins each output onto them, so the regions
    they define transfer directly.

    Returns an array of RGB centres, most common first.
    """
    from collections import Counter

    tally: Counter = Counter()
    sums: dict[int, np.ndarray] = {}
    for native in natives:
        mask = erode(foreground_mask(native), erode_radius)
        if not mask.any():
            continue
        rgb = native[:, :, :3][mask].astype(np.int64)
        keys = (rgb // MATERIAL_BIN) @ np.array([10_000, 100, 1])
        for key, count in Counter(keys.tolist()).items():
            tally[key] += count
        for key in set(keys.tolist()):
            chosen = rgb[keys == key]
            sums[key] = sums.get(key, np.zeros(3)) + chosen.sum(axis=0)

    centres: list[np.ndarray] = []
    weights: list[float] = []
    for key, count in tally.most_common():
        if count < MIN_MATERIAL_PIXELS:
            continue
        centre = sums[key] / count
        # A quantisation bin boundary can cut one material in two. Merge a
        # centre into a near neighbour rather than giving one material two
        # independent corrections computed from half its pixels each.
        merged = False
        for index, existing in enumerate(centres):
            if float(np.linalg.norm(existing - centre)) < MATERIAL_MERGE_DISTANCE:
                total = weights[index] + count
                centres[index] = (existing * weights[index] + centre * count) / total
                weights[index] = total
                merged = True
                break
        if not merged:
            centres.append(centre)
            weights.append(float(count))
        if len(centres) >= limit:
            break
    return np.array(centres) if centres else np.zeros((0, 3))


def assign_materials(native: np.ndarray, materials: np.ndarray) -> np.ndarray:
    """Label every pixel by the material its NATIVE colour is closest to.

    Assignment comes from the source, never from the output being corrected, so
    an output whose colour has drifted cannot be assigned to the wrong material
    and then "corrected" further in the wrong direction.

    Returns an int array; -1 where the native is background.
    """
    labels = np.full(native.shape[:2], -1, dtype=np.int16)
    if materials.size == 0:
        return labels
    mask = foreground_mask(native)
    if not mask.any():
        return labels
    rgb = native[:, :, :3][mask].astype(np.float64)
    distance = ((rgb[:, None, :] - materials[None, :, :]) ** 2).sum(axis=2)
    labels[mask] = distance.argmin(axis=1).astype(np.int16)
    return labels


def erode(mask: "np.ndarray", radius: int) -> "np.ndarray":
    """Local copy so this module does not import the registration script."""
    out = mask.copy()
    for _ in range(radius):
        shifted = out.copy()
        shifted[1:, :] &= out[:-1, :]
        shifted[:-1, :] &= out[1:, :]
        shifted[:, 1:] &= out[:, :-1]
        shifted[:, :-1] &= out[:, 1:]
        out = shifted
    return out
