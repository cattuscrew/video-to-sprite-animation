#!/usr/bin/env python3
"""Put each frame's foreground colour back where its own source frame has it.

The image tool returns colour that is close but not equal to the input, and the
error is different every frame: measured over 48 frames it ran -11 to +5 levels
per channel against each frame's own source, swinging up to 6.8 levels between
neighbours. Each frame on its own looks right. Played back, the sequence
pulses, because the source itself is stable to 0.22 levels and the output is
not -- about eleven times the variation, all of it introduced here.

No per-frame check can see that. A frame sitting 2 levels off and the next
sitting 9 off are both well inside any sane absolute limit; the flicker is the
distance between them, and only a gate that looks at neighbours can measure it.

The correction is a per-channel offset applied per material, chosen so each
material's opaque pixels have the same mean colour as the same pixels of the
frame's own mapped native frame.

Per material, because the materials drift independently and often in opposite
directions: on a delivered sequence the tunic moved 15.3 levels between
neighbours and the shield 16.4, while the average over the whole character
moved 1.47. One offset for the whole frame can only cancel what the materials
share, so it corrects the average and leaves every visible pulse in place. That
was tried first and changed nothing anyone could see.

The danger of a per-material fit is mis-clustering: a region assigned to the
wrong material gets recoloured, which is worse than the flicker. That is
avoided by taking the regions from the native source frame -- stable,
authoritative, and already pinned to the output by registration -- and never
from the output being corrected.

Offsets rather than gains: they preserve contrast and cannot invert anything.

Alpha is never touched, and neither is geometry.
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

# Per material the offsets are larger than the frame-wide one they replaced:
# measured over 384 frame-material pairs, median 9.5, p99 28.6, worst 29.6. The
# darkest material -- the artwork's keyline, which the tool renders heavier than
# the source -- needs 24.5 on its own. The cap sits just above the observed
# worst, so a frame that is genuinely a different colour is still refused
# rather than shifted until it matches.
MAX_OFFSET = 32.0
MIN_INTERIOR_PIXELS = 500
ALPHA_OPAQUE = 250


def solid_region(output: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Pixels solid in the output and character in the source, eroded.

    The soft edge is excluded: it blends toward transparency in the output and
    does not in the source, so including it would bias every measurement.
    """
    return erode((output[:, :, 3] >= ALPHA_OPAQUE) & foreground_mask(source), 2)


def normalize(
    output: np.ndarray,
    source: np.ndarray,
    materials: np.ndarray,
    max_offset: float = MAX_OFFSET,
) -> tuple[np.ndarray | None, dict[str, object]]:
    """Match each material's colour to the same material in its own source."""
    record: dict[str, object] = {}
    labels = assign_materials(source, materials)
    solid = solid_region(output, source)
    if int(solid.sum()) < MIN_INTERIOR_PIXELS:
        record.update({"status": "repair-needed", "error": "too little shared interior"})
        return None, record

    # A frame-wide offset, used for pixels no material claims: the soft edge,
    # and anywhere the output is drawn but the source says background.
    fallback = (
        source[:, :, :3][solid].astype(np.float64).mean(axis=0)
        - output[:, :, :3][solid].astype(np.float64).mean(axis=0)
    )

    offsets: dict[int, np.ndarray] = {}
    measured: dict[str, list[float]] = {}
    for index in range(len(materials)):
        region = solid & (labels == index)
        if int(region.sum()) < MIN_MATERIAL_PIXELS:
            continue
        offset = source[:, :, :3][region].astype(np.float64).mean(axis=0) - output[
            :, :, :3
        ][region].astype(np.float64).mean(axis=0)
        if float(np.abs(offset).max()) > max_offset:
            record.update(
                {
                    "status": "repair-needed",
                    "error": (
                        f"material {index} is {float(np.abs(offset).max()):.1f} levels "
                        f"from its source, over {max_offset}; this frame is not "
                        "merely drifted"
                    ),
                }
            )
            return None, record
        offsets[index] = offset
        measured[str(index)] = [round(float(v), 3) for v in offset]

    if not offsets:
        record.update({"status": "repair-needed", "error": "no material large enough"})
        return None, record

    corrected = output.copy()
    drawn = output[:, :, 3] > 0
    shift = np.zeros(output.shape[:2] + (3,), dtype=np.float64)
    shift[:] = fallback
    for index, offset in offsets.items():
        shift[labels == index] = offset
    values = output[:, :, :3][drawn].astype(np.float64) + shift[drawn]
    corrected[:, :, :3][drawn] = np.clip(np.rint(values), 0, 255).astype(np.uint8)

    record.update(
        {
            "status": "accepted",
            "materialsCorrected": len(offsets),
            "offsets": measured,
            "fallbackOffset": [round(float(v), 3) for v in fallback],
            "largestOffset": round(
                float(max(np.abs(o).max() for o in offsets.values())), 3
            ),
        }
    )
    return corrected, record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="source-frame-manifest.json")
    parser.add_argument("frames", type=Path, help="directory of delivered frames")
    parser.add_argument("output", type=Path, help="directory to write corrected frames")
    parser.add_argument("--record", type=Path, help="write the per-frame measurements here")
    parser.add_argument("--max-offset", type=float, default=MAX_OFFSET)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    directory = Path(manifest["sourceFramesDirectory"])
    args.output.mkdir(parents=True, exist_ok=True)
    records_in = manifest.get("frameMapping", [])

    def source_of(item: dict) -> np.ndarray | None:
        path = directory / str(item["sourceFile"])
        if not path.is_file():
            return None
        return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)

    sample = [source_of(r) for r in records_in[:: max(1, len(records_in) // 4)]]
    materials = discover_materials([s for s in sample if s is not None])
    if materials.size == 0:
        raise SystemExit("no material regions could be found in the source frames")

    records: list[dict[str, object]] = []
    errors: list[str] = []
    for item in manifest.get("frameMapping", []):
        number = int(item["outputFrame"])
        name = str(item.get("outputFile") or f"frame-{number:03d}.png")
        frame_path = args.frames / name
        source_path = directory / str(item["sourceFile"])
        if not frame_path.is_file():
            errors.append(f"frame {number}: missing output frame")
            records.append({"outputFrame": number, "status": "user-visible-blocked"})
            continue
        output = np.asarray(Image.open(frame_path).convert("RGBA"), dtype=np.uint8)
        source = np.asarray(Image.open(source_path).convert("RGBA"), dtype=np.uint8)
        corrected, record = normalize(output, source, materials, args.max_offset)
        record["outputFrame"] = number
        records.append(record)
        if corrected is None:
            errors.append(f"frame {number}: {record.get('error')}")
            continue
        # Alpha must come through bit for bit; this is a colour pass.
        assert np.array_equal(corrected[:, :, 3], output[:, :, 3])
        Image.fromarray(corrected, "RGBA").save(args.output / name, format="PNG")

    magnitudes = [
        float(r["largestOffset"]) for r in records if r.get("largestOffset") is not None
    ]
    report = {
        "status": "accepted" if not errors else "repair-needed",
        "method": "per-material-offset-to-own-source-frame",
        "materials": [[round(float(v), 1) for v in m] for m in materials],
        "frameCount": len(records),
        "correctedFrameCount": sum(r.get("status") == "accepted" for r in records),
        "maxOffsetApplied": round(max(magnitudes), 3) if magnitudes else None,
        "medianOffsetApplied": (
            round(float(np.median(magnitudes)), 3) if magnitudes else None
        ),
        "errors": errors,
        "frames": records,
    }
    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ("status", "correctedFrameCount", "maxOffsetApplied")},
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
