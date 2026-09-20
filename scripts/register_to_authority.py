#!/usr/bin/env python3
"""Place one edited frame back onto its own native source frame.

The image tool returns a canvas larger than the one it was given and places the
sprite a fraction of a pixel away from where the native frame has it. Left
alone, that sub-pixel wander varies frame to frame and shows up as temporal
jitter that no per-frame gate can see. This script measures the offset on the
part of the sprite that is solid in the output and character in the source,
applies it as a pure translation, and unmixes the background colour out of the
soft edge.

Translation only. No scale, no rotation, no per-frame recentering: the offset
is measured against this frame's own mapped native frame, never against a
neighbour and never against a batch average.

Nothing here decides transparency. The source silhouette is used to choose
which pixels to measure on; the delivered alpha is the tool's, untouched.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as error:  # pragma: no cover - dependency guidance
    raise SystemExit(
        f"{error}. Install the skill's dependencies: "
        "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    )

from source_foreground import foreground_mask


# Limits calibrated on the 48-frame run of 2026-09-20; see the reasoning in
# references/failure-prevention.md.
MAX_SHIFT_PIXELS = 2.0          # observed max 0.594
MAX_QUADRANT_SPREAD = 0.40      # observed max 0.259; a 0.5% scale gives 0.626
MAX_REMAINING_SHIFT = 0.05      # observed 0.0000 on every frame
# Measured across the 48 delivered frames of 2026-09-20 against their own
# source silhouettes: -0.6% to +2.2%. The limit is deliberately far looser than
# that spread, because this gate is for a sprite that lost a limb or grew a
# halo, not for the few percent of honest disagreement between a chroma test
# and an anti-aliased alpha channel.
MAX_AREA_DEVIATION = 0.10
ALPHA_VISIBLE = 18              # silhouette threshold shared with the temporal gates
ALPHA_OPAQUE = 250              # the stable interior registration measures on
MIN_INTERIOR_PIXELS = 500


def luma(image: np.ndarray) -> np.ndarray:
    channels = image[:, :, :3].astype(np.float64)
    return 0.299 * channels[:, :, 0] + 0.587 * channels[:, :, 1] + 0.114 * channels[:, :, 2]


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        shifted = out.copy()
        shifted[1:, :] &= out[:-1, :]
        shifted[:-1, :] &= out[1:, :]
        shifted[:, 1:] &= out[:, :-1]
        shifted[:, :-1] &= out[:, 1:]
        out = shifted
    return out


def presmooth(image: np.ndarray) -> np.ndarray:
    """Two separable 1-2-1 passes. Flat cartoon fills carry no gradient of their
    own, so without this the fit has nothing to lock onto away from outlines."""
    out = image
    for _ in range(2):
        padded = np.pad(out, 1, mode="edge")
        out = (padded[:-2, 1:-1] + 2.0 * padded[1:-1, 1:-1] + padded[2:, 1:-1]) / 4.0
        padded = np.pad(out, 1, mode="edge")
        out = (padded[1:-1, :-2] + 2.0 * padded[1:-1, 1:-1] + padded[1:-1, 2:]) / 4.0
    return out


def sample_shifted(image: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Bilinear resample of `image` at (x + dx, y + dy)."""
    height, width = image.shape
    ys, xs = np.mgrid[0:height, 0:width]
    sx = np.clip(xs + dx, 0, width - 1)
    sy = np.clip(ys + dy, 0, height - 1)
    x0 = np.floor(sx).astype(int)
    y0 = np.floor(sy).astype(int)
    x1 = np.clip(x0 + 1, 0, width - 1)
    y1 = np.clip(y0 + 1, 0, height - 1)
    fx = sx - x0
    fy = sy - y0
    return (
        image[y0, x0] * (1 - fx) * (1 - fy)
        + image[y0, x1] * fx * (1 - fy)
        + image[y1, x0] * (1 - fx) * fy
        + image[y1, x1] * fx * fy
    )


def estimate_shift(
    target: np.ndarray, reference: np.ndarray, mask: np.ndarray, iterations: int = 4
) -> tuple[float, float]:
    """Translation-only Gauss-Newton. Returns the (dx, dy) that brings `target`
    onto `reference`. Recovers known shifts to about 0.008 px on real frames."""
    ref = presmooth(reference)
    tgt = presmooth(target)
    gy, gx = np.gradient(ref)
    gxm, gym = gx[mask], gy[mask]
    a11 = float((gxm * gxm).sum())
    a12 = float((gxm * gym).sum())
    a22 = float((gym * gym).sum())
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-9:
        return (float("nan"), float("nan"))
    dx = dy = 0.0
    for _ in range(iterations):
        error = (sample_shifted(tgt, dx, dy) - ref)[mask]
        b1 = float((gxm * error).sum())
        b2 = float((gym * error).sum())
        step_x = -(a22 * b1 - a12 * b2) / det
        step_y = -(a11 * b2 - a12 * b1) / det
        dx += step_x
        dy += step_y
        if math.hypot(step_x, step_y) < 1e-4:
            break
    return (dx, dy)


def quadrant_spread(
    target: np.ndarray, reference: np.ndarray, mask: np.ndarray
) -> float:
    """Spread of per-quadrant shifts. A pure translation moves every quadrant
    the same way; scale or warp does not."""
    height, width = mask.shape
    shifts = []
    for ys, xs in (
        (slice(0, height // 2), slice(0, width // 2)),
        (slice(0, height // 2), slice(width // 2, width)),
        (slice(height // 2, height), slice(0, width // 2)),
        (slice(height // 2, height), slice(width // 2, width)),
    ):
        sub = mask[ys, xs]
        if int(sub.sum()) < 200:
            continue
        qdx, qdy = estimate_shift(target[ys, xs], reference[ys, xs], sub, iterations=3)
        if not math.isnan(qdx):
            shifts.append((qdx, qdy))
    if len(shifts) < 2:
        return float("nan")
    arr = np.array(shifts)
    return float(np.hypot(arr[:, 0].std(), arr[:, 1].std()))


def premultiplied_shift_and_fit(
    image: np.ndarray, dx: float, dy: float, canvas: tuple[int, int], pad: int = 8
) -> np.ndarray:
    """Translate and scale to the contract canvas in one resample.

    The shift rides on the resize as a source window rather than happening
    first: resampling twice softens the outline and, worse, leaves the sprite
    up to 0.2px from where it was asked to go, which is most of the drift
    budget spent on the arithmetic rather than on the image. The window is
    padded because it may start left of or above the origin.

    Compositing in premultiplied space keeps colour from bleeding out of the
    transparent side of the outline; a straight RGBA resize would drag the
    background toward the sprite edge.
    """
    height, width = image.shape[:2]
    alpha = image[:, :, 3].astype(np.float64) / 255.0
    premultiplied = np.dstack(
        [image[:, :, channel].astype(np.float64) * alpha for channel in range(3)]
        + [alpha * 255.0]
    )
    margin = max(pad, int(abs(dx)) + 2, int(abs(dy)) + 2)
    padded = np.pad(premultiplied, ((margin, margin), (margin, margin), (0, 0)))
    resized = np.asarray(
        Image.fromarray(np.clip(padded, 0, 255).astype(np.uint8), "RGBA").resize(
            canvas,
            Image.LANCZOS,
            box=(margin + dx, margin + dy, margin + dx + width, margin + dy + height),
        ),
        dtype=np.float64,
    )
    out_alpha = np.clip(resized[:, :, 3], 0, 255)
    safe = np.where(out_alpha > 0, out_alpha / 255.0, 1.0)
    straight = np.dstack(
        [np.clip(resized[:, :, c] / safe, 0, 255) for c in range(3)] + [out_alpha]
    )
    straight[out_alpha <= 0, :3] = 0
    return straight.astype(np.uint8)


def register(
    edited: np.ndarray,
    authority: np.ndarray,
    max_shift: float = MAX_SHIFT_PIXELS,
    max_spread: float = MAX_QUADRANT_SPREAD,
    max_remaining: float = MAX_REMAINING_SHIFT,
    max_area_deviation: float = MAX_AREA_DEVIATION,
) -> tuple[np.ndarray | None, dict[str, object]]:
    """Register `edited` onto its native `authority` frame.

    Returns (image, record); image is None when the frame is rejected.
    """
    canvas = (authority.shape[1], authority.shape[0])
    errors: list[str] = []
    record: dict[str, object] = {
        "canvas": list(canvas),
        "inputSize": [edited.shape[1], edited.shape[0]],
    }

    scale_x = edited.shape[1] / authority.shape[1]
    scale_y = edited.shape[0] / authority.shape[0]

    # Measure at authority resolution so the offset is in canvas pixels.
    measurable = np.asarray(
        Image.fromarray(edited, "RGBA").resize(canvas, Image.LANCZOS), dtype=np.uint8
    )
    # Measure only where the output is solid and the source says character:
    # the eroded overlap excludes the soft edge, whose colour is about to
    # change, and excludes the screen, whose flat green has no gradient to
    # register against.
    source_mask = foreground_mask(authority)
    interior = erode(source_mask & (measurable[:, :, 3] >= ALPHA_OPAQUE), 2)
    record["interiorPixels"] = int(interior.sum())
    if record["interiorPixels"] < MIN_INTERIOR_PIXELS:
        errors.append("no stable opaque interior to register against")
        record["errors"] = errors
        record["status"] = "repair-needed"
        return None, record

    reference = luma(authority)
    target = luma(measurable)
    dx, dy = estimate_shift(target, reference, interior)
    if math.isnan(dx):
        errors.append("registration did not converge")
        record["errors"] = errors
        record["status"] = "repair-needed"
        return None, record

    spread = quadrant_spread(target, reference, interior)
    remaining_dx, remaining_dy = estimate_shift(
        sample_shifted(target, dx, dy), reference, interior
    )
    remaining = math.hypot(remaining_dx, remaining_dy)
    magnitude = math.hypot(dx, dy)
    record.update(
        {
            "dx": round(dx, 4),
            "dy": round(dy, 4),
            "shiftPixels": round(magnitude, 4),
            "quadrantSpreadPixels": None if math.isnan(spread) else round(spread, 4),
            "remainingShiftPixels": round(remaining, 4),
            "method": "translation-only-gauss-newton",
            "authorityKind": "selected-native-source-frame",
        }
    )

    if magnitude > max_shift:
        errors.append(f"offset {magnitude:.3f}px exceeds {max_shift}px")
    if not math.isnan(spread) and spread > max_spread:
        errors.append(
            f"per-quadrant shift spread {spread:.3f}px exceeds {max_spread}px; "
            "this is scale or warp, not translation"
        )
    if remaining > max_remaining:
        errors.append(f"registration left {remaining:.3f}px unresolved")

    registered = premultiplied_shift_and_fit(edited, dx * scale_x, dy * scale_y, canvas)

    # There is no parent outline to clamp to any more, so the source silhouette
    # is a gate rather than a mask: a sprite far larger or smaller than the
    # character in its own source frame has lost or gained something, and that
    # is a rejection, not something to trim into shape.
    source_area = int(source_mask.sum())
    final_area = int(np.count_nonzero(registered[:, :, 3] > ALPHA_VISIBLE))
    deviation = (final_area - source_area) / max(1, source_area)
    record.update(
        {
            "sourceArea": source_area,
            "visibleArea": final_area,
            "areaDeviation": round(deviation, 5),
        }
    )
    if abs(deviation) > max_area_deviation:
        errors.append(
            f"visible area is {deviation:+.2%} against the source silhouette, "
            f"outside {max_area_deviation:.0%}"
        )

    record["errors"] = errors
    record["status"] = "accepted" if not errors else "repair-needed"
    return (registered if not errors else None), record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edited", type=Path, help="raw image-tool output")
    parser.add_argument("authority", type=Path, help="mapped native source frame")
    parser.add_argument("output", type=Path, help="registered, decontaminated PNG")
    parser.add_argument("--record", type=Path, help="write the measurement JSON here")
    parser.add_argument("--max-shift-pixels", type=float, default=MAX_SHIFT_PIXELS)
    parser.add_argument("--max-quadrant-spread", type=float, default=MAX_QUADRANT_SPREAD)
    parser.add_argument("--max-remaining-shift", type=float, default=MAX_REMAINING_SHIFT)
    parser.add_argument("--max-area-deviation", type=float, default=MAX_AREA_DEVIATION)
    args = parser.parse_args()

    edited = np.asarray(Image.open(args.edited).convert("RGBA"), dtype=np.uint8)
    authority = np.asarray(Image.open(args.authority).convert("RGBA"), dtype=np.uint8)
    registered, record = register(
        edited,
        authority,
        max_shift=args.max_shift_pixels,
        max_spread=args.max_quadrant_spread,
        max_remaining=args.max_remaining_shift,
        max_area_deviation=args.max_area_deviation,
    )
    record["edited"] = str(args.edited)
    record["authority"] = str(args.authority)

    if registered is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(registered, "RGBA").save(args.output, format="PNG", optimize=False)
        record["output"] = str(args.output)
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return 0 if record["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
