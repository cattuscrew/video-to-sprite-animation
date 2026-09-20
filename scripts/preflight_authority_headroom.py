#!/usr/bin/env python3
"""Measure the source sequence's own motion before setting limits on outputs.

A temporal limit is only meaningful next to the motion it governs. Set it from
a default and it can be tighter than the animation itself, so honest frames
fail; set it from a previous run's outputs and it inherits that run's jitter as
if it were the subject's movement.

So measure the authority. These are the numbers the animation actually makes,
with no processing in between: whatever an output does, this is the floor it
has to clear, and the gap between the two is all the room a per-frame error has
to live in.

This also reports the anatomical pivot, because the contract needs one and
guessing it is how a contract ends up tighter than its own authority. The pivot
is measured across the bottom rows of the silhouette -- where the character
meets the ground -- not across the whole bounding box. On the reference source
the contact pivot sits at x=520.5 in all 48 frames while the box centre wanders
between 351 and 360, because a held sword and a shield pull the box sideways
and the boots do not move.

Prints a table and writes JSON. It decides nothing: the limits it suggests go
to the user as a question, and a transition with too little headroom is listed
explicitly in `approvedTemporalTransitions` rather than answered by relaxing a
limit for the whole batch.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as error:  # pragma: no cover - dependency guidance
    raise SystemExit(
        f"{error}. Install the skill's dependencies: "
        "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    )

from register_to_authority import erode
from source_foreground import foreground_mask

# How much of the limit the authority's own motion is allowed to use before the
# transition is worth putting to the user. At 0.5 a per-frame error has as much
# room as the animation does.
HEADROOM_FRACTION = 0.5

# How many rows above the lowest pixel count as ground contact.
CONTACT_ROWS = 10


def measure(path: Path) -> dict[str, object]:
    image = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
    mask = foreground_mask(image)
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return {}
    left, right, top, bottom = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    interior = erode(mask, 2)
    colour = (
        image[:, :, :3][interior].astype(np.float64).mean(axis=0)
        if int(interior.sum()) >= 500
        else None
    )
    contact = mask[max(0, bottom - CONTACT_ROWS + 1) : bottom + 1]
    _, contact_xs = np.nonzero(contact)
    root = (
        float(contact_xs.min() + contact_xs.max()) / 2.0
        if contact_xs.size
        else (left + right) / 2.0
    )
    return {
        "centroid": (float(xs.mean()), float(ys.mean())),
        "box": (right - left + 1, bottom - top + 1),
        "area": int(mask.sum()),
        "pivot": (root, float(bottom)),
        "colour": colour,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="source-frame-manifest.json")
    parser.add_argument("output", type=Path, help="where to write the headroom JSON")
    parser.add_argument("--max-centroid-step-pixels", type=float, default=2.0)
    parser.add_argument("--max-centroid-acceleration-pixels", type=float, default=2.0)
    parser.add_argument("--max-bbox-size-step-pixels", type=float, default=12.0)
    parser.add_argument("--max-bbox-size-acceleration-pixels", type=float, default=16.0)
    parser.add_argument("--max-visible-area-step-ratio", type=float, default=0.03)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    directory = Path(manifest["sourceFramesDirectory"])
    records = manifest.get("frameMapping", [])

    frames: list[tuple[int, dict[str, object]]] = []
    missing: list[int] = []
    for record in records:
        number = int(record["outputFrame"])
        path = directory / str(record["sourceFile"])
        if not path.is_file():
            missing.append(number)
            continue
        found = measure(path)
        if found:
            frames.append((number, found))

    if len(frames) < 3:
        raise SystemExit("need at least three readable source frames")

    numbers = [n for n, _ in frames]
    centroids = np.array([f["centroid"] for _, f in frames])
    boxes = np.array([f["box"] for _, f in frames], dtype=float)
    areas = np.array([f["area"] for _, f in frames], dtype=float)
    pivots = np.array([f["pivot"] for _, f in frames])

    steps = np.linalg.norm(np.diff(centroids, axis=0), axis=1)
    accelerations = np.linalg.norm(np.diff(centroids, n=2, axis=0), axis=1)
    box_steps = np.abs(np.diff(boxes, axis=0)).max(axis=1)
    box_accelerations = np.abs(np.diff(boxes, n=2, axis=0)).max(axis=1)
    area_steps = np.abs(np.diff(areas)) / areas[:-1]

    limits = {
        "maximumCentroidStepPixels": args.max_centroid_step_pixels,
        "maximumCentroidAccelerationPixels": args.max_centroid_acceleration_pixels,
        "maximumBoundingBoxSizeStepPixels": args.max_bbox_size_step_pixels,
        "maximumBoundingBoxSizeAccelerationPixels": args.max_bbox_size_acceleration_pixels,
        "maximumVisibleAreaStepRatio": args.max_visible_area_step_ratio,
    }
    observed = {
        "maximumCentroidStepPixels": steps,
        "maximumCentroidAccelerationPixels": accelerations,
        "maximumBoundingBoxSizeStepPixels": box_steps,
        "maximumBoundingBoxSizeAccelerationPixels": box_accelerations,
        "maximumVisibleAreaStepRatio": area_steps,
    }

    measures = []
    tight: list[dict[str, object]] = []
    for name, limit in limits.items():
        values = observed[name]
        worst = float(values.max())
        # A step indexes the pair starting at frames[i]; an acceleration the
        # triplet starting there. Report the real frame number either way.
        offset = 1 if values.size == len(numbers) - 1 else 2
        index = int(values.argmax())
        measures.append(
            {
                "limit": name,
                "limitValue": limit,
                "authorityMedian": round(float(np.median(values)), 4),
                "authorityMax": round(worst, 4),
                "usedFraction": round(worst / limit, 4) if limit else None,
                "worstAt": numbers[index : index + offset + 1],
            }
        )
        if limit and worst > limit * HEADROOM_FRACTION:
            tight.append(measures[-1])

    # The source's own colour variation, which is what a colour-stability limit
    # has to be set from. An animation that genuinely shifts colour needs room;
    # one that does not makes any output wobble obvious.
    colours = [f["colour"] for _, f in frames if f["colour"] is not None]
    colour_steps = (
        np.abs(np.diff(np.array(colours), axis=0)).max(axis=1)
        if len(colours) > 1
        else np.array([0.0])
    )

    pivot = [int(round(float(np.median(pivots[:, 0])))), int(round(float(pivots[:, 1].max())))]
    report = {
        "status": "accepted" if not tight and not missing else "review-needed",
        "sourceManifest": str(args.manifest.resolve()),
        "frameCount": len(frames),
        "missingFrames": missing,
        "measuredPivot": pivot,
        "pivotSpreadPixels": round(float(pivots[:, 0].max() - pivots[:, 0].min()), 3),
        "sourceColourStep": {
            "median": round(float(np.median(colour_steps)), 4),
            "max": round(float(colour_steps.max()), 4),
            "suggestedLimit": round(max(1.0, float(colour_steps.max()) * 3.0), 2),
        },
        "headroomFraction": HEADROOM_FRACTION,
        "measures": measures,
        "tightTransitions": tight,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")

    print(f"{'limit':<44}{'authority max':>14}{'limit':>10}{'used':>8}")
    for item in measures:
        print(
            f"{item['limit']:<44}{item['authorityMax']:>14.3f}"
            f"{item['limitValue']:>10.3f}{item['usedFraction']:>7.0%}"
        )
    print(
        f"\nsource colour step between frames: median "
        f"{np.median(colour_steps):.2f}  max {colour_steps.max():.2f} levels"
        f"  -> suggested colour limit {max(1.0, colour_steps.max() * 3.0):.2f}"
    )
    print(f"measured ground-contact pivot: {pivot[0]}, {pivot[1]}")
    if missing:
        print(f"missing source frames: {missing}")
    if tight:
        print(
            "\nthese limits are more than "
            f"{HEADROOM_FRACTION:.0%} spent by the animation itself; put them to "
            "the user before the batch:"
        )
        for item in tight:
            print(f"  {item['limit']} at frames {item['worstAt']}")
    return 0 if report["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
