#!/usr/bin/env python3
"""Tests for rendering the step-7 transparency proof."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from delivery_policy import transparency_proof_report_errors


SCRIPT = Path(__file__).with_name("build_transparency_proof.py")
CANVAS = 48


def write(path: Path, alpha: int = 255) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    for y in range(12, 36):
        for x in range(16, 32):
            image.putpixel((x, y), (90, 140, 190, alpha))
    image.save(path)


class TransparencyProofTests(unittest.TestCase):
    def build(self, *extra: str) -> tuple[dict, Path]:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        proof, source = root / "proof.png", root / "native-000154.png"
        write(proof)
        Image.new("RGB", (CANVAS, CANVAS), (30, 120, 60)).save(source)
        output = root / "qa"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(proof),
                str(output),
                "--source",
                str(source),
                "--native-frame",
                "154",
                *extra,
            ],
            capture_output=True,
            text=True,
        )
        self.assertIn(result.returncode, (0, 2), result.stderr)
        return json.loads((output / "transparency-proof-report.json").read_text()), output

    def test_renders_all_three_backgrounds_and_both_crop_scales(self) -> None:
        report, output = self.build()
        self.assertEqual(
            report["backgroundsRendered"], ["checkerboard", "white", "black"]
        )
        self.assertEqual(report["cropScales"], [1.0, 4.0])
        for artifact in report["artifacts"].values():
            self.assertTrue(Path(artifact).is_file(), artifact)
        self.assertTrue((output / "proof-bg-removal.png").is_file())

    def test_unreviewed_proof_is_pending_and_blocks_delivery(self) -> None:
        report, _ = self.build()
        self.assertEqual(report["status"], "pending-review")
        self.assertIs(report["userApproved"], False)
        errors = transparency_proof_report_errors(report)
        self.assertTrue(any("not accepted" in error for error in errors))

    def test_accept_records_the_reviewer_and_passes_the_gate(self) -> None:
        report, _ = self.build("--accept", "agent-and-user")
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["reviewer"], "agent-and-user")
        self.assertEqual(transparency_proof_report_errors(report), [])

    def test_source_frame_is_bound_by_digest(self) -> None:
        report, _ = self.build("--accept", "user")
        self.assertEqual(len(report["sourceFrame"]["sha256"]), 64)
        self.assertEqual(report["sourceFrame"]["nativeFrame"], 154)
        self.assertEqual(len(report["proofFrame"]["sha256"]), 64)

    def test_a_checkerboard_only_approval_is_rejected(self) -> None:
        report, _ = self.build("--accept", "user")
        report["backgroundsRendered"] = ["checkerboard"]
        errors = transparency_proof_report_errors(report)
        self.assertTrue(any("on white" in error for error in errors))
        self.assertTrue(any("on black" in error for error in errors))

    def test_magnified_crops_cannot_stand_in_for_full_scale(self) -> None:
        report, _ = self.build("--accept", "user")
        report["cropScales"] = [4.0]
        self.assertTrue(
            any("100%" in error for error in transparency_proof_report_errors(report))
        )


if __name__ == "__main__":
    unittest.main()
