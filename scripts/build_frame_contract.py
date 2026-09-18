#!/usr/bin/env python3
"""Build measurable identity/placement constraints from an approved RGBA frame."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def parse_pair(value: str) -> tuple[int, int]:
    parts = [int(part.strip()) for part in value.lower().replace("x", ",").split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected two integers, such as 512x512")
    return parts[0], parts[1]


def parse_region(value: str) -> dict[str, object]:
    name, raw = value.split("=", 1)
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be name=x,y,width,height")
    return {"name": name, "rect": parts}


def validate_authority(authority: dict[str, object]) -> None:
    allowed = {"canonical-original", "native-source-derived"}
    if authority.get("sourceKind") not in allowed:
        raise ValueError(f"authority sourceKind must be one of {sorted(allowed)}")
    if authority.get("userApproved") is not True:
        raise ValueError("authority/proof frame is not user-approved")
    if authority.get("derivedFromRejectedOutput") is not False:
        raise ValueError("authority may be derived from rejected output")
    if not authority.get("canonicalMaster") and not authority.get("nativeSource"):
        raise ValueError("authority names neither canonicalMaster nor nativeSource")


def visible_bbox(alpha: np.ndarray, threshold: int = 18) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(alpha > threshold)
    if len(xs) == 0:
        raise ValueError("frame has no visible pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def contact_pivot(alpha: np.ndarray, threshold: int = 18) -> tuple[float, int]:
    ys, xs = np.nonzero(alpha > threshold)
    bottom = int(ys.max())
    contact_x = xs[ys >= bottom - 8]
    return float(contact_x.min() + contact_x.max()) / 2.0, bottom


def edge_density(rgb: np.ndarray, alpha: np.ndarray) -> float:
    gray = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114
    dx = np.diff(gray, axis=1, append=gray[:, -1:])
    dy = np.diff(gray, axis=0, append=gray[-1:, :])
    edges = np.sqrt(dx * dx + dy * dy) > 24
    return float(np.mean(edges[alpha > 18]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("master", type=Path, help="Approved RGBA reference")
    parser.add_argument("output", type=Path, help="frame-contract.json")
    parser.add_argument("--canvas", type=parse_pair, default=(512, 512))
    parser.add_argument("--pivot", type=parse_pair, default=(256, 492))
    parser.add_argument("--scale-tolerance", type=float, default=0.03)
    parser.add_argument(
        "--processing-mode",
        choices=("faithful-extraction", "regenerative"),
        required=True,
    )
    parser.add_argument("--authority-manifest", required=True, type=Path)
    parser.add_argument("--per-frame-authority-dir", type=Path)
    parser.add_argument("--locked-region", action="append", default=[], type=parse_region)
    parser.add_argument("--required-semantic-region", action="append", default=[], type=parse_region)
    parser.add_argument("--allowed-moving", action="append", default=[])
    args = parser.parse_args()

    authority = json.loads(args.authority_manifest.read_text())
    validate_authority(authority)
    if args.processing_mode == "faithful-extraction" and not args.per_frame_authority_dir:
        raise SystemExit("faithful-extraction requires --per-frame-authority-dir")

    image = Image.open(args.master).convert("RGBA")
    rgba = np.asarray(image)
    alpha = rgba[:, :, 3]
    bbox = visible_bbox(alpha)
    pivot = contact_pivot(alpha)
    visible = alpha > 18
    rgb = rgba[:, :, :3][visible].astype(np.float32) / 255.0
    quantized = np.clip((rgb * 16).astype(np.int32), 0, 15)
    histogram = np.bincount(quantized[:, 0] * 256 + quantized[:, 1] * 16 + quantized[:, 2], minlength=4096)
    histogram = (histogram / max(1, histogram.sum())).round(6).tolist()

    contract = {
        "version": 2,
        "processingMode": args.processing_mode,
        "authorityManifest": str(args.authority_manifest.resolve()),
        "authority": authority,
        "perFrameAuthorityDirectory": (
            str(args.per_frame_authority_dir.resolve())
            if args.per_frame_authority_dir
            else None
        ),
        "master": str(args.master.resolve()),
        "masterSize": list(image.size),
        "canvas": list(args.canvas),
        "pivot": list(args.pivot),
        "groundY": args.pivot[1],
        "visibleBounds": list(bbox),
        "visibleSize": [bbox[2] - bbox[0], bbox[3] - bbox[1]],
        "measuredContactPivot": [round(pivot[0], 2), pivot[1]],
        "margins": {
            "left": bbox[0],
            "top": bbox[1],
            "right": image.width - bbox[2],
            "bottom": image.height - bbox[3],
        },
        "rgbMean": np.mean(rgb, axis=0).round(6).tolist(),
        "rgbStd": np.std(rgb, axis=0).round(6).tolist(),
        "paletteHistogram16": histogram,
        "paletteFingerprint": hashlib.sha256(bytes(quantized.tobytes())).hexdigest(),
        "edgeDensity": edge_density(rgba[:, :, :3].astype(np.float32), alpha),
        "lockedRegions": args.locked_region,
        "requiredSemanticRegions": args.required_semantic_region,
        "allowedMovingRegions": args.allowed_moving,
        "tolerances": {
            "pivotPixels": 1,
            "visibleScaleRatio": args.scale_tolerance,
            "paletteMeanAbsolute": 0.08,
            "edgeDensityAbsolute": 0.08,
            "lockedRegionMeanAbsolute": 0.06,
            "minimumMarginPixels": 1,
            "missingProtectedPixels": 0,
            "missingDarkOutlinePixels": 0,
            "newInternalHoles": 0,
            "protectedRgbMaxError": 0,
            "componentCountDelta": 0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(contract, indent=2) + "\n")
    print(f"Wrote frame contract to {args.output}")


if __name__ == "__main__":
    main()
