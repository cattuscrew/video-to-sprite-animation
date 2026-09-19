#!/usr/bin/env python3
"""Verify that rembg outputs contain pixels from their declared native frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def transformed_source(
    rgb: np.ndarray, canvas: tuple[int, int], offset: tuple[int, int]
) -> np.ndarray:
    width, height = canvas
    ox, oy = offset
    out = np.zeros((height, width, 3), dtype=np.uint8)
    source_height, source_width = rgb.shape[:2]
    source_x0 = max(0, -ox)
    source_y0 = max(0, -oy)
    destination_x0 = max(0, ox)
    destination_y0 = max(0, oy)
    copy_width = min(source_width - source_x0, width - destination_x0)
    copy_height = min(source_height - source_y0, height - destination_y0)
    if copy_width <= 0 or copy_height <= 0:
        raise ValueError("shared transform does not intersect output canvas")
    out[
        destination_y0 : destination_y0 + copy_height,
        destination_x0 : destination_x0 + copy_width,
    ] = rgb[
        source_y0 : source_y0 + copy_height,
        source_x0 : source_x0 + copy_width,
    ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.source_manifest.read_text())
    errors: list[str] = []
    if manifest.get("processingType") != "exact-source-extraction":
        errors.append("manifest processingType is not exact-source-extraction")
    transform = manifest.get("sharedTransform", {})
    if float(transform.get("scale", 0)) != 1.0:
        errors.append("exact-source validation currently requires scale=1.0")
    canvas = tuple(int(value) for value in transform.get("canvas", []))
    offset = tuple(int(value) for value in transform.get("offset", []))
    if len(canvas) != 2 or len(offset) != 2:
        raise SystemExit("manifest sharedTransform requires canvas and offset pairs")

    mapping = list(manifest.get("frameMapping", []))
    source_dir = Path(manifest["sourceFramesDirectory"])
    expected_alpha_dir = (
        Path(manifest["expectedAlphaDirectory"])
        if manifest.get("expectedAlphaDirectory")
        else None
    )
    frames = sorted(args.frames_dir.glob("frame-*.png"))
    if len(frames) != len(mapping):
        errors.append(f"mapping/frame count mismatch {len(mapping)}/{len(frames)}")
    native_ids = [int(record.get("nativeFrame", -1)) for record in mapping]
    if len(set(native_ids)) != len(native_ids):
        errors.append("native frame mapping contains reused/held sources")
    if native_ids and native_ids != list(range(native_ids[0], native_ids[0] + len(native_ids))):
        errors.append("native frame mapping is not contiguous at native FPS")

    records: list[dict[str, object]] = []
    diagnostics = args.output / "diagnostics"
    for index, (record, frame_path) in enumerate(zip(mapping, frames), start=1):
        frame_errors: list[str] = []
        if record.get("classification") != "exact-source-extraction":
            frame_errors.append("classification is not exact-source-extraction")
        if any(bool(record.get(key)) for key in ("rgbChanged", "geometryChanged", "held", "interpolated", "generated")):
            frame_errors.append("mapping declares a non-source-preserving operation")
        if record.get("outputFile") != frame_path.name:
            frame_errors.append(
                f"output filename={frame_path.name} expected={record.get('outputFile')}"
            )
        source_path = source_dir / str(record["sourceFile"])
        source = np.asarray(Image.open(source_path).convert("RGB"), dtype=np.uint8)
        expected_rgb = transformed_source(source, canvas, offset)
        output = np.asarray(Image.open(frame_path).convert("RGBA"), dtype=np.uint8)
        if (output.shape[1], output.shape[0]) != canvas:
            frame_errors.append(
                f"canvas={(output.shape[1], output.shape[0])} expected={canvas}"
            )
            foreign_count = -1
            max_rgb_error = -1
            alpha_mismatch = -1
        else:
            visible = output[:, :, 3] > 0
            delta = np.abs(output[:, :, :3].astype(np.int16) - expected_rgb.astype(np.int16))
            foreign = visible & np.any(delta != 0, axis=2)
            foreign_count = int(np.count_nonzero(foreign))
            max_rgb_error = int(delta[visible].max()) if np.any(visible) else 0
            alpha_mismatch = 0
            mismatch = foreign.copy()
            if foreign_count:
                frame_errors.append(f"visible pixels not copied from declared source={foreign_count}")
            if expected_alpha_dir:
                alpha_path = expected_alpha_dir / frame_path.name
                expected_alpha = np.asarray(Image.open(alpha_path).convert("RGBA"))[:, :, 3]
                alpha_diff = output[:, :, 3] != expected_alpha
                alpha_mismatch = int(np.count_nonzero(alpha_diff))
                mismatch |= alpha_diff
                if alpha_mismatch:
                    frame_errors.append(f"alpha differs from approved extraction={alpha_mismatch}")
            if frame_errors:
                overlay = output.copy()
                overlay[mismatch] = [255, 0, 255, 255]
                diagnostics.mkdir(parents=True, exist_ok=True)
                Image.fromarray(overlay, "RGBA").save(diagnostics / frame_path.name)
        records.append(
            {
                "frame": index,
                "nativeFrame": record.get("nativeFrame"),
                "sourceFile": str(source_path),
                "status": "accepted" if not frame_errors else "repair-needed",
                "foreignSourcePixelCount": foreign_count,
                "maximumVisibleRgbError": max_rgb_error,
                "alphaMismatchPixelCount": alpha_mismatch,
                "errors": frame_errors,
            }
        )
        errors.extend(f"frame {index}: {error}" for error in frame_errors)

    report = {
        "status": "accepted" if not errors else "repair-needed",
        "sourceManifest": str(args.source_manifest.resolve()),
        "frameCount": len(records),
        "failedFrameCount": sum(record["status"] != "accepted" for record in records),
        "errors": errors,
        "frames": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "source-correspondence-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps({"status": report["status"], "errors": len(errors)}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
