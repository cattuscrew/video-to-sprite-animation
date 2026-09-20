#!/usr/bin/env python3
"""Gate colour across the sequence, the way the temporal gates do geometry.

Every colour check in this skill compared a frame with its own source and
stopped there. That cannot see flicker. A frame 2 levels off its source next to
one 9 levels off is two passes and one visible pulse; the defect lives in the
distance between neighbours, not in either frame.

Measured per material, because a per-frame average cannot see it either. The
materials drift in opposite directions: on a delivered sequence the tunic moved
15.3 levels between neighbours and the shield 16.4, while the mean over the
whole character moved 1.47. Averaging the character cancels exactly the defect
being looked for, and no threshold recovers a quantity that was never measured.

So the limit comes from the source, like the geometry limits do. The source
says how much this animation's colour really moves; anything beyond that was
introduced by the tool.

Measured on the eroded opaque interior, so the soft edge -- which is allowed to
differ, and where a single-pixel change swings the mean -- cannot register as
flicker.
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

from source_foreground import (
    MIN_MATERIAL_PIXELS,
    assign_materials,
    discover_materials,
    erode,
    foreground_mask,
)

# Per material, the source's own neighbour swing was 0.83 median, 7.07 worst --
# it is a compressed video, not flat cel art, so its materials are steady but
# not still. The limit sits above the source's worst and well below the output's
# 16.4.
DEFAULT_MAX_STEP = 8.0
ALPHA_OPAQUE = 250
MIN_INTERIOR_PIXELS = 500


def material_means(
    image: np.ndarray, source: np.ndarray, materials: np.ndarray
) -> dict[int, np.ndarray]:
    """Mean output colour inside each material, as the source defines it."""
    labels = assign_materials(source, materials)
    solid = erode((image[:, :, 3] >= ALPHA_OPAQUE) & (labels >= 0), 2)
    found: dict[int, np.ndarray] = {}
    for index in range(len(materials)):
        region = solid & (labels == index)
        if int(region.sum()) >= MIN_MATERIAL_PIXELS:
            found[index] = image[:, :, :3][region].astype(np.float64).mean(axis=0)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="source-frame-manifest.json")
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path, help="where to write the report")
    parser.add_argument("--max-step", type=float, default=DEFAULT_MAX_STEP)
    parser.add_argument(
        "--loop",
        action="store_true",
        help="also check the seam from the last frame back to the first",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    directory = Path(manifest["sourceFramesDirectory"])
    records = manifest.get("frameMapping", [])

    def source_of(item: dict) -> np.ndarray | None:
        path = directory / str(item["sourceFile"])
        if not path.is_file():
            return None
        return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)

    # Materials come from a spread of native frames, so a colour that only
    # appears in part of the loop still gets its own region.
    sample = [source_of(r) for r in records[:: max(1, len(records) // 4)]]
    materials = discover_materials([s for s in sample if s is not None])
    if materials.size == 0:
        raise SystemExit("no material regions could be found in the source frames")

    means: dict[int, dict[int, np.ndarray]] = {}
    errors: list[str] = []
    numbers: list[int] = []
    for item in records:
        number = int(item["outputFrame"])
        numbers.append(number)
        name = str(item.get("outputFile") or f"frame-{number:03d}.png")
        path = args.frames / name
        source = source_of(item)
        if not path.is_file():
            errors.append(f"missing output frame {number}")
            continue
        if source is None:
            errors.append(f"frame {number}: source frame is missing")
            continue
        image = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
        found = material_means(image, source, materials)
        if not found:
            errors.append(f"frame {number}: no material region large enough to measure")
            continue
        means[number] = found

    # Only real neighbours, in manifest order. A missing frame leaves a gap
    # rather than letting the frames either side stand next to each other.
    pairs = [(a, b) for a, b in zip(numbers, numbers[1:]) if a in means and b in means]
    if args.loop and numbers and numbers[-1] in means and numbers[0] in means:
        pairs.append((numbers[-1], numbers[0]))

    steps = []
    for first, second in pairs:
        shared = sorted(set(means[first]) & set(means[second]))
        per_material = {}
        worst, worst_material = 0.0, None
        for index in shared:
            delta = means[second][index] - means[first][index]
            value = float(np.abs(delta).max())
            per_material[str(index)] = round(value, 3)
            if value > worst:
                worst, worst_material = value, index
        entry = {
            "from": first,
            "to": second,
            "worstChannelStep": round(worst, 3),
            "worstMaterial": worst_material,
            "perMaterialStep": per_material,
            "status": "accepted" if worst <= args.max_step else "repair-needed",
        }
        steps.append(entry)
        if worst > args.max_step:
            errors.append(
                f"frames {first}->{second}: material {worst_material} steps "
                f"{worst:.2f} levels, over {args.max_step}"
            )

    observed = [s["worstChannelStep"] for s in steps]
    report = {
        "status": "accepted" if not errors else "repair-needed",
        "measuredPer": "material",
        "maxStepLimit": args.max_step,
        "materials": [[round(float(v), 1) for v in m] for m in materials],
        "frameCount": len(means),
        "transitionCount": len(steps),
        "medianStep": round(float(np.median(observed)), 3) if observed else None,
        "maxStep": round(float(max(observed)), 3) if observed else None,
        "failedTransitionCount": sum(s["status"] != "accepted" for s in steps),
        "errors": errors[:40],
        "transitions": steps,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "medianStep", "maxStep", "failedTransitionCount")
            },
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
