#!/usr/bin/env python3
"""Tests for reconstructing a worker attempt from the host event stream."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from run_frame_worker import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    FAST_TIER,
    MODERATION,
    STANDARD_TIER,
    TOOL_ERROR,
    USAGE_LIMIT,
    WORKER_DIED,
    build_brief,
    build_command,
    validate_settings,
    choose_prompt,
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

    def test_an_epoch_in_the_429_body_is_understood(self) -> None:
        """The real form. Prose parsing alone left 13 of 15 usage-limit records
        with no reset time, so the queue knew it was paused but not until when."""
        body = (
            'image generation failed: http 429 Too Many Requests: '
            '{"error":{"type":"usage_limit_reached","resets_at":1758410460}}'
        )
        self.assertEqual(resets_at(body), 1758410460.0)

    def test_an_epoch_in_milliseconds_is_understood(self) -> None:
        self.assertEqual(resets_at('"resets_at": 1758410460000'), 1758410460.0)

    def test_a_message_without_a_time_yields_nothing(self) -> None:
        self.assertIsNone(resets_at("You've hit your usage limit."))


class BriefTests(unittest.TestCase):
    TEMPLATE = Path(__file__).resolve().parent.parent / "references" / "worker-brief.md"

    def test_an_approved_colour_reference_is_sent_as_image_two(self) -> None:
        """A reference recorded in the manifest but never sent guides nothing:
        that is how a batch drifted in colour with every gate passing."""
        brief = build_brief(
            {
                "outputFrame": 24,
                "nativeFrame": 177,
                "authority": "/run/source/frame-024.png",
                "colorReference": "/run/source/frame-001.png",
            },
            "EXTRACTION PROMPT",
            self.TEMPLATE.read_text(),
        )
        self.assertIn("Image 1: /run/source/frame-024.png", brief)
        self.assertIn("Image 2: /run/source/frame-001.png", brief)
        self.assertIn("appearance", brief.lower())
        self.assertIn("not a pose", brief)

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
        self.assertNotIn("colour reference", brief)
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
        self.assertNotIn("colour reference", brief)

    def test_the_brief_forbids_the_worker_judging_its_own_output(self) -> None:
        text = self.TEMPLATE.read_text()
        for rule in ("Do not judge the result", "Do not retry", "Never request"):
            self.assertIn(rule, text)


class CommandTests(unittest.TestCase):
    """The model settings are pinned, not inherited from config.toml."""

    def command(self, **kwargs) -> list[str]:
        defaults = {
            "codex": "codex",
            "run": Path("/tmp/run"),
            "brief": "brief",
            "model": DEFAULT_MODEL,
            "effort": DEFAULT_EFFORT,
            "tier": STANDARD_TIER,
        }
        return build_command(**{**defaults, **kwargs})

    def test_model_and_effort_are_passed_rather_than_inherited(self) -> None:
        command = self.command()
        self.assertEqual(command[command.index("-m") + 1], DEFAULT_MODEL)
        self.assertIn(f'model_reasoning_effort="{DEFAULT_EFFORT}"', command)

    def test_standard_and_fast_select_their_service_tiers(self) -> None:
        self.assertIn(f'service_tier="{STANDARD_TIER}"', self.command())
        self.assertIn(f'service_tier="{FAST_TIER}"', self.command(tier=FAST_TIER))

    def test_the_brief_stays_last_and_the_sandbox_stays_read_only(self) -> None:
        command = self.command(brief="the brief")
        self.assertEqual(command[-1], "the brief")
        self.assertEqual(command[command.index("-s") + 1], "read-only")


class SettingValidationTests(unittest.TestCase):
    """A typo must stop the run, not quietly change what generated it."""

    def catalog(self) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(
            {
                "models": [
                    {
                        "slug": DEFAULT_MODEL,
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                        ],
                        "service_tiers": [{"id": FAST_TIER}],
                    },
                    {"slug": "gpt-no-fast", "service_tiers": []},
                ]
            },
            handle,
        )
        handle.close()
        return Path(handle.name)

    def test_approved_settings_pass(self) -> None:
        self.assertEqual(
            validate_settings(DEFAULT_MODEL, DEFAULT_EFFORT, False, self.catalog()), []
        )

    def test_an_unknown_model_is_named(self) -> None:
        problems = validate_settings("gpt-5.6-sool", DEFAULT_EFFORT, False, self.catalog())
        self.assertIn("unknown model", problems[0])

    def test_an_effort_the_model_lacks_is_rejected(self) -> None:
        problems = validate_settings(DEFAULT_MODEL, "turbo", False, self.catalog())
        self.assertIn("reasoning effort", problems[0])

    def test_fast_is_rejected_where_the_tier_does_not_exist(self) -> None:
        problems = validate_settings("gpt-no-fast", DEFAULT_EFFORT, True, self.catalog())
        self.assertIn("Fast mode is unavailable", problems[0])

    def test_a_missing_catalog_blocks_nothing(self) -> None:
        """It is a cache. An absent one must not stop a run from starting."""
        self.assertEqual(
            validate_settings("anything", "anything", True, Path("/nonexistent.json")), []
        )


if __name__ == "__main__":
    unittest.main()


class ChoosePromptTests(unittest.TestCase):
    def test_short_prompt_is_used_from_the_first_attempt(self) -> None:
        """It is the better prompt, not a moderation rescue, so nothing is
        gained by spending the long prompt's worse odds on attempt one."""
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "prompt.txt").write_text("long")
            (run / "prompt-short.txt").write_text("short")
            self.assertEqual(choose_prompt(run).name, "prompt-short.txt")

    def test_long_prompt_is_used_when_no_short_one_was_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "prompt.txt").write_text("long")
            self.assertEqual(choose_prompt(run).name, "prompt.txt")
