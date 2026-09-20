#!/usr/bin/env python3
"""Restore approved opaque foreground RGB while preserving GPT alpha and edge cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("parent_manifest", type=Path)
    parser.add_argument("gpt_frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--opaque-threshold", type=int, default=250)
    parser.add_argument("--allow-missing", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.parent_manifest.read_text())
    parent_dir = Path(manifest["parentFramesDirectory"])
    records = list(manifest.get("frameMapping", []))
    args.output.mkdir(parents=True, exist_ok=True)
    report_records = []

    for index, record in enumerate(records, start=1):
        name = f"frame-{index:03d}.png"
        parent_path = parent_dir / str(record["parentFile"])
        gpt_path = args.gpt_frames / name
        if not gpt_path.is_file():
            if args.allow_missing:
                report_records.append(
                    {"outputFrame": index, "status": "user-visible-blocked", "reason": "missing GPT frame"}
                )
                continue
            raise SystemExit(f"missing GPT frame: {gpt_path}")
        parent = np.asarray(Image.open(parent_path).convert("RGBA"), dtype=np.uint8)
        gpt = np.asarray(Image.open(gpt_path).convert("RGBA"), dtype=np.uint8).copy()
        if parent.shape != gpt.shape:
            raise SystemExit(f"{name}: parent/GPT canvas mismatch")
        stable = (
            (parent[:, :, 3] >= args.opaque_threshold)
            & (gpt[:, :, 3] >= args.opaque_threshold)
        )
        gpt[:, :, :3][stable] = parent[:, :, :3][stable]
        output_path = args.output / name
        Image.fromarray(gpt, "RGBA").save(output_path, format="PNG", optimize=False)
        report_records.append(
            {
                "outputFrame": index,
                "parentSha256": sha256(parent_path),
                "gptInputSha256": sha256(gpt_path),
                "outputSha256": sha256(output_path),
                "opaqueRgbPixelsRestored": int(np.count_nonzero(stable)),
                "alphaChangedByLock": False,
                "status": "complete",
            }
        )

    report = {
        "status": "complete",
        "method": "approved-parent-opaque-rgb-lock",
        "backgroundRemovalTool": "GPT Image",
        "alphaAuthority": "gpt-image-alpha-repair",
        "opaqueThreshold": args.opaque_threshold,
        "frames": report_records,
        "blockedFrameCount": sum(r.get("status") == "user-visible-blocked" for r in report_records),
    }
    (args.output.parent / "parent-foreground-lock-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
