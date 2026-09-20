#!/usr/bin/env python3
"""Tests for preparing the per-frame pose review."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).with_name("build_pose_correspondence.py")
CANVAS = 40
FRAME_COUNT = 4

JUDGEMENTS = (
    "sourcePosePreserved",
    "silhouettePreserved",
    "topologyPreserved",
    "equipmentGeometryPreserved",
    "eyeStatePreserved",
    "negativeSpacesPreserved",
    "noSubstitutedPose",
    "noMasterWarp",
)


def write(path: Path, left: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    for y in range(10, 30):
        for x in range(left, left + 12):
            image.putpixel((x, y), (90, 140, 190, 255))
    image.save(path)


class PoseReportTests(unittest.TestCase):
    def build(self, *extra: str, drop: int | None = None) -> tuple[dict, Path]:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        source, parents, frames = root / "source", root / "parents", root / "frames"
        mapping = []
        for index in range(1, FRAME_COUNT + 1):
            write(source / f"frame-{index:03d}.png", 6 + index)
            write(parents / f"frame-{index:03d}.png", 6 + index)
            if index != drop:
                write(frames / f"frame-{index:03d}.png", 6 + index)
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
        parent_manifest = root / "parent-frame-manifest.json"
        parent_manifest.write_text(
            json.dumps({"parentFramesDirectory": str(parents), "frameMapping": mapping})
        )
        subprocess.run(
            [
                sys.executable, str(SCRIPT), str(source_manifest), str(frames),
                str(root / "qa"), "--parent-frame-manifest", str(parent_manifest), *extra,
            ],
            capture_output=True,
            text=True,
        )
        return json.loads((root / "qa" / "pose-correspondence-report.json").read_text()), root

    def tearDown(self) -> None:
        if hasattr(self, "_directory"):
            self._directory.cleanup()

    def test_bindings_are_filled_in_and_judgements_are_not(self) -> None:
        report, _ = self.build()
        entry = next(f for f in report["frames"] if f["outputFrame"] == 2)
        self.assertEqual(entry["nativeFrame"], 152)
        self.assertEqual(len(entry["sourceSha256"]), 64)
        self.assertEqual(len(entry["outputSha256"]), 64)
        self.assertEqual(len(entry["parentSha256"]), 64)
        self.assertTrue(all(entry[key] is False for key in JUDGEMENTS))
        self.assertEqual(report["status"], "pending-review")

    def test_every_frame_gets_a_comparison_that_exists(self) -> None:
        report, root = self.build()
        for entry in report["frames"]:
            if entry["status"] == "user-visible-blocked":
                continue
            with self.subTest(frame=entry["outputFrame"]):
                self.assertTrue((root / "qa" / entry["sourceOutputComparisonArtifact"]).is_file())

    def test_accept_records_the_reviewer(self) -> None:
        report, _ = self.build("--accept", "agent")
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["reviewer"], "agent")
        entry = report["frames"][0]
        self.assertTrue(all(entry[key] is True for key in JUDGEMENTS))

    def test_a_missing_frame_cannot_be_accepted(self) -> None:
        """Accepting a review of 3 frames must not pass as a review of 4."""
        report, _ = self.build("--accept", "agent", drop=3)
        self.assertEqual(report["status"], "pending-review")
        self.assertEqual(report["missingFrames"], [3])
        blocked = next(f for f in report["frames"] if f["outputFrame"] == 3)
        self.assertEqual(blocked["status"], "user-visible-blocked")

    def test_a_partial_review_is_recorded_as_partial(self) -> None:
        report, _ = self.build("--accept", "agent", "--accept-frames", "1-2")
        self.assertEqual(report["status"], "pending-review")
        self.assertEqual(report["pendingFrames"], [3, 4])
        first = next(f for f in report["frames"] if f["outputFrame"] == 1)
        third = next(f for f in report["frames"] if f["outputFrame"] == 3)
        self.assertTrue(first["sourcePosePreserved"])
        self.assertFalse(third["sourcePosePreserved"])


if __name__ == "__main__":
    unittest.main()
