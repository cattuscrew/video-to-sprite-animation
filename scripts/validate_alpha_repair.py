#!/usr/bin/env python3
"""Reject GPT alpha repairs that redraw or reposition approved parent sprites."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def visible_bbox(alpha: np.ndarray, threshold: int = 8) -> tuple[int, int, int, int]:
    ys, xs = np.where(alpha > threshold)
    if len(xs) == 0:
        return (0, 0, 0, 0)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def centroid(alpha: np.ndarray) -> tuple[float, float]:
    weights = alpha.astype(np.float64) / 255.0
    total = float(weights.sum())
    if total <= 0:
        return (0.0, 0.0)
    ys, xs = np.indices(alpha.shape)
    return (float((xs * weights).sum() / total), float((ys * weights).sum() / total))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("parent_manifest", type=Path)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-bbox-edge-delta", type=int, default=2)
    parser.add_argument("--max-centroid-delta", type=float, default=1.5)
    parser.add_argument("--max-visible-area-ratio", type=float, default=0.03)
    parser.add_argument("--max-interior-rgb-mae", type=float, default=3.0)
    parser.add_argument(
        "--pre-lock-frames",
        type=Path,
        help=(
            "Directory of repaired frames before lock_parent_foreground.py restored "
            "parent RGB. Interior RGB is meaningless when measured on locked frames, "
            "because the lock writes the parent's own pixels back."
        ),
    )
    args = parser.parse_args()

    manifest = json.loads(args.parent_manifest.read_text())
    parent_dir = Path(manifest["parentFramesDirectory"])
    mapping = list(manifest.get("frameMapping", []))
    errors: list[str] = []
    outputs = sorted(args.frames_dir.glob("frame-*.png"))
    if len(outputs) != len(mapping):
        errors.append(f"mapping/frame count mismatch {len(mapping)}/{len(outputs)}")

    records: list[dict[str, object]] = []
    for index, record in enumerate(mapping, start=1):
        frame_errors: list[str] = []
        output_path = args.frames_dir / f"frame-{index:03d}.png"
        if not output_path.is_file():
            frame_errors.append("missing repaired output")
            records.append(
                {
                    "outputFrame": index,
                    "nativeFrame": record.get("nativeFrame"),
                    "parentFile": str(Path(manifest["parentFramesDirectory"]) / str(record.get("parentFile"))),
                    "outputFile": str(output_path),
                    "status": "user-visible-blocked",
                    "errors": frame_errors,
                }
            )
            errors.extend(f"frame {index}: {error}" for error in frame_errors)
            continue
        parent_path = parent_dir / str(record.get("parentFile"))
        parent_digest = hashlib.sha256(parent_path.read_bytes()).hexdigest()
        if parent_digest != record.get("parentSha256"):
            frame_errors.append("parent SHA-256 does not match manifest")
        parent = np.asarray(Image.open(parent_path).convert("RGBA"), dtype=np.uint8)
        output = np.asarray(Image.open(output_path).convert("RGBA"), dtype=np.uint8)
        if output.shape != parent.shape:
            frame_errors.append(
                f"canvas changed from {(parent.shape[1], parent.shape[0])} "
                f"to {(output.shape[1], output.shape[0])}"
            )
            bbox_delta = None
            centroid_delta = None
            area_ratio = None
            rgb_mae = None
        else:
            parent_alpha = parent[:, :, 3]
            output_alpha = output[:, :, 3]
            parent_bbox = visible_bbox(parent_alpha)
            output_bbox = visible_bbox(output_alpha)
            bbox_delta = max(abs(a - b) for a, b in zip(parent_bbox, output_bbox))
            if bbox_delta > args.max_bbox_edge_delta:
                frame_errors.append(f"visible bounds changed by {bbox_delta}px")
            pc = centroid(parent_alpha)
            oc = centroid(output_alpha)
            centroid_delta = float(np.hypot(pc[0] - oc[0], pc[1] - oc[1]))
            if centroid_delta > args.max_centroid_delta:
                frame_errors.append(f"alpha centroid moved {centroid_delta:.3f}px")
            parent_area = int(np.count_nonzero(parent_alpha > 8))
            output_area = int(np.count_nonzero(output_alpha > 8))
            area_ratio = abs(output_area - parent_area) / max(1, parent_area)
            if area_ratio > args.max_visible_area_ratio:
                frame_errors.append(f"visible area changed by {area_ratio:.3%}")
            rgb_image = output
            if args.pre_lock_frames is not None:
                pre_lock_path = args.pre_lock_frames / f"frame-{index:03d}.png"
                if not pre_lock_path.is_file():
                    frame_errors.append("missing pre-lock frame for interior RGB check")
                    rgb_image = None
                else:
                    rgb_image = np.asarray(
                        Image.open(pre_lock_path).convert("RGBA"), dtype=np.uint8
                    )
                    if rgb_image.shape != parent.shape:
                        frame_errors.append("pre-lock frame canvas does not match parent")
                        rgb_image = None
            stable_interior = (parent_alpha >= 250) & (output_alpha >= 250)
            if rgb_image is None:
                rgb_mae = None
            elif not np.any(stable_interior):
                rgb_mae = None
                frame_errors.append("no stable opaque interior remains")
            else:
                delta = np.abs(
                    parent[:, :, :3].astype(np.int16)
                    - rgb_image[:, :, :3].astype(np.int16)
                )
                rgb_mae = float(np.mean(delta[stable_interior]))
                if rgb_mae > args.max_interior_rgb_mae:
                    frame_errors.append(f"interior foreground RGB MAE={rgb_mae:.3f}")

        records.append(
            {
                "outputFrame": index,
                "nativeFrame": record.get("nativeFrame"),
                "parentFile": str(parent_path),
                "outputFile": str(output_path),
                "status": "accepted" if not frame_errors else "repair-needed",
                "maximumBoundingBoxEdgeDeltaPixels": bbox_delta,
                "centroidDeltaPixels": centroid_delta,
                "visibleAreaDeltaRatio": area_ratio,
                "interiorRgbMeanAbsoluteError": rgb_mae,
                "errors": frame_errors,
            }
        )
        errors.extend(f"frame {index}: {error}" for error in frame_errors)

    if args.pre_lock_frames is None:
        errors.append(
            "interior RGB was measured on delivered frames; supply --pre-lock-frames "
            "so the check compares the parent with the repair, not with itself"
        )

    report = {
        "status": "accepted" if not errors else "repair-needed",
        "processingMode": "gpt-image-alpha-repair",
        "parentFrameManifest": str(args.parent_manifest.resolve()),
        "interiorRgbMeasuredOn": (
            "pre-lock-repair" if args.pre_lock_frames is not None else "delivered-frames"
        ),
        "frameCount": len(records),
        "failedFrameCount": sum(r["status"] != "accepted" for r in records),
        "errors": errors,
        "frames": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "errors": len(errors)}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
