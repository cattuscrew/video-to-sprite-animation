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
LOCK = Path(__file__).with_name("lock_parent_foreground.py")
ALPHA_REPAIR = Path(__file__).with_name("validate_alpha_repair.py")

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


def parent_manifest(parent_dir: Path, source: dict[str, object]) -> dict[str, object]:
    mapping = []
    for record in source["frameMapping"]:
        index = int(record["outputFrame"])
        parent = parent_dir / f"frame-{index:03d}.png"
        mapping.append(
            {
                "outputFrame": index,
                "nativeFrame": record["nativeFrame"],
                "sourceFile": record["sourceFile"],
                "sourceSha256": record["sourceSha256"],
                "parentFile": parent.name,
                "parentSha256": sha256(parent),
                "parentRole": "approved-foreground-edit-target",
                "classification": "source-frame-gpt-alpha-repair",
                "geometryChanged": False,
            }
        )
    return {
        "version": 1,
        "frameConstruction": "one-to-one-source",
        "processingMode": "gpt-image-alpha-repair",
        "backgroundRemovalTool": "GPT Image",
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "sourceFrameManifest": "source-frame-manifest.json",
        "parentFramesDirectory": str(parent_dir),
        "frameCount": FRAME_COUNT,
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


class LockStatusTests(unittest.TestCase):
    """A blocked frame must not be reported as a complete lock."""

    def run_lock(self, drop: int | None) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            parents = root / "parents"
            gpt = root / "gpt"
            for path in (source_dir, parents, gpt):
                path.mkdir()
            for index in range(1, FRAME_COUNT + 1):
                write_sprite(source_dir / f"frame-{index:03d}.png", 10 + index, (0, 200, 0, 255))
                write_sprite(parents / f"frame-{index:03d}.png", 10 + index, (80, 120, 160, 255))
                if index != drop:
                    write_sprite(gpt / f"frame-{index:03d}.png", 10 + index, (81, 121, 161, 255))
            source = source_manifest(source_dir)
            parent_path = root / "parent-frame-manifest.json"
            parent_path.write_text(json.dumps(parent_manifest(parents, source)))
            process = subprocess.run(
                [
                    sys.executable,
                    str(LOCK),
                    str(parent_path),
                    str(gpt),
                    str(root / "locked"),
                    "--allow-missing",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            report = json.loads((root / "parent-foreground-lock-report.json").read_text())
            return process, report

    def test_missing_gpt_frame_blocks_the_lock_report(self) -> None:
        process, report = self.run_lock(drop=2)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertEqual(report["status"], "user-visible-blocked")
        self.assertEqual(report["blockedFrameCount"], 1)

    def test_complete_batch_reports_complete(self) -> None:
        process, report = self.run_lock(drop=None)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["blockedFrameCount"], 0)


class InteriorRgbTests(unittest.TestCase):
    """Interior RGB compared against locked frames measures the parent against itself."""

    def run_repair_validation(self, pre_lock: bool) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            parents = root / "parents"
            repaired = root / "repaired"
            locked = root / "locked"
            for path in (source_dir, parents, repaired, locked):
                path.mkdir()
            for index in range(1, FRAME_COUNT + 1):
                write_sprite(source_dir / f"frame-{index:03d}.png", 10 + index, (0, 200, 0, 255))
                write_sprite(parents / f"frame-{index:03d}.png", 10 + index, (80, 120, 160, 255))
                # The repair shifted interior colour well past the 3.0 MAE limit.
                write_sprite(repaired / f"frame-{index:03d}.png", 10 + index, (120, 160, 200, 255))
                # The lock restored the parent's own pixels.
                write_sprite(locked / f"frame-{index:03d}.png", 10 + index, (80, 120, 160, 255))
            source = source_manifest(source_dir)
            parent_path = root / "parent-frame-manifest.json"
            parent_path.write_text(json.dumps(parent_manifest(parents, source)))
            command = [
                sys.executable,
                str(ALPHA_REPAIR),
                str(parent_path),
                str(locked),
                str(root / "qa" / "alpha-repair-validation.json"),
            ]
            if pre_lock:
                command += ["--pre-lock-frames", str(repaired)]
            subprocess.run(command, text=True, capture_output=True, check=False)
            return json.loads((root / "qa" / "alpha-repair-validation.json").read_text())

    def test_pre_lock_frames_expose_interior_colour_drift(self) -> None:
        report = self.run_repair_validation(pre_lock=True)
        self.assertEqual(report["interiorRgbMeasuredOn"], "pre-lock-repair")
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(all(r["interiorRgbMeanAbsoluteError"] > 3.0 for r in report["frames"]))

    def test_locked_frames_alone_cannot_establish_interior_fidelity(self) -> None:
        report = self.run_repair_validation(pre_lock=False)
        self.assertEqual(report["interiorRgbMeasuredOn"], "delivered-frames")
        self.assertTrue(all(r["interiorRgbMeanAbsoluteError"] == 0.0 for r in report["frames"]))
        self.assertTrue(any("measured on delivered frames" in e for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
