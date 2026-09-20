#!/usr/bin/env python3
"""Tests for gating one attempt as it lands."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


SCRIPT = Path(__file__).with_name("check_frame_attempt.py")
CANVAS = 96
FRAME_COUNT = 5


def sprite(left: float) -> np.ndarray:
    """A sprite whose horizontal position is the only thing that changes."""
    image = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
    start = int(round(left))
    image[20:76, start : start + 40] = (90, 140, 190, 255)
    image[20:24, start : start + 40] = (30, 40, 60, 255)
    image[34:42, start + 10 : start + 18] = (240, 220, 180, 255)
    return image


def save(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array, "RGBA").save(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AttemptCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.run = Path(self._directory.name) / "run"
        self.natives = self.run / "natives"
        # Each frame's authority sits two pixels right of the one before.
        for frame in range(1, FRAME_COUNT + 1):
            save(self.natives / f"frame-{frame:03d}.png", sprite(10 + 2 * frame))
            job = self.run / "jobs" / f"{frame:03d}" / "job.json"
            job.parent.mkdir(parents=True, exist_ok=True)
            job.write_text(
                json.dumps(
                    {
                        "outputFrame": frame,
                        "outputFile": f"frame-{frame:03d}.png",
                        "nativeFrame": 150 + frame,
                        "editTarget": "source",
                        "authority": str(self.natives / f"frame-{frame:03d}.png"),
                        "sourceFile": str(self.natives / f"frame-{frame:03d}.png"),
                        "sourceSha256": sha256(self.natives / f"frame-{frame:03d}.png"),
                    }
                )
            )

    def tearDown(self) -> None:
        self._directory.cleanup()

    def place(self, frame: int, image: np.ndarray, attempt: int = 1) -> Path:
        directory = self.run / "jobs" / f"{frame:03d}" / f"attempt-{attempt:03d}"
        save(directory / "locked.png", image)
        shutil.copyfile(directory / "locked.png", directory / "raw.png")
        (directory / "record.json").write_text(
            json.dumps(
                {
                    "outputFrame": frame,
                    "attempt": attempt,
                    "status": "accepted",
                    "errorClass": "none",
                    "itemId": f"exec-{frame:03d}",
                    "outputSha256": sha256(directory / "raw.png"),
                }
            )
        )
        return directory

    def select(self, frame: int, attempt: int = 1) -> None:
        directory = self.run / "jobs" / f"{frame:03d}" / f"attempt-{attempt:03d}"
        (self.run / "jobs" / f"{frame:03d}" / "selected.json").write_text(
            json.dumps(
                {
                    "outputFrame": frame,
                    "attempt": attempt,
                    "source": str(directory / "locked.png"),
                }
            )
        )

    def check(self, frame: int, attempt: int = 1, *extra: str) -> dict:
        subprocess.run(
            [sys.executable, str(SCRIPT), str(self.run), str(frame), str(attempt), *extra],
            capture_output=True,
            text=True,
        )
        path = (
            self.run / "jobs" / f"{frame:03d}" / f"attempt-{attempt:03d}" / "check-attempt.json"
        )
        return json.loads(path.read_text())

    def test_a_faithful_repair_is_accepted(self) -> None:
        self.place(3, sprite(16))
        self.assertEqual(self.check(3)["status"], "accepted", self.check(3)["errors"])

    def test_a_recoloured_frame_is_caught(self) -> None:
        """A clean cut-out in the wrong colour. Silhouette, drift, identity and
        every temporal gate pass; only the comparison with the source's own
        interior colour sees it."""
        tinted = sprite(16)
        opaque = tinted[:, :, 3] > 250
        tinted[:, :, 2][opaque] = np.clip(
            tinted[:, :, 2][opaque].astype(int) + 40, 0, 255
        ).astype(np.uint8)
        self.place(3, tinted)
        report = self.check(3)
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(
            any("recoloured" in e for e in report["errors"]), report["errors"]
        )

    def test_redrawn_linework_is_caught(self) -> None:
        """The outline thickened. Colour bias stays near zero because the fill
        is untouched, so the dark-pixel fraction is what notices."""
        inked = sprite(16)
        inked[20:32, 16:56] = (30, 40, 60, 255)
        self.place(3, inked)
        report = self.check(3)
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(
            any("linework" in e for e in report["errors"]), report["errors"]
        )

    def test_a_faithful_frame_reports_its_appearance_measurements(self) -> None:
        self.place(3, sprite(16))
        report = self.check(3)
        self.assertLess(report["interiorRgbMeanAbsoluteError"], 1.0)
        self.assertEqual(len(report["interiorChannelBias"]), 3)
        self.assertEqual(len(report["darkOutlineFraction"]), 2)

    def test_the_wrong_frame_is_caught_even_though_it_is_a_valid_sprite(self) -> None:
        """Frame 3's job filled with frame 4's image. Every per-frame limit
        passes -- it is a clean sprite two pixels along -- so only the
        comparison against its neighbours' authorities can see it."""
        self.place(3, sprite(18))
        report = self.check(3)
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(any("wrong frame" in e for e in report["errors"]))

    def test_drift_beyond_the_radius_is_rejected(self) -> None:
        self.place(3, sprite(16.0 + 1.0))
        report = self.check(3, 1, "--drift-radius", "0.35")
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(any("approved target" in e for e in report["errors"]))

    def test_drift_is_measured_against_the_approved_target(self) -> None:
        """A constant offset shared by every frame is placement, not jitter, so
        an approved target absolves it while the same drift without one fails."""
        self.place(3, sprite(17))
        without = self.check(3, 1, "--drift-radius", "0.35")
        self.assertEqual(without["status"], "repair-needed")
        self.assertTrue(any("approved target" in e for e in without["errors"]))
        with_target = self.check(3, 1, "--drift-radius", "0.35", "--drift-target", "1.0", "0")
        self.assertEqual(with_target["status"], "accepted", with_target["errors"])

    def test_a_frame_drifted_halfway_is_a_drift_failure_not_an_identity_one(self) -> None:
        """Sitting midway between two authorities ties on identity. That is
        drift, and only the drift gate should speak."""
        self.place(3, sprite(17))
        report = self.check(3, 1, "--drift-radius", "0.35")
        self.assertFalse(any("wrong frame" in e for e in report["errors"]))
        self.assertTrue(any("approved target" in e for e in report["errors"]))

    def test_a_tampered_record_is_caught(self) -> None:
        directory = self.place(3, sprite(16))
        record = json.loads((directory / "record.json").read_text())
        record["outputSha256"] = "0" * 64
        (directory / "record.json").write_text(json.dumps(record))
        report = self.check(3)
        self.assertTrue(any("SHA-256 its record claims" in e for e in report["errors"]))

    def test_success_without_an_item_id_is_not_trusted(self) -> None:
        directory = self.place(3, sprite(16))
        record = json.loads((directory / "record.json").read_text())
        del record["itemId"]
        (directory / "record.json").write_text(json.dumps(record))
        report = self.check(3)
        self.assertTrue(any("names no image item id" in e for e in report["errors"]))

    def test_only_landed_neighbours_are_compared(self) -> None:
        self.place(2, sprite(14))
        self.select(2)
        self.place(3, sprite(16))
        report = self.check(3)
        self.assertEqual(report["neighboursCompared"], [2])
        self.assertEqual(report["status"], "accepted")

    def test_a_frame_that_has_not_landed_is_simply_absent(self) -> None:
        self.place(3, sprite(16))
        report = self.check(3)
        self.assertEqual(report["neighboursCompared"], [])
        self.assertEqual(report["neighbourFailures"], [])

    def test_a_neighbour_jump_is_caught_as_it_lands(self) -> None:
        self.place(2, sprite(14))
        self.select(2)
        # Frame 3 lands far from frame 2: a step gate failure, visible now
        # rather than after the whole batch has been generated.
        self.place(3, sprite(24))
        report = self.check(3)
        self.assertEqual(report["status"], "repair-needed")
        self.assertTrue(report["neighbourFailures"])


if __name__ == "__main__":
    unittest.main()
