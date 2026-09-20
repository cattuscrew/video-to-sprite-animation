#!/usr/bin/env python3
"""Tests for colour flicker: the gate that sees it, and the pass that fixes it."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import normalize_palette
from source_foreground import discover_materials


GATE = Path(__file__).with_name("validate_color_stability.py")
NORMALIZE = Path(__file__).with_name("normalize_palette.py")
CANVAS = 80
GREEN = (16, 245, 50)
FRAME_COUNT = 6
BODY = (120, 110, 90)
TRIM = (40, 150, 60)


def source_frame() -> np.ndarray:
    """An opaque green-screen frame with a solid character in the middle."""
    image = np.empty((CANVAS, CANVAS, 4), dtype=np.uint8)
    image[:, :, :3] = np.array(GREEN, dtype=np.uint8)
    image[:, :, 3] = 255
    image[16:64, 20:60, :3] = BODY
    image[24:56, 28:52, :3] = TRIM
    return image


def output_frame(shift: int = 0, trim_shift: int | None = None) -> np.ndarray:
    """The same character cut out, with each material shiftable on its own.

    Two materials, shiftable independently, because the defect this gate exists
    for is materials drifting in opposite directions while the frame average
    stays put.
    """
    image = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
    body = np.clip(np.array(BODY, dtype=int) + shift, 0, 255).astype(np.uint8)
    trim = np.clip(
        np.array(TRIM, dtype=int) + (shift if trim_shift is None else trim_shift),
        0,
        255,
    ).astype(np.uint8)
    image[16:64, 20:60, :3] = body
    image[24:56, 28:52, :3] = trim
    image[16:64, 20:60, 3] = 255
    return image


def build(root: Path, shifts: list[int], trims: list[int] | None = None) -> tuple[Path, Path]:
    sources, frames = root / "source", root / "frames"
    sources.mkdir(parents=True, exist_ok=True)
    frames.mkdir(parents=True, exist_ok=True)
    mapping = []
    for index, shift in enumerate(shifts, start=1):
        trim = None if trims is None else trims[index - 1]
        Image.fromarray(source_frame(), "RGBA").save(sources / f"frame-{index:03d}.png")
        Image.fromarray(output_frame(shift, trim), "RGBA").save(
            frames / f"frame-{index:03d}.png"
        )
        mapping.append(
            {
                "outputFrame": index,
                "outputFile": f"frame-{index:03d}.png",
                "nativeFrame": 150 + index,
                "sourceFile": f"frame-{index:03d}.png",
            }
        )
    manifest = root / "source-frame-manifest.json"
    manifest.write_text(
        json.dumps({"sourceFramesDirectory": str(sources), "frameMapping": mapping})
    )
    return manifest, frames


def run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *arguments], text=True, capture_output=True
    )


class GateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def report(self, shifts: list[int], *extra: str, trims: list[int] | None = None) -> dict:
        manifest, frames = build(self.root, shifts, trims)
        out = self.root / "color.json"
        run(GATE, str(manifest), str(frames), str(out), *extra)
        return json.loads(out.read_text())

    def test_a_steady_sequence_passes(self) -> None:
        report = self.report([0] * FRAME_COUNT)
        self.assertEqual(report["status"], "accepted", report["errors"])
        self.assertEqual(report["maxStep"], 0.0)

    def test_a_constant_offset_is_not_flicker(self) -> None:
        """Every frame equally wrong is a bias, which the per-frame gate owns.
        This gate must stay quiet about it or it reports the same defect twice."""
        report = self.report([7] * FRAME_COUNT)
        self.assertEqual(report["status"], "accepted", report["errors"])

    def test_two_materials_moving_oppositely_are_caught(self) -> None:
        """The case a frame average cannot see: one material up, the other
        down by the same amount, so the mean over the character never moves."""
        report = self.report([0, 12, 0, 12, 0, 12], trims=[0, -12, 0, -12, 0, -12])
        self.assertEqual(report["status"], "repair-needed")
        self.assertEqual(report["failedTransitionCount"], 5)

    def test_alternating_frames_are_caught(self) -> None:
        report = self.report([0, 14, 0, 14, 0, 14])
        self.assertEqual(report["status"], "repair-needed")
        self.assertEqual(report["failedTransitionCount"], 5)
        self.assertTrue(any("steps" in e for e in report["errors"]))

    def test_one_odd_frame_fails_both_of_its_transitions(self) -> None:
        report = self.report([0, 0, 14, 0, 0, 0])
        failed = [(t["from"], t["to"]) for t in report["transitions"] if t["status"] != "accepted"]
        self.assertEqual(failed, [(2, 3), (3, 4)])

    def test_the_loop_seam_is_checked_when_asked(self) -> None:
        report = self.report([0, 0, 0, 0, 0, 14], "--loop")
        seam = [t for t in report["transitions"] if (t["from"], t["to"]) == (6, 1)]
        self.assertEqual(len(seam), 1)
        self.assertEqual(seam[0]["status"], "repair-needed")

    def test_a_missing_frame_does_not_make_its_neighbours_adjacent(self) -> None:
        manifest, frames = build(self.root, [0, 0, 14, 0, 0, 0])
        (frames / "frame-003.png").unlink()
        out = self.root / "color.json"
        run(GATE, str(manifest), str(frames), str(out))
        report = json.loads(out.read_text())
        self.assertTrue(any("missing output frame 3" in e for e in report["errors"]))
        self.assertNotIn((2, 4), [(t["from"], t["to"]) for t in report["transitions"]])


class NormalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)

    def tearDown(self) -> None:
        self._directory.cleanup()

    def materials(self) -> np.ndarray:
        return discover_materials([source_frame()])

    def test_two_materials_are_corrected_independently(self) -> None:
        """A single frame-wide offset cannot do this: the two materials are
        wrong in opposite directions and cancel in the average."""
        skewed = output_frame(12, trim_shift=-12)
        corrected, record = normalize_palette.normalize(
            skewed, source_frame(), self.materials()
        )
        self.assertEqual(record["status"], "accepted", record.get("error"))
        self.assertGreaterEqual(record["materialsCorrected"], 2)
        truth = output_frame(0).astype(int)
        inside = truth[:, :, 3] > 0
        self.assertLess(
            float(np.abs(corrected.astype(int) - truth)[inside][:, :3].mean()), 1.5
        )

    def test_alpha_is_never_touched(self) -> None:
        original = output_frame(9)
        corrected, _ = normalize_palette.normalize(
            original, source_frame(), self.materials()
        )
        self.assertTrue(np.array_equal(corrected[:, :, 3], original[:, :, 3]))

    def test_a_wildly_wrong_frame_is_refused_not_shifted(self) -> None:
        """Beyond tool noise this is a different colour, not a drifted one, and
        hiding it under an offset would pass off a defect as a correction."""
        corrected, record = normalize_palette.normalize(
            output_frame(90), source_frame(), self.materials()
        )
        self.assertIsNone(corrected)
        self.assertEqual(record["status"], "repair-needed")
        self.assertIn("not\n                        merely drifted".replace("\n                        ", " "), record["error"])

    def test_normalizing_a_flickering_sequence_clears_the_gate(self) -> None:
        manifest, frames = build(self.root, [0, 14, 0, 14, 0, 14], [0, -14, 0, -14, 0, -14])
        before = self.root / "before.json"
        self.assertEqual(run(GATE, str(manifest), str(frames), str(before)).returncode, 2)

        fixed = self.root / "fixed"
        self.assertEqual(
            run(NORMALIZE, str(manifest), str(frames), str(fixed)).returncode, 0
        )
        after = self.root / "after.json"
        self.assertEqual(run(GATE, str(manifest), str(fixed), str(after)).returncode, 0)
        self.assertLess(json.loads(after.read_text())["maxStep"], 2.0)


if __name__ == "__main__":
    unittest.main()


class LockSourceInteriorTests(unittest.TestCase):
    """The tool decides transparency; the source decides what the pixels look
    like. Line boil is the tool redrawing, so the cure is not to use its
    drawing where the source has one."""

    def test_the_interior_becomes_the_source_exactly(self) -> None:
        import lock_source_interior

        source = source_frame()
        locked, record = lock_source_interior.lock(output_frame(20), source)
        self.assertEqual(record["status"], "accepted")
        region = lock_source_interior.locked_region(output_frame(20), source)
        self.assertTrue(region.any())
        self.assertTrue(
            np.array_equal(locked[:, :, :3][region], source[:, :, :3][region])
        )

    def test_alpha_is_the_tools_and_is_never_touched(self) -> None:
        import lock_source_interior

        original = output_frame(20)
        locked, _ = lock_source_interior.lock(original, source_frame())
        self.assertTrue(np.array_equal(locked[:, :, 3], original[:, :, 3]))

    def test_green_pixels_are_never_copied_in(self) -> None:
        """The source's own anti-aliased boundary is blended with the screen.
        Copying it where the tool says opaque paints the spill back on."""
        import lock_source_interior
        from source_foreground import green_excess

        source = source_frame()
        region = lock_source_interior.locked_region(output_frame(), source)
        self.assertTrue(region.any())
        self.assertLess(int(green_excess(source)[region].max()), 0)

    def test_two_frames_drawn_differently_become_identical_inside(self) -> None:
        """The whole point: whatever the tool did to the linework, the interior
        of neighbouring frames now comes from one unchanging source."""
        import lock_source_interior

        source = source_frame()
        first, _ = lock_source_interior.lock(output_frame(14), source)
        second, _ = lock_source_interior.lock(output_frame(-14), source)
        region = lock_source_interior.locked_region(output_frame(), source)
        self.assertTrue(
            np.array_equal(first[:, :, :3][region], second[:, :, :3][region])
        )
