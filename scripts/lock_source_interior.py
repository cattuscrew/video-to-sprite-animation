#!/usr/bin/env python3
"""Take the sprite's interior pixels from the source, not from the tool.

The tool redraws. Registration fixes where the sprite sits and a palette pass
fixes what colour it is, but neither can fix the fact that every line in the
artwork is drawn again for each frame and lands a fraction of a pixel
differently. Measured between neighbouring delivered frames, 2.29% of interior
pixels swung more than 40 luma levels, and those pixels sat on the artwork's
lines: their gradient in the source was 82.8 against 1.3 for the flat areas, 66
times higher. Played back, that is the shimmer on every outline, eye, seam and
rivet. No colour gate can see it and no colour pass can fix it, because it is
not colour.

The source does not have this problem. Its lines are the same lines in every
frame. So where the source is unambiguously the character, its pixels are used
directly, and the frame-to-frame error there becomes zero by construction.

This is not a background-removal method and does not become one. The alpha
channel is the tool's, untouched, and it alone decides what is transparent.
What changes is only the colour of pixels the tool already decided are opaque.

Two pixels of erosion, and any pixel with detectable green spill is skipped:
the source's own anti-aliased boundary is blended with the screen, so copying
it where the tool says "opaque" would paint the spill back on. Near the
outline the tool's colour stays, which is where it is already unmixed.
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

from source_foreground import erode, foreground_mask, green_excess

ALPHA_OPAQUE = 250
DEFAULT_ERODE = 2


def locked_region(
    output: np.ndarray, source: np.ndarray, radius: int = DEFAULT_ERODE
) -> np.ndarray:
    """Where the source may be copied: opaque in the output, clean in the source."""
    return (
        erode(foreground_mask(source), radius)
        & (green_excess(source) < 0)
        & (output[:, :, 3] >= ALPHA_OPAQUE)
    )


def lock(
    output: np.ndarray, source: np.ndarray, radius: int = DEFAULT_ERODE
) -> tuple[np.ndarray, dict[str, object]]:
    if output.shape[:2] != source.shape[:2]:
        return output, {
            "status": "repair-needed",
            "error": "output and source are different sizes",
        }
    region = locked_region(output, source, radius)
    locked = output.copy()
    locked[:, :, :3][region] = source[:, :, :3][region]
    drawn = int((output[:, :, 3] > 0).sum())
    return locked, {
        "status": "accepted",
        "lockedPixels": int(region.sum()),
        "drawnPixels": drawn,
        "lockedFraction": round(int(region.sum()) / max(1, drawn), 4),
        "erodePixels": radius,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="source-frame-manifest.json")
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--erode-pixels", type=int, default=DEFAULT_ERODE)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    directory = Path(manifest["sourceFramesDirectory"])
    args.output.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, object]] = []
    errors: list[str] = []
    for item in manifest.get("frameMapping", []):
        number = int(item["outputFrame"])
        name = str(item.get("outputFile") or f"frame-{number:03d}.png")
        frame_path, source_path = args.frames / name, directory / str(item["sourceFile"])
        if not frame_path.is_file():
            errors.append(f"frame {number}: missing output frame")
            continue
        output = np.asarray(Image.open(frame_path).convert("RGBA"), dtype=np.uint8)
        source = np.asarray(Image.open(source_path).convert("RGBA"), dtype=np.uint8)
        locked, record = lock(output, source, args.erode_pixels)
        record["outputFrame"] = number
        records.append(record)
        if record["status"] != "accepted":
            errors.append(f"frame {number}: {record.get('error')}")
            continue
        # The tool's alpha is the delivered alpha. Always.
        assert np.array_equal(locked[:, :, 3], output[:, :, 3])
        Image.fromarray(locked, "RGBA").save(args.output / name, format="PNG")

    fractions = [float(r["lockedFraction"]) for r in records if "lockedFraction" in r]
    report = {
        "status": "accepted" if not errors else "repair-needed",
        "method": "source-interior-locked-behind-tool-alpha",
        "frameCount": len(records),
        "medianLockedFraction": round(float(np.median(fractions)), 4) if fractions else None,
        "errors": errors,
        "frames": records,
    }
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "frameCount", "medianLockedFraction")}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
