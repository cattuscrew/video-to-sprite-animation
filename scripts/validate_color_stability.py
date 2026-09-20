#!/usr/bin/env python3
"""Gate colour across the sequence, the way the temporal gates do geometry.

Every colour check in this skill compared a frame with its own source and
stopped there. That cannot see flicker. A frame 2 levels off its source next to
one 9 levels off is two passes and one visible pulse; the defect lives in the
distance between neighbours, not in either frame.

Measured on a 48-frame delivery: every frame inside an absolute limit of 12,
and the sequence still pulsing, because neighbours differed by up to 6.8 levels
while the source animation's own neighbours differ by at most 0.53.

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

from register_to_authority import erode
from source_foreground import foreground_mask

# The source animation's own neighbour swing was 0.22 median, 0.53 worst. Three
# times the worst leaves honest lighting changes room while still catching a
# pulse: the delivery that prompted this ran to 7.1.
DEFAULT_MAX_STEP = 1.6
ALPHA_OPAQUE = 250
MIN_INTERIOR_PIXELS = 500


def interior_mean(image: np.ndarray, source: np.ndarray | None) -> np.ndarray | None:
    mask = image[:, :, 3] >= ALPHA_OPAQUE
    if source is not None:
        mask = mask & foreground_mask(source)
    mask = erode(mask, 2)
    if int(mask.sum()) < MIN_INTERIOR_PIXELS:
        return None
    return image[:, :, :3][mask].astype(np.float64).mean(axis=0)


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

    means: dict[int, np.ndarray] = {}
    errors: list[str] = []
    numbers: list[int] = []
    for item in manifest.get("frameMapping", []):
        number = int(item["outputFrame"])
        numbers.append(number)
        name = str(item.get("outputFile") or f"frame-{number:03d}.png")
        path = args.frames / name
        if not path.is_file():
            errors.append(f"missing output frame {number}")
            continue
        source_path = directory / str(item["sourceFile"])
        source = (
            np.asarray(Image.open(source_path).convert("RGBA"), dtype=np.uint8)
            if source_path.is_file()
            else None
        )
        found = interior_mean(
            np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8), source
        )
        if found is None:
            errors.append(f"frame {number}: too little opaque interior to measure")
            continue
        means[number] = found

    # Only real neighbours, in manifest order. A missing frame leaves a gap
    # rather than letting the frames either side stand next to each other.
    pairs = [(a, b) for a, b in zip(numbers, numbers[1:]) if a in means and b in means]
    if args.loop and numbers and numbers[-1] in means and numbers[0] in means:
        pairs.append((numbers[-1], numbers[0]))

    steps = []
    for first, second in pairs:
        delta = means[second] - means[first]
        worst = float(np.abs(delta).max())
        entry = {
            "from": first,
            "to": second,
            "delta": [round(float(v), 3) for v in delta],
            "worstChannelStep": round(worst, 3),
            "status": "accepted" if worst <= args.max_step else "repair-needed",
        }
        steps.append(entry)
        if worst > args.max_step:
            errors.append(
                f"frames {first}->{second}: interior colour steps {worst:.2f} "
                f"levels, over {args.max_step}"
            )

    observed = [s["worstChannelStep"] for s in steps]
    report = {
        "status": "accepted" if not errors else "repair-needed",
        "maxStepLimit": args.max_step,
        "frameCount": len(means),
        "transitionCount": len(steps),
        "medianStep": round(float(np.median(observed)), 3) if observed else None,
        "maxStep": round(float(max(observed)), 3) if observed else None,
        "failedTransitionCount": sum(s["status"] != "accepted" for s in steps),
        "errors": errors,
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
