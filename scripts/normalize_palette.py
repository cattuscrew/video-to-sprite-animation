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

The correction is a per-channel offset on the foreground, chosen so the frame's
opaque interior has the same mean colour as the same region of its own mapped
native frame. Deliberately the frame's own source and not a shared reference
frame: every other stage in this workflow answers to the frame's own authority,
and matching a single reference would drag a genuine lighting change in the
animation toward whatever frame was picked. Because the source is stable,
matching each frame to its own source makes the sequence stable too.

An offset, not a gain or a per-material fit. Offsets preserve contrast and
cannot invert anything; the failure mode of a cleverer fit is recolouring a
material it mis-clustered, which is a worse defect than the one being fixed.

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

from register_to_authority import erode
from source_foreground import foreground_mask

# An offset this large is not tool noise. Measured worst case was 11.2 levels;
# beyond 24 something is wrong with the frame and shifting it would hide that.
MAX_OFFSET = 24.0
MIN_INTERIOR_PIXELS = 500
ALPHA_OPAQUE = 250


def interior_mask(output: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Pixels solid in the output and character in the source.

    Eroded, so the soft edge -- where the output legitimately blends toward
    transparency and the source does not -- cannot pull the mean.
    """
    return erode((output[:, :, 3] >= ALPHA_OPAQUE) & foreground_mask(source), 2)


def measure_offset(
    output: np.ndarray, source: np.ndarray
) -> tuple[np.ndarray | None, dict[str, object]]:
    """The per-channel shift that puts the output's interior on the source's."""
    mask = interior_mask(output, source)
    record: dict[str, object] = {"interiorPixels": int(mask.sum())}
    if int(mask.sum()) < MIN_INTERIOR_PIXELS:
        record["error"] = "too little shared interior to measure colour against"
        return None, record
    output_mean = output[:, :, :3][mask].astype(np.float64).mean(axis=0)
    source_mean = source[:, :, :3][mask].astype(np.float64).mean(axis=0)
    offset = source_mean - output_mean
    record.update(
        {
            "outputInteriorMean": [round(float(v), 3) for v in output_mean],
            "sourceInteriorMean": [round(float(v), 3) for v in source_mean],
            "offset": [round(float(v), 3) for v in offset],
            "offsetMagnitude": round(float(np.abs(offset).max()), 3),
        }
    )
    return offset, record


def apply_offset(output: np.ndarray, offset: np.ndarray) -> np.ndarray:
    """Shift every drawn pixel's RGB. Alpha is copied through untouched."""
    corrected = output.copy()
    drawn = output[:, :, 3] > 0
    values = output[:, :, :3][drawn].astype(np.float64) + offset
    corrected[:, :, :3][drawn] = np.clip(np.rint(values), 0, 255).astype(np.uint8)
    return corrected


def normalize(
    output: np.ndarray, source: np.ndarray, max_offset: float = MAX_OFFSET
) -> tuple[np.ndarray | None, dict[str, object]]:
    offset, record = measure_offset(output, source)
    if offset is None:
        record["status"] = "repair-needed"
        return None, record
    if float(np.abs(offset).max()) > max_offset:
        record["status"] = "repair-needed"
        record["error"] = (
            f"colour offset {float(np.abs(offset).max()):.1f} levels exceeds "
            f"{max_offset}; this frame is not merely shifted"
        )
        return None, record
    corrected = apply_offset(output, offset)
    residual = measure_offset(corrected, source)[0]
    record["residual"] = [round(float(v), 3) for v in residual] if residual is not None else None
    record["status"] = "accepted"
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
        corrected, record = normalize(output, source, args.max_offset)
        record["outputFrame"] = number
        records.append(record)
        if corrected is None:
            errors.append(f"frame {number}: {record.get('error')}")
            continue
        # Alpha must come through bit for bit; this is a colour pass.
        assert np.array_equal(corrected[:, :, 3], output[:, :, 3])
        Image.fromarray(corrected, "RGBA").save(args.output / name, format="PNG")

    magnitudes = [
        float(r["offsetMagnitude"]) for r in records if r.get("offsetMagnitude") is not None
    ]
    report = {
        "status": "accepted" if not errors else "repair-needed",
        "method": "per-channel-offset-to-own-source-frame",
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
