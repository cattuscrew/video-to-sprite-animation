#!/usr/bin/env python3
"""A one-shot animation must survive the gate built for loops.

An attack, death or cast ends nowhere near where it started. The seam gate
compares the last frame with the first, which for a loop is the join and for a
one-shot is simply the two ends of the action -- so before the loop type was
carried through, every correct one-shot failed validation for the crime of not
repeating.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
CANVAS = 64


def contract(path: Path, loop_type: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": 4,
                "canvas": [CANVAS, CANVAS],
                "loopType": loop_type,
                "tolerances": {},
                "temporalLimits": {
                    # Only the seam is under test; the per-pair gates are
                    # opened up so a deliberate travelling sprite passes them.
                    "maximumVisibleAreaStepRatio": 1.0,
                    "maximumBoundingBoxSizeStepPixels": 64,
                    "maximumBoundingBoxSizeAccelerationPixels": 64,
                    "maximumCentroidStepPixels": 64,
                    "maximumCentroidAccelerationPixels": 64,
                    "maximumSilhouetteSpikeRatio": 100.0,
                    "maximumMotionSpikeRatio": 100.0,
                },
            }
        )
    )
    return path


def travelling_sequence(directory: Path, frames: int = 20) -> Path:
    """A sprite that walks steadily left to right and stops.

    Every step is the same size and overlaps its neighbour, so the only large
    transition in the clip is the wraparound from the last frame back to the
    first -- where the sprite has travelled far enough not to overlap at all.
    That is a bad loop and a perfectly ordinary one-shot.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(frames):
        image = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
        left = 2 + index * 2
        image[20:50, left : left + 12] = (80, 120, 160, 255)
        Image.fromarray(image, "RGBA").save(directory / f"frame-{index + 1:03d}.png")
    return directory


def run(contract_path: Path, frames: Path, output: Path, *extra: str):
    return subprocess.run(
        [sys.executable, str(HERE / "validate_temporal_sequence.py"),
         str(contract_path), str(frames), str(output), "--fps", "12", *extra],
        capture_output=True,
        text=True,
    )


class OneShotSeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.frames = travelling_sequence(self.root / "frames")

    def tearDown(self) -> None:
        self._directory.cleanup()

    def report(self, loop_type: str, *extra: str) -> dict:
        path = contract(self.root / f"{loop_type}.json", loop_type)
        output = self.root / f"out-{loop_type}"
        run(path, self.frames, output, *extra)
        return json.loads((output / "temporal-validation-report.json").read_text())

    def test_a_loop_is_still_judged_on_its_seam(self) -> None:
        report = self.report("natural-loop")
        self.assertIsNotNone(report["loopSeamRatio"])
        self.assertTrue(
            any("seam" in error for error in report["errors"]),
            f"a sprite that ends far from where it began is a bad loop: {report['errors']}",
        )

    def test_a_one_shot_is_not_judged_on_a_seam_it_does_not_have(self) -> None:
        report = self.report("one-shot")
        self.assertIsNone(report["loopSeamRatio"])
        self.assertEqual(
            [error for error in report["errors"] if "seam" in error], []
        )

    def test_the_flag_overrides_the_contract(self) -> None:
        """So an existing contract can be re-validated without rebuilding it."""
        path = contract(self.root / "override.json", "natural-loop")
        output = self.root / "out-override"
        run(path, self.frames, output, "--loop-type", "one-shot")
        report = json.loads((output / "temporal-validation-report.json").read_text())
        self.assertEqual(report["loopType"], "one-shot")
        self.assertIsNone(report["loopSeamRatio"])

    def test_the_seam_frame_is_not_counted_as_a_transition_in_a_one_shot(self) -> None:
        """The wraparound pair must be absent, not merely unjudged: left in the
        motion median it drags every spike threshold upward."""
        loop = self.report("natural-loop")
        shot = self.report("one-shot")
        self.assertEqual(len(shot["motionEnergy"]), len(loop["motionEnergy"]) - 1)


if __name__ == "__main__":
    unittest.main()
