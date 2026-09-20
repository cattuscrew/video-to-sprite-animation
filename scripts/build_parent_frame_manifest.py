#!/usr/bin/env python3
"""Bind approved parent sprites to their exact selected native source frames."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from delivery_policy import ONE_TO_ONE, mapping_manifest_errors, parent_frame_manifest_errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("parent_frames", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = json.loads(args.source_manifest.read_text())
    source_errors = mapping_manifest_errors(source, ONE_TO_ONE)
    if source_errors:
        raise SystemExit("invalid source manifest: " + "; ".join(source_errors))

    parent_files = sorted(args.parent_frames.glob("frame-*.png"))
    source_records = list(source["frameMapping"])
    if len(parent_files) != len(source_records):
        raise SystemExit(
            f"parent/source frame count mismatch {len(parent_files)}/{len(source_records)}"
        )

    records = []
    for index, (parent, source_record) in enumerate(
        zip(parent_files, source_records), start=1
    ):
        expected = f"frame-{index:03d}.png"
        if parent.name != expected:
            raise SystemExit(f"parent frame {index} must be named {expected}")
        records.append(
            {
                "outputFrame": index,
                "nativeFrame": source_record["nativeFrame"],
                "sourceFile": source_record["sourceFile"],
                "sourceSha256": source_record["sourceSha256"],
                "parentFile": parent.name,
                "parentSha256": hashlib.sha256(parent.read_bytes()).hexdigest(),
                "parentRole": "approved-foreground-edit-target",
                "classification": "source-frame-gpt-alpha-repair",
                "geometryChanged": False,
            }
        )

    manifest = {
        "version": 1,
        "frameConstruction": "one-to-one-source",
        "processingMode": "gpt-image-alpha-repair",
        "backgroundRemovalTool": "GPT Image",
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "sourceFrameManifest": str(args.source_manifest.resolve()),
        "parentFramesDirectory": str(args.parent_frames.resolve()),
        "frameCount": len(records),
        "frameMapping": records,
    }
    errors = parent_frame_manifest_errors(manifest, source)
    if errors:
        raise SystemExit("invalid parent-frame manifest: " + "; ".join(errors))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": "mapped", "frames": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
