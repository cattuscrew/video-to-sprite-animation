#!/usr/bin/env python3
"""Write a native-frame motion-reference map for GPT Image regeneration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


CLASSIFICATIONS = (
    "source-derived-deformation",
    "generated",
    "interpolated",
    "held/reused",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--first-native-frame", type=int, required=True)
    parser.add_argument("--source-fps", type=float, required=True)
    parser.add_argument("--output-fps", type=float, required=True)
    parser.add_argument("--classification", choices=CLASSIFICATIONS, required=True)
    args = parser.parse_args()

    files = sorted(args.source_frames.glob("*.png"))
    if not files:
        raise SystemExit(f"No source PNGs found in {args.source_frames}")

    mapping = []
    for index, path in enumerate(files, start=1):
        native_frame = args.first_native_frame + index - 1
        classification = args.classification
        mapping.append(
            {
                "outputFrame": index,
                "outputFile": f"frame-{index:03d}.png",
                "nativeFrame": native_frame,
                "sourceFile": path.name,
                "timestampSeconds": (native_frame - 1) / args.source_fps,
                "classification": classification,
                "rgbChanged": True,
                "geometryChanged": classification != "held/reused",
                "held": classification == "held/reused",
                "interpolated": classification == "interpolated",
                "generated": classification == "generated",
            }
        )

    manifest = {
        "version": 3,
        "frameConstruction": "synthesized",
        "mappingRole": "motion-reference-only",
        "processingType": "native-motion-reference",
        "backgroundRemovalTool": "GPT Image",
        "sourceFramesDirectory": str(args.source_frames.resolve()),
        "sourceFps": args.source_fps,
        "outputFps": args.output_fps,
        "frameCount": len(mapping),
        "frameMapping": mapping,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "frames": len(mapping),
                "status": "motion-reference-mapped",
                "classification": args.classification,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
