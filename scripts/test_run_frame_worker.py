#!/usr/bin/env python3
"""Tests for reconstructing a worker attempt from the host event stream."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from run_frame_worker import (
    MODERATION,
    TOOL_ERROR,
    USAGE_LIMIT,
    WORKER_DIED,
    build_brief,
    classify,
    parse_events,
    resets_at,
)


USAGE_MESSAGE = (
    "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
    "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try "
    "again at 6:20 PM."
)

MODERATION_MESSAGE = (
    'image generation failed: http 400 Bad Request: Some("{\\n  \\"error\\": {\\n    '
    '\\"message\\": \\"Your request was rejected by the safety system...\\",\\n    '
    '\\"code\\": \\"moderation_blocked\\",\\n    \\"moderation_details\\": {\\n      '
    '\\"moderation_stage\\": \\"output\\"}}}")'
)


def stream(*events: dict) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for event in events:
        handle.write(json.dumps(event) + "\n")
    handle.close()
    return Path(handle.name)


class ParseEventTests(unittest.TestCase):
    def test_thread_id_is_captured_for_image_lookup(self) -> None:
        found = parse_events(
            stream({"type": "thread.started", "thread_id": "01a0be3d-e1de-74d2"})
        )
        self.assertEqual(found["threadId"], "01a0be3d-e1de-74d2")

    def test_image_item_id_is_recovered_from_any_event_shape(self) -> None:
        found = parse_events(
            stream(
                {"type": "thread.started", "thread_id": "abc"},
                {
                    "type": "item.completed",
                    "item": {
                        "kind": "image_gen.generation",
                        "id": "exec-53ece2d6-9062-44b9-aef0-18bdfd6172e5",
                    },
                },
                {"type": "turn.completed"},
            )
        )
        self.assertEqual(
            found["itemIds"], ["exec-53ece2d6-9062-44b9-aef0-18bdfd6172e5"]
        )
        self.assertTrue(found["completed"])

    def test_a_truncated_stream_is_not_a_completed_turn(self) -> None:
        found = parse_events(
            stream({"type": "thread.started", "thread_id": "abc"}, {"type": "turn.started"})
        )
        self.assertFalse(found["completed"])

    def test_unparseable_lines_are_skipped(self) -> None:
        path = stream({"type": "thread.started", "thread_id": "abc"})
        with path.open("a") as handle:
            handle.write("not json at all\n")
        self.assertEqual(parse_events(path)["threadId"], "abc")


class ClassifyTests(unittest.TestCase):
    def test_usage_limit_is_recognised_and_spends_no_budget(self) -> None:
        found = parse_events(
            stream(
                {"type": "thread.started", "thread_id": "abc"},
                {"type": "error", "message": USAGE_MESSAGE},
                {"type": "turn.failed", "error": {"message": USAGE_MESSAGE}},
            )
        )
        error_class, _ = classify(found, "", "")
        self.assertEqual(error_class, USAGE_LIMIT)

    def test_output_stage_moderation_is_recognised(self) -> None:
        found = parse_events(
            stream(
                {"type": "thread.started", "thread_id": "abc"},
                {"type": "error", "message": MODERATION_MESSAGE},
                {"type": "turn.failed", "error": {"message": MODERATION_MESSAGE}},
            )
        )
        error_class, text = classify(found, "", "")
        self.assertEqual(error_class, MODERATION)
        self.assertIn("moderation_blocked", text)

    def test_a_turn_that_simply_stops_is_a_dead_worker(self) -> None:
        """A usage limit kills the turn with no final message, which is how the
        2026-09-20 run ended. That must not read as a frame-quality failure."""
        found = parse_events(
            stream({"type": "thread.started", "thread_id": "abc"}, {"type": "turn.started"})
        )
        error_class, _ = classify(found, "", "")
        self.assertEqual(error_class, WORKER_DIED)

    def test_other_failures_stay_tool_errors(self) -> None:
        found = parse_events(
            stream(
                {"type": "thread.started", "thread_id": "abc"},
                {"type": "turn.failed", "error": {"message": "connection reset"}},
            )
        )
        self.assertEqual(classify(found, "", "")[0], TOOL_ERROR)


class ResetTimeTests(unittest.TestCase):
    def test_reset_time_is_parsed_so_the_queue_can_wait(self) -> None:
        stamp = resets_at(USAGE_MESSAGE)
        self.assertIsNotNone(stamp)
        self.assertEqual(time.localtime(stamp).tm_hour, 18)
        self.assertEqual(time.localtime(stamp).tm_min, 20)

    def test_a_time_already_past_moves_to_tomorrow(self) -> None:
        stamp = resets_at("try again at 00:01")
        self.assertGreater(stamp, time.time())

    def test_a_message_without_a_time_yields_nothing(self) -> None:
        self.assertIsNone(resets_at("You've hit your usage limit."))


class BriefTests(unittest.TestCase):
    TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "worker-brief.md"

    def test_the_brief_sends_one_image_only(self) -> None:
        """No second lineage means no second image, and no chance of sending
        the wrong one as the edit target."""
        brief = build_brief(
            {
                "outputFrame": 24,
                "nativeFrame": 177,
                "authority": "/run/source/frame-024.png",
                "sourceFile": "/run/source/frame-024.png",
            },
            "EXTRACTION PROMPT",
            self.TEMPLATE.read_text(),
        )
        self.assertIn("Image 1: /run/source/frame-024.png", brief)
        self.assertNotIn("Image 2:", brief)
        self.assertIn("EXTRACTION PROMPT", brief)
        self.assertIn("output frame 24", brief)

    def test_standard_extraction_passes_only_the_source(self) -> None:
        brief = build_brief(
            {
                "outputFrame": 3,
                "nativeFrame": 156,
                "authority": "/run/source/frame-003.png",
                "sourceFile": "/run/source/frame-003.png",
                "editTarget": "source",
            },
            "EXTRACT PROMPT",
            self.TEMPLATE.read_text(),
        )
        self.assertIn("Image 1: /run/source/frame-003.png", brief)
        self.assertNotIn("Image 2:", brief)

    def test_the_brief_forbids_the_worker_judging_its_own_output(self) -> None:
        text = self.TEMPLATE.read_text()
        for rule in ("Do not judge the result", "Do not retry", "Never request"):
            self.assertIn(rule, text)


if __name__ == "__main__":
    unittest.main()
