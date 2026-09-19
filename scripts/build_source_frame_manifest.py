#!/usr/bin/env python3
"""Write an auditable output-to-native-frame map before frame processing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--first-native-frame", type=int, required=True)
    parser.add_argument("--source-fps", type=float, required=True)
    parser.add_argument("--output-fps", type=float, required=True)
    parser.add_argument("--canvas", default="720,720")
    parser.add_argument("--offset", default="0,0")
    parser.add_argument("--expected-alpha-dir", type=Path)
    args = parser.parse_args()

    if args.source_fps != args.output_fps:
        raise SystemExit(
            "This exact-source manifest requires matching source/output FPS; "
            "use an explicit sampling manifest for decimation."
        )
    files = sorted(args.source_frames.glob("*.png"))
    if not files:
        raise SystemExit(f"No source PNGs found in {args.source_frames}")
    canvas = [int(value) for value in args.canvas.split(",")]
    offset = [int(value) for value in args.offset.split(",")]
    if len(canvas) != 2 or len(offset) != 2:
        raise SystemExit("--canvas and --offset require x,y pairs")

    mapping = []
    for index, path in enumerate(files, start=1):
        native_frame = args.first_native_frame + index - 1
        mapping.append(
            {
                "outputFrame": index,
                "outputFile": f"frame-{index:03d}.png",
                "nativeFrame": native_frame,
                "sourceFile": path.name,
                "timestampSeconds": (native_frame - 1) / args.source_fps,
                "classification": "exact-source-extraction",
                "rgbChanged": False,
                "geometryChanged": False,
                "held": False,
                "interpolated": False,
                "generated": False,
            }
        )

    manifest = {
        "version": 1,
        "processingType": "exact-source-extraction",
        "sourceFramesDirectory": str(args.source_frames.resolve()),
        "expectedAlphaDirectory": (
            str(args.expected_alpha_dir.resolve()) if args.expected_alpha_dir else None
        ),
        "sourceFps": args.source_fps,
        "outputFps": args.output_fps,
        "frameCount": len(mapping),
        "sharedTransform": {"scale": 1.0, "offset": offset, "canvas": canvas},
        "frameMapping": mapping,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"frames": len(mapping), "status": "mapped"}, indent=2))


if __name__ == "__main__":
    main()
