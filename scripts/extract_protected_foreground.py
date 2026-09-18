#!/usr/bin/env python3
"""Faithful native-resolution extraction with border-connected background removal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from protected_background import (
    extract_protected_foreground,
    place_rgba,
    resize_rgba_premultiplied,
)


def parse_pair(value: str) -> tuple[int, int]:
    parts = [int(part.strip()) for part in value.lower().replace("x", ",").split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected x,y or widthxheight")
    return parts[0], parts[1]


def metrics(alpha: np.ndarray) -> tuple[list[int], list[float | int]]:
    ys, xs = np.nonzero(alpha > 18)
    if not len(xs):
        raise ValueError("extraction produced no foreground")
    bounds = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    bottom = int(ys.max())
    contact = xs[ys >= bottom - 8]
    return bounds, [round(float(contact.min() + contact.max()) / 2.0, 2), bottom]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path, help="Native-resolution decoded source frames")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--canvas", type=parse_pair, default=(512, 512))
    parser.add_argument("--scale", type=float, required=True)
    parser.add_argument("--offset", type=parse_pair, required=True)
    parser.add_argument("--seed-threshold", type=float, default=12.0)
    parser.add_argument("--grow-threshold", type=float, default=80.0)
    parser.add_argument("--border-width", type=int, default=24)
    args = parser.parse_args()

    files = sorted(args.input_dir.glob("*.png"))
    if not files:
        raise SystemExit(f"No PNG frames found in {args.input_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    for index, path in enumerate(files, start=1):
        source = Image.open(path).convert("RGB")
        rgb = np.asarray(source, dtype=np.uint8)
        result = extract_protected_foreground(
            rgb,
            seed_threshold=args.seed_threshold,
            grow_threshold=args.grow_threshold,
            border_width=args.border_width,
        )
        resized_size = (round(source.width * args.scale), round(source.height * args.scale))
        resized = resize_rgba_premultiplied(result.rgba, resized_size)
        output = place_rgba(resized, args.canvas, args.offset)
        bounds, pivot = metrics(output[:, :, 3])
        output_path = args.output_dir / f"frame-{index:03d}.png"
        Image.fromarray(output, "RGBA").save(output_path)
        records.append(
            {
                "source": path.name,
                "output": output_path.name,
                "sourceSize": list(source.size),
                "backgroundRemovalResolution": list(source.size),
                "canvas": list(args.canvas),
                "scale": args.scale,
                "offset": list(args.offset),
                "keyColor": list(result.key_rgb),
                "seedThreshold": args.seed_threshold,
                "growThreshold": args.grow_threshold,
                "foregroundComponents": result.foreground_components,
                "visibleBounds": bounds,
                "contactPivot": pivot,
            }
        )

    report = {
        "status": "candidate-needs-proof-frame-or-batch-validation",
        "policy": {
            "backgroundRemoval": "native-resolution border-connected",
            "componentDeletion": False,
            "erosion": False,
            "edgeRgbRewrite": False,
            "resize": "single premultiplied-RGBA pass",
            "perFrameRecenter": False,
        },
        "sharedSettings": {
            "canvas": list(args.canvas),
            "scale": args.scale,
            "offset": list(args.offset),
            "seedThreshold": args.seed_threshold,
            "growThreshold": args.grow_threshold,
            "borderWidth": args.border_width,
        },
        "frames": records,
    }
    (args.output_dir / "extraction-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"frames": len(records), "status": report["status"]}, indent=2))


if __name__ == "__main__":
    main()
