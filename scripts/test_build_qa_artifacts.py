#!/usr/bin/env python3
"""Tests for rendering visual QA artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
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
    def build(self, *extra: str, drop: int | None = None) -> tuple[dict, Path]:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        source, frames = root / "source", root / "frames"
        mapping = []
        for index in range(1, FRAME_COUNT + 1):
            write(source / f"frame-{index:03d}.png", 8 + index)
            if index != drop:
                write(frames / f"frame-{index:03d}.png", 8 + index)
            mapping.append(
                {
                    "outputFrame": index,
                    "outputFile": f"frame-{index:03d}.png",
                    "nativeFrame": 150 + index,
                    "sourceFile": f"frame-{index:03d}.png",
                }
            )
        source_manifest = root / "source-frame-manifest.json"
        source_manifest.write_text(
            json.dumps({"sourceFramesDirectory": str(source), "frameMapping": mapping})
        )
        manifest = root / "source-frame-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "sourceFrameManifest": str(source_manifest),
                    "frameMapping": mapping,
                }
            )
        )
        subprocess.run(
            [
                sys.executable, str(SCRIPT), str(manifest), str(frames),
                str(root / "qa" / "artifacts"), "--fps", "24", *extra,
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


class GifPreviewTests(QaArtifactTests):
    """The GIF is the normal-speed preview: it loops by itself wherever it is
    opened, where an MP4 has to be played and replayed by hand."""

    def test_the_gif_plays_at_normal_speed_and_loops(self) -> None:
        _, root = self.build()
        found = list(root.rglob("preview.gif"))
        self.assertEqual(len(found), 1, found)
        gif = Image.open(found[0])
        self.assertEqual(gif.info.get("loop"), 0)

    def test_the_gif_holds_its_loop_length_despite_centisecond_delays(self) -> None:
        """24fps is 41.67ms a frame, which GIF cannot store. A uniform 40ms
        runs 4% fast; distributing the rounding keeps the loop its true length."""
        from build_qa_artifacts import gif_delays

        for fps, count in ((24.0, 48), (12.0, 24), (30.0, 60)):
            with self.subTest(fps=fps):
                delays = gif_delays(count, fps)
                self.assertEqual(len(delays), count)
                self.assertAlmostEqual(sum(delays) / 1000.0, count / fps, places=3)
                self.assertTrue(all(d % 10 == 0 and d >= 10 for d in delays))

    def test_the_gif_is_composited_on_black(self) -> None:
        """Matching the exact-FPS MP4, so an edge reads the same way in both."""
        _, root = self.build()
        gif = Image.open(next(iter(root.rglob("preview.gif"))))
        gif.seek(0)
        corner = np.asarray(gif.convert("RGB"))[0, 0]
        self.assertTrue((corner < 8).all(), f"corner was {corner}, expected black")

    def test_no_slow_mp4_is_written(self) -> None:
        _, root = self.build()
        self.assertEqual(list(root.rglob("preview-slow.mp4")), [])
