#!/usr/bin/env python3
"""Tests for rendering visual QA artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).with_name("build_qa_artifacts.py")
CANVAS = 48
FRAME_COUNT = 6


def write(path: Path, left: int, opaque: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    for y in range(12, 36):
        for x in range(left, left + 16):
            image.putpixel((x, y), (90, 140, 190, 255 if opaque else 120))
    image.save(path)


class QaArtifactTests(unittest.TestCase):
    def build(self, drop: int | None = None) -> tuple[dict, Path]:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        source, parents, frames = root / "source", root / "parents", root / "frames"
        mapping = []
        for index in range(1, FRAME_COUNT + 1):
            write(source / f"frame-{index:03d}.png", 8 + index)
            write(parents / f"frame-{index:03d}.png", 8 + index)
            if index != drop:
                write(frames / f"frame-{index:03d}.png", 8 + index)
            mapping.append(
                {
                    "outputFrame": index,
                    "outputFile": f"frame-{index:03d}.png",
                    "nativeFrame": 150 + index,
                    "sourceFile": f"frame-{index:03d}.png",
                    "parentFile": f"frame-{index:03d}.png",
                }
            )
        source_manifest = root / "source-frame-manifest.json"
        source_manifest.write_text(
            json.dumps({"sourceFramesDirectory": str(source), "frameMapping": mapping})
        )
        manifest = root / "parent-frame-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "parentFramesDirectory": str(parents),
                    "sourceFrameManifest": str(source_manifest),
                    "frameMapping": mapping,
                }
            )
        )
        subprocess.run(
            [
                sys.executable, str(SCRIPT), str(manifest), str(frames),
                str(root / "qa" / "artifacts"), "--fps", "24",
            ],
            capture_output=True,
            text=True,
        )
        return json.loads((root / "qa" / "visual-qa-report.json").read_text()), root

    def tearDown(self) -> None:
        if hasattr(self, "_directory"):
            self._directory.cleanup()

    def test_every_named_artifact_exists_on_disk(self) -> None:
        report, root = self.build()
        for name, value in report["artifacts"].items():
            with self.subTest(artifact=name):
                self.assertTrue((root / "qa" / value).exists(), name)

    def test_nothing_is_marked_reviewed(self) -> None:
        """Rendering a picture is not the same as having looked at it."""
        report, _ = self.build()
        flags = [k for k in report if k.endswith("Reviewed") or k == "sourceMotionCompared"]
        self.assertTrue(flags)
        self.assertTrue(all(report[flag] is False for flag in flags))
        self.assertEqual(report["status"], "pending-review")

    def test_comparisons_follow_the_link_to_the_source_manifest(self) -> None:
        report, _ = self.build()
        self.assertGreater(report["comparisonSheets"], 0)

    def test_a_missing_frame_is_named_in_the_report(self) -> None:
        report, _ = self.build(drop=3)
        self.assertEqual(report["missingFrames"], [3])
        self.assertEqual(report["frameCount"], FRAME_COUNT - 1)

    def test_only_the_named_checks_are_recorded(self) -> None:
        report, _ = self.build("--reviewed", "onionSkin,triplets")
        self.assertTrue(report["onionSkinReviewed"])
        self.assertTrue(report["tripletsReviewed"])
        self.assertFalse(report["normalSpeedReviewed"])
        self.assertEqual(report["status"], "pending-review")
        self.assertIn("normalSpeed", report["outstandingChecks"])

    def test_all_checks_named_accepts_the_report(self) -> None:
        report, _ = self.build(
            "--reviewed",
            "normalSpeed,slowSpeed,triplets,onionSkin,sourceOutputPairs,"
            "sourceMotion,topologyAndLandmarks",
        )
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["outstandingChecks"], [])

    def test_a_missing_frame_blocks_acceptance_even_when_all_checks_are_named(self) -> None:
        report, _ = self.build(
            "--reviewed",
            "normalSpeed,slowSpeed,triplets,onionSkin,sourceOutputPairs,"
            "sourceMotion,topologyAndLandmarks",
            drop=3,
        )
        self.assertEqual(report["status"], "pending-review")
        self.assertEqual(report["missingFrames"], [3])


if __name__ == "__main__":
    unittest.main()
