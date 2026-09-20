#!/usr/bin/env python3
"""Tests for the per-frame job queue, its two budgets and its ledger."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import frame_jobs


SCRIPT = Path(__file__).with_name("frame_jobs.py")
FRAME_COUNT = 4


def write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16), (80, 120, 160, 255)).save(path)


def manifest(root: Path) -> Path:
    natives = root / "natives"
    for index in range(1, FRAME_COUNT + 1):
        write_png(natives / f"frame-{index:03d}.png")
    mapping = [
        {
            "outputFrame": index,
            "outputFile": f"frame-{index:03d}.png",
            "nativeFrame": 150 + index,
            "sourceFile": f"frame-{index:03d}.png",
            "sourceSha256": "0" * 64,
            }
        for index in range(1, FRAME_COUNT + 1)
    ]
    path = root / "source-frame-manifest.json"
    path.write_text(
        json.dumps(
            {
                "sourceFramesDirectory": str(natives),
                "frameCount": FRAME_COUNT,
                "frameMapping": mapping,
            }
        )
    )
    return path


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments], text=True, capture_output=True
    )


def record_attempt(
    run: Path, frame: int, attempt: int, *, error_class: str | None = None, **extra
) -> Path:
    directory = run / "jobs" / f"{frame:03d}" / f"attempt-{attempt:03d}"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"outputFrame": frame, "attempt": attempt, **extra}
    if error_class:
        payload["errorClass"] = error_class
        payload["status"] = "repair-needed"
    else:
        payload["status"] = "accepted"
    (directory / "record.json").write_text(json.dumps(payload))
    return directory


class InitTests(unittest.TestCase):
    def test_one_job_per_mapped_frame_with_its_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            run_cli("init", str(run), str(manifest(root)))
            jobs = sorted((run / "jobs").glob("*/job.json"))
            self.assertEqual(len(jobs), FRAME_COUNT)
            third = json.loads((run / "jobs" / "003" / "job.json").read_text())
            self.assertEqual(third["outputFrame"], 3)
            self.assertEqual(third["nativeFrame"], 153)
            self.assertEqual(third["editTarget"], "source")
            self.assertTrue(third["authority"].endswith("natives/frame-003.png"))
            self.assertEqual(third["authority"], third["sourceFile"])

    def test_existing_jobs_are_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            path = manifest(root)
            run_cli("init", str(run), str(path))
            marked = run / "jobs" / "001" / "job.json"
            payload = json.loads(marked.read_text())
            payload["marker"] = "kept"
            marked.write_text(json.dumps(payload))
            run_cli("init", str(run), str(path))
            self.assertEqual(json.loads(marked.read_text()).get("marker"), "kept")


class BudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.run = self.root / "run"
        run_cli("init", str(self.run), str(manifest(self.root)))

    def tearDown(self) -> None:
        self._directory.cleanup()

    def ready_frames(self) -> list[int]:
        result = run_cli("next", str(self.run))
        return [item["outputFrame"] for item in json.loads(result.stdout)["ready"]]

    def test_every_frame_starts_ready(self) -> None:
        self.assertEqual(self.ready_frames(), [1, 2, 3, 4])

    def test_budgets_are_counted_separately(self) -> None:
        safety = frame_jobs.DEFAULT_BUDGETS["safetyBlock"]
        geometry = frame_jobs.DEFAULT_BUDGETS["qualityGeometry"]
        for attempt in range(1, safety + 1):
            record_attempt(self.run, 1, attempt, error_class=frame_jobs.MODERATION)
        for attempt in range(1, geometry + 1):
            record_attempt(
                self.run,
                2,
                attempt,
                error_class=frame_jobs.QUALITY,
                qualityKinds=[frame_jobs.GEOMETRY],
            )
        ready = self.ready_frames()
        self.assertNotIn(1, ready, "spending the safety budget should exhaust it")
        self.assertNotIn(2, ready, "spending the geometry budget should exhaust it")
        self.assertIn(3, ready)

    def test_warping_and_repainting_draw_on_different_budgets(self) -> None:
        """The two quality failures are unrelated, so a frame that keeps
        warping must not use up the budget for a frame that keeps repainting."""
        geometry = frame_jobs.DEFAULT_BUDGETS["qualityGeometry"]
        for attempt in range(1, geometry + 1):
            record_attempt(
                self.run,
                1,
                attempt,
                error_class=frame_jobs.QUALITY,
                qualityKinds=[frame_jobs.GEOMETRY],
            )
        result = json.loads(run_cli("next", str(self.run)).stdout)
        exhausted = next(i for i in result["exhausted"] if i["outputFrame"] == 1)
        self.assertEqual(exhausted["exhausted"], ["qualityGeometry"])
        self.assertEqual(exhausted["spent"]["qualityColour"], 0)

    def test_an_attempt_that_failed_both_ways_charges_both(self) -> None:
        record_attempt(
            self.run,
            1,
            1,
            error_class=frame_jobs.QUALITY,
            qualityKinds=[frame_jobs.COLOUR, frame_jobs.GEOMETRY],
        )
        result = json.loads(run_cli("next", str(self.run)).stdout)
        first = next(i for i in result["ready"] if i["outputFrame"] == 1)
        self.assertEqual(first["spent"]["qualityGeometry"], 1)
        self.assertEqual(first["spent"]["qualityColour"], 1)

    def test_a_record_from_before_the_split_counts_as_geometry(self) -> None:
        """Almost every one of them was, and guessing colour would block a
        resumed run on a budget nothing had actually spent."""
        record_attempt(self.run, 1, 1, error_class=frame_jobs.QUALITY)
        result = json.loads(run_cli("next", str(self.run)).stdout)
        first = next(i for i in result["ready"] if i["outputFrame"] == 1)
        self.assertEqual(first["spent"]["qualityGeometry"], 1)
        self.assertEqual(first["spent"]["qualityColour"], 0)

    def test_safety_blocks_do_not_spend_the_quality_budget(self) -> None:
        for attempt in range(1, 4):
            record_attempt(self.run, 1, attempt, error_class=frame_jobs.MODERATION)
        result = json.loads(run_cli("next", str(self.run)).stdout)
        first = next(i for i in result["ready"] if i["outputFrame"] == 1)
        self.assertEqual(
            first["spent"],
            {"safetyBlock": 3, "qualityGeometry": 0, "qualityColour": 0},
        )

    def test_usage_limit_pauses_without_spending_a_budget(self) -> None:
        import time

        record_attempt(
            self.run,
            1,
            1,
            error_class=frame_jobs.USAGE_LIMIT,
            resetsAt=time.time() + 3600,
        )
        result = json.loads(run_cli("next", str(self.run)).stdout)
        self.assertIn("pausedUntil", result)
        first = next(i for i in result["ready"] if i["outputFrame"] == 1)
        self.assertEqual(
            first["spent"],
            {"safetyBlock": 0, "qualityGeometry": 0, "qualityColour": 0},
        )

    def test_a_worker_that_died_spends_no_budget(self) -> None:
        for attempt in range(1, 6):
            record_attempt(self.run, 1, attempt, error_class=frame_jobs.WORKER_DIED)
        self.assertIn(1, self.ready_frames())

    def test_approved_budgets_override_the_defaults(self) -> None:
        (self.run / "authority-manifest.json").write_text(
            json.dumps({"approvalScope": {"retryBudgets": {"safetyBlock": 1}}})
        )
        record_attempt(self.run, 1, 1, error_class=frame_jobs.MODERATION)
        self.assertNotIn(1, self.ready_frames())

    def test_a_manifest_approved_before_the_split_still_binds_both_kinds(self) -> None:
        """It named one quality budget. Honour it as the limit for each kind
        rather than handing a resumed run the larger new default."""
        (self.run / "authority-manifest.json").write_text(
            json.dumps({"approvalScope": {"retryBudgets": {"quality": 1}}})
        )
        record_attempt(
            self.run,
            1,
            1,
            error_class=frame_jobs.QUALITY,
            qualityKinds=[frame_jobs.COLOUR],
        )
        limits = frame_jobs.budgets(self.run)
        self.assertEqual(limits["qualityColour"], 1)
        self.assertEqual(limits["qualityGeometry"], 1)
        self.assertNotIn("quality", limits)
        self.assertNotIn(1, self.ready_frames())


class WorkerConfigurationTests(unittest.TestCase):
    """A misconfigured driver must not spend retry budgets doing nothing."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.run = self.root / "run"
        run_cli("init", str(self.run), str(manifest(self.root)))

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_no_worker_and_no_staged_image_stops_instead_of_retrying(self) -> None:
        result = run_cli("run", str(self.run), "--worker", "none")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no worker configured", result.stderr + result.stdout)
        attempts = list((self.run / "jobs").glob("*/attempt-*"))
        self.assertEqual(attempts, [], "a misconfiguration must cost no attempts")

    def test_the_worker_defaults_to_the_bundled_one(self) -> None:
        import frame_jobs as module

        parser = module.build_parser()
        args = parser.parse_args(["run", str(self.run)])
        self.assertEqual(Path(args.worker).name, "run_frame_worker.py")

    def test_model_settings_reach_the_worker(self) -> None:
        """Pinned settings are useless if the driver keeps them to itself."""
        fake = self.root / "fake_worker.py"
        fake.write_text(
            "import json, sys, pathlib\n"
            f"pathlib.Path({str(self.root / 'argv.json')!r}).write_text(json.dumps(sys.argv))\n"
            "raise SystemExit(1)\n"
        )
        run_cli("run", str(self.run), "--worker", str(fake), "--fast", "--max-attempts", "1")
        argv = json.loads((self.root / "argv.json").read_text())
        self.assertIn("--fast", argv)
        self.assertEqual(argv[argv.index("--model") + 1], frame_jobs.DEFAULT_MODEL)
        self.assertEqual(
            argv[argv.index("--reasoning-effort") + 1], frame_jobs.DEFAULT_EFFORT
        )

    def test_fast_mode_is_off_unless_asked_for(self) -> None:
        import frame_jobs as module

        args = module.build_parser().parse_args(["run", str(self.run)])
        self.assertFalse(args.fast)
        self.assertEqual(args.model, module.DEFAULT_MODEL)
        self.assertEqual(args.reasoning_effort, module.DEFAULT_EFFORT)


class StatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.run = self.root / "run"
        run_cli("init", str(self.run), str(manifest(self.root)))

    def tearDown(self) -> None:
        self._directory.cleanup()

    def status(self) -> dict:
        run_cli("status", str(self.run))
        return json.loads((self.run / "run-status.json").read_text())

    def test_a_frame_never_produced_stays_a_hole(self) -> None:
        report = self.status()
        self.assertEqual(report["frameCount"], FRAME_COUNT)
        self.assertEqual(report["acceptedFrameCount"], 0)
        self.assertEqual([f["outputFrame"] for f in report["frames"]], [1, 2, 3, 4])

    def test_exhausted_frames_are_blocked_not_silently_dropped(self) -> None:
        for attempt in range(1, frame_jobs.DEFAULT_BUDGETS["safetyBlock"] + 1):
            record_attempt(self.run, 2, attempt, error_class=frame_jobs.MODERATION)
        report = self.status()
        second = next(f for f in report["frames"] if f["outputFrame"] == 2)
        self.assertEqual(second["status"], frame_jobs.BLOCKED)
        self.assertTrue(any("frame 2" in e for e in report["errors"]))

    def test_one_image_cannot_be_claimed_by_two_frames(self) -> None:
        record_attempt(self.run, 1, 1, itemId="exec-abc")
        record_attempt(self.run, 2, 1, itemId="exec-abc")
        report = self.status()
        self.assertTrue(any("exec-abc" in e for e in report["errors"]))

    def test_select_promotes_an_attempt_and_completes_the_run(self) -> None:
        for frame in range(1, FRAME_COUNT + 1):
            directory = record_attempt(self.run, frame, 1, itemId=f"exec-{frame}")
            write_png(directory / "locked.png")
            run_cli("select", str(self.run), str(frame), "1")
        report = self.status()
        self.assertEqual(report["status"], frame_jobs.ACCEPTED)
        self.assertEqual(report["acceptedFrameCount"], FRAME_COUNT)
        for frame in range(1, FRAME_COUNT + 1):
            self.assertTrue((self.run / "frames" / f"frame-{frame:03d}.png").is_file())

    def test_a_failing_frame_does_not_hold_up_the_others(self) -> None:
        """Fewest attempts first: frame 1 spending its budget must not stop
        frames 2-4 from being generated at all."""
        for attempt in range(1, 3):
            record_attempt(self.run, 1, attempt, error_class=frame_jobs.MODERATION)
        result = json.loads(run_cli("next", str(self.run)).stdout)
        self.assertEqual(result["ready"][0]["outputFrame"], 2)
        self.assertEqual(
            [item["outputFrame"] for item in result["ready"]][-1],
            1,
            "the frame with the most attempts should be last in line",
        )

    def test_a_selected_frame_leaves_the_queue(self) -> None:
        directory = record_attempt(self.run, 1, 1)
        write_png(directory / "locked.png")
        run_cli("select", str(self.run), "1", "1")
        ready = json.loads(run_cli("next", str(self.run)).stdout)["ready"]
        self.assertNotIn(1, [item["outputFrame"] for item in ready])


if __name__ == "__main__":
    unittest.main()
