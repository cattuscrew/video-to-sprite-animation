#!/usr/bin/env python3
"""Regression tests for subtle one-frame redraw enlargement and jitter."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


SCRIPT = Path(__file__).with_name("validate_temporal_sequence.py")


def write_frame(path: Path, left: int, width: int = 20) -> None:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, 20, left + width - 1, 49), fill=(80, 120, 160, 255))
    image.save(path)


def contract() -> dict[str, object]:
    return {
        "canvas": [64, 64],
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
            "maximumBoundingBoxSizeAccelerationPixels": 4,
            "maximumCentroidStepPixels": 2,
            "maximumCentroidAccelerationPixels": 1.5,
            "maximumLoopSeamRatio": 100,
        },
        "tolerances": {"lockedRegionMeanAbsolute": 0.06},
    }


class TemporalJitterTests(unittest.TestCase):
    def run_validator(self, widths: list[int]) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            output = root / "qa"
            frames.mkdir()
            for index, width in enumerate(widths, start=1):
                write_frame(frames / f"frame-{index:03d}.png", 10 + index, width)
            contract_path = root / "contract.json"
            contract_path.write_text(json.dumps(contract()))
            process = subprocess.run(
                [sys.executable, str(SCRIPT), str(contract_path), str(frames), str(output), "--fps", "24"],
                text=True,
                capture_output=True,
                check=False,
            )
            report = json.loads((output / "temporal-validation-report.json").read_text())
            self.assertTrue((output / "temporal-alpha-onion-sheet.png").exists())
            return process, report

    def test_smooth_translation_passes_geometry_gate(self) -> None:
        process, report = self.run_validator([20, 20, 20, 20, 20, 20])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(report["geometryTransitionFailures"], [])
        self.assertEqual(report["geometryAccelerationFailures"], [])

    def test_single_frame_enlargement_is_rejected(self) -> None:
        process, report = self.run_validator([20, 20, 20, 28, 20, 20])
        self.assertEqual(process.returncode, 2)
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(report["geometryTransitionFailures"])
        self.assertTrue(report["geometryAccelerationFailures"])
        self.assertGreater(report["diagnostics"]["flaggedTripletCount"], 0)


if __name__ == "__main__":
    unittest.main()
