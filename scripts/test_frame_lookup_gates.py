#!/usr/bin/env python3
"""Regression tests for index-bound frame lookup and honest lock/repair status."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


CORRESPONDENCE = Path(__file__).with_name("validate_source_correspondence.py")
TEMPORAL = Path(__file__).with_name("validate_temporal_sequence.py")

CANVAS = 64
FRAME_COUNT = 4


def write_sprite(path: Path, left: int, fill: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, 20, left + 19, 49), fill=fill)
    image.save(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(source_dir: Path) -> dict[str, object]:
    mapping = []
    for index in range(1, FRAME_COUNT + 1):
        source = source_dir / f"frame-{index:03d}.png"
        mapping.append(
            {
                "outputFrame": index,
                "outputFile": f"frame-{index:03d}.png",
                "nativeFrame": 100 + index - 1,
                "sourceFile": source.name,
                "timestampSeconds": round((index - 1) / 24, 6),
                "classification": "source-frame-gpt-edit",
                "sourceFrameRequired": True,
                "sourceSha256": sha256(source),
                "rgbChanged": True,
                "geometryChanged": False,
                "held": False,
                "interpolated": False,
                "generated": True,
            }
        )
    return {
        "version": 3,
        "frameConstruction": "one-to-one-source",
        "mappingRole": "selected-source-frame-authority",
        "processingType": "one-to-one-source-processing",
        "backgroundRemovalTool": "GPT Image",
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "sourceFramesDirectory": str(source_dir),
        "sourceFps": 24,
        "outputFps": 24,
        "frameCount": FRAME_COUNT,
        "sharedTransform": {"scale": 1.0, "offset": [0, 0], "canvas": [CANVAS, CANVAS]},
        "frameMapping": mapping,
    }


def pose_report(source: dict[str, object], frames: Path) -> dict[str, object]:
    """An accepted pose review for whichever frames are present on disk."""
    records = []
    for record in source["frameMapping"]:
        index = int(record["outputFrame"])
        output = frames / f"frame-{index:03d}.png"
        if not output.is_file():
            continue
        records.append(
            {
                "outputFrame": index,
                "nativeFrame": record["nativeFrame"],
                "sourceFile": record["sourceFile"],
                "sourceSha256": record["sourceSha256"],
                "outputSha256": sha256(output),
                "status": "accepted",
                "sourcePosePreserved": True,
                "noSubstitutedPose": True,
                "noMasterWarp": True,
                "silhouettePreserved": True,
                "topologyPreserved": True,
                "equipmentGeometryPreserved": True,
                "eyeStatePreserved": True,
                "negativeSpacesPreserved": True,
                "sourceOutputComparisonArtifact": f"qa/pairs/frame-{index:03d}.png",
            }
        )
    return {
        "status": "accepted",
        "reviewMethod": "full-frame-source-output-comparison",
        "frames": records,
    }


class FrameLookupTests(unittest.TestCase):
    """A hole in the frames directory must be named against its own index."""

    def run_correspondence(self, drop: int | None) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            frames = root / "frames"
            source_dir.mkdir()
            frames.mkdir()
            for index in range(1, FRAME_COUNT + 1):
                write_sprite(source_dir / f"frame-{index:03d}.png", 10 + index, (0, 200, 0, 255))
                if index != drop:
                    write_sprite(frames / f"frame-{index:03d}.png", 10 + index, (80, 120, 160, 255))
            source = source_manifest(source_dir)
            manifest_path = root / "source-frame-manifest.json"
            manifest_path.write_text(json.dumps(source))
            pose_path = root / "pose-correspondence-report.json"
            pose_path.write_text(json.dumps(pose_report(source, frames)))
            subprocess.run(
                [
                    sys.executable,
                    str(CORRESPONDENCE),
                    str(manifest_path),
                    str(frames),
                    str(root / "qa"),
                    "--pose-correspondence-report",
                    str(pose_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            return json.loads((root / "qa" / "source-correspondence-report.json").read_text())

    def test_missing_frame_is_reported_against_its_own_index(self) -> None:
        report = self.run_correspondence(drop=3)
        blocked = [r for r in report["frames"] if r["status"] != "accepted"]
        self.assertEqual([r["outputFrame"] for r in blocked], [3])
        self.assertTrue(any("frame 3: missing output frame" in e for e in report["errors"]))

    def test_frames_after_a_hole_keep_their_own_native_frame(self) -> None:
        report = self.run_correspondence(drop=3)
        fourth = next(r for r in report["frames"] if r["outputFrame"] == 4)
        self.assertEqual(fourth["nativeFrame"], 103)

    def test_complete_directory_has_no_lookup_errors(self) -> None:
        report = self.run_correspondence(drop=None)
        self.assertFalse(any("missing output frame" in e for e in report["errors"]))
        self.assertFalse(any("unmapped files" in e for e in report["errors"]))


class TemporalHoleTests(unittest.TestCase):
    """A gap must not let the frames either side become neighbours."""

    CONTRACT = {
        "canvas": [CANVAS, CANVAS],
        "statefulRegions": [],
        "lockedRegions": [],
        "negativeSpaceRegions": [],
        "approvedHoldTransitions": [],
        "approvedTemporalTransitions": [],
        "temporalLimits": {
            "maximumDuplicateRatio": 0.1,
            "maximumConsecutiveHolds": 1,
            "maximumMotionSpikeRatio": 2.0,
            "maximumSilhouetteSpikeRatio": 1.8,
            "maximumVisibleAreaStepRatio": 0.03,
            "maximumBoundingBoxSizeStepPixels": 3,
            "maximumCentroidSizeStepPixels": 2,
            "maximumCentroidStepPixels": 2,
            "maximumCentroidAccelerationPixels": 1.5,
            "maximumBoundingBoxSizeAccelerationPixels": 4,
            "maximumLoopSeamRatio": 100,
        },
        "tolerances": {"lockedRegionMeanAbsolute": 0.06},
    }

    def run_temporal(self, drop: int, with_manifest: bool) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            frames = root / "frames"
            source_dir.mkdir()
            frames.mkdir()
            for index in range(1, FRAME_COUNT + 1):
                write_sprite(source_dir / f"frame-{index:03d}.png", 10 + index, (0, 200, 0, 255))
                if index != drop:
                    write_sprite(frames / f"frame-{index:03d}.png", 10 + index, (80, 120, 160, 255))
            manifest_path = root / "source-frame-manifest.json"
            manifest_path.write_text(json.dumps(source_manifest(source_dir)))
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(self.CONTRACT))
            command = [
                sys.executable,
                str(TEMPORAL),
                str(contract_path),
                str(frames),
                str(root / "qa"),
                "--fps",
                "24",
            ]
            if with_manifest:
                command += ["--frame-manifest", str(manifest_path)]
            subprocess.run(command, text=True, capture_output=True, check=False)
            return json.loads((root / "qa" / "temporal-validation-report.json").read_text())

    def test_a_hole_is_named_when_the_manifest_is_supplied(self) -> None:
        report = self.run_temporal(drop=3, with_manifest=True)
        self.assertEqual(report["status"], "repair-needed")
        self.assertIn("missing output frame 3", report["errors"])

    def test_transitions_are_numbered_by_frame_not_by_position(self) -> None:
        report = self.run_temporal(drop=3, with_manifest=True)
        transitions = {f["transition"] for f in report["geometryTransitionFailures"]}
        self.assertNotIn("2->3", transitions, "frame 3 is absent; 2->4 is the real gap")

    def test_a_complete_sequence_needs_no_hole_report(self) -> None:
        report = self.run_temporal(drop=0, with_manifest=True)
        self.assertFalse([e for e in report["errors"] if "missing" in e])


if __name__ == "__main__":
    unittest.main()
