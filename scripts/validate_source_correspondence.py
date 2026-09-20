#!/usr/bin/env python3
"""Verify one-to-one correspondence with every selected native video frame."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from delivery_policy import (
    ONE_TO_ONE,
    mapping_manifest_errors,
    parent_frame_manifest_errors,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--pose-correspondence-report",
        type=Path,
        help="Required for GPT Image; full-frame source/output pose review JSON",
    )
    parser.add_argument("--parent-frame-manifest", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.source_manifest.read_text())
    errors = mapping_manifest_errors(manifest, ONE_TO_ONE)
    tool = manifest.get("backgroundRemovalTool")
    transform = manifest.get("sharedTransform", {})
    if float(transform.get("scale", 0)) != 1.0:
        errors.append("one-to-one validation currently requires scale=1.0")
    canvas = tuple(int(value) for value in transform.get("canvas", []))
    offset = tuple(int(value) for value in transform.get("offset", []))
    if len(canvas) != 2 or len(offset) != 2:
        raise SystemExit("manifest sharedTransform requires canvas and offset pairs")

    mapping = list(manifest.get("frameMapping", []))
    parent_records: list[dict[str, object]] = []
    alpha_repair = args.parent_frame_manifest is not None
    if args.parent_frame_manifest:
        parent_manifest = json.loads(args.parent_frame_manifest.read_text())
        errors.extend(parent_frame_manifest_errors(parent_manifest, manifest))
        parent_records = list(parent_manifest.get("frameMapping", []))
    source_dir = Path(manifest["sourceFramesDirectory"])
    frames = sorted(args.frames_dir.glob("frame-*.png"))
    if len(frames) != len(mapping):
        errors.append(f"mapping/frame count mismatch {len(mapping)}/{len(frames)}")

    pose_records: dict[int, dict[str, object]] = {}
    if tool == "GPT Image":
        if not args.pose_correspondence_report:
            errors.append("GPT Image requires --pose-correspondence-report")
        else:
            pose_report = json.loads(args.pose_correspondence_report.read_text())
            if pose_report.get("status") != "accepted":
                errors.append("pose correspondence report is not accepted")
            if pose_report.get("reviewMethod") != "full-frame-source-output-comparison":
                errors.append("pose report did not use full-frame source/output comparison")
            for item in pose_report.get("frames", []):
                if isinstance(item, dict) and isinstance(item.get("outputFrame"), int):
                    pose_records[int(item["outputFrame"])] = item

    records: list[dict[str, object]] = []
    for index, (record, frame_path) in enumerate(zip(mapping, frames), start=1):
        frame_errors: list[str] = []
        if record.get("outputFile") != frame_path.name:
            frame_errors.append(
                f"output filename={frame_path.name} expected={record.get('outputFile')}"
            )
        source_path = source_dir / str(record["sourceFile"])
        source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source_digest != record.get("sourceSha256"):
            frame_errors.append("selected source frame SHA-256 does not match manifest")
        output = np.asarray(Image.open(frame_path).convert("RGBA"), dtype=np.uint8)
        output_digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
        if (output.shape[1], output.shape[0]) != canvas:
            frame_errors.append(
                f"canvas={(output.shape[1], output.shape[0])} expected={canvas}"
            )

        if tool == "GPT Image":
            pose = pose_records.get(index, {})
            required_pose = {
                "nativeFrame": record.get("nativeFrame"),
                "sourceFile": record.get("sourceFile"),
                "sourceSha256": record.get("sourceSha256"),
                "outputSha256": output_digest,
                "status": "accepted",
                "sourcePosePreserved": True,
                "noSubstitutedPose": True,
                "noMasterWarp": True,
                "silhouettePreserved": True,
                "topologyPreserved": True,
                "equipmentGeometryPreserved": True,
                "eyeStatePreserved": True,
                "negativeSpacesPreserved": True,
            }
            for key, value in required_pose.items():
                if pose.get(key) != value:
                    frame_errors.append(
                        f"pose report {key}={pose.get(key)!r} expected={value!r}"
                    )
            if not pose.get("sourceOutputComparisonArtifact"):
                frame_errors.append("pose report lacks sourceOutputComparisonArtifact")
            if alpha_repair:
                parent = parent_records[index - 1] if index <= len(parent_records) else {}
                required_parent = {
                    "parentSha256": parent.get("parentSha256"),
                    "parentGeometryPreserved": True,
                    "parentForegroundPreserved": True,
                }
                for key, value in required_parent.items():
                    if pose.get(key) != value:
                        frame_errors.append(
                            f"pose report {key}={pose.get(key)!r} expected={value!r}"
                        )
                if not pose.get("parentOutputComparisonArtifact"):
                    frame_errors.append("pose report lacks parentOutputComparisonArtifact")

        records.append(
            {
                "outputFrame": index,
                "nativeFrame": record.get("nativeFrame"),
                "sourceFile": str(source_path),
                "sourceSha256": source_digest,
                "outputSha256": output_digest,
                "status": "accepted" if not frame_errors else "repair-needed",
                "errors": frame_errors,
            }
        )
        errors.extend(f"frame {index}: {error}" for error in frame_errors)

    errors = list(dict.fromkeys(errors))
    report = {
        "status": "accepted" if not errors else "repair-needed",
        "backgroundRemovalTool": tool,
        "correspondenceType": (
            "selected-frame-parent-and-pose"
            if alpha_repair
            else "selected-frame-and-pose"
        ),
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
