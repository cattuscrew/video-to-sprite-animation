#!/usr/bin/env python3
"""Regression tests for independent frame construction and tool choice."""

from __future__ import annotations

import unittest

from delivery_policy import authority_policy_errors


def source_authority(tool: str) -> dict[str, object]:
    is_gpt = tool == "GPT Image"
    return {
        "frameConstruction": "one-to-one-source",
        "backgroundRemovalTool": tool,
        "processingMode": "gpt-image-per-frame-edit" if is_gpt else "rembg-extraction",
        "pixelAuthority": (
            "gpt-edited-selected-source-frame" if is_gpt else "native-source-rgb"
        ),
        "poseAuthority": "selected-native-source-frame",
        "mappingRole": "selected-source-frame-authority",
        "nativeSource": "/tmp/source.mp4",
        "sourceFrameManifest": "/tmp/source-frame-manifest.json",
        "backgroundRemovalToolApproved": True,
        "userApproved": True,
        "derivedFromRejectedOutput": False,
        "approvalScope": {
            "geometryPreserved": True,
            "foregroundRgbPreserved": not is_gpt,
            "perFrameGptEditApproved": is_gpt,
            "sourcePixelChangesAccepted": is_gpt,
        },
    }


class ToolChoiceGateTests(unittest.TestCase):
    def test_rembg_and_gpt_both_support_one_to_one_mapping(self) -> None:
        self.assertEqual(authority_policy_errors(source_authority("rembg")), [])
        self.assertEqual(authority_policy_errors(source_authority("GPT Image")), [])

    def test_tool_choice_remains_mandatory(self) -> None:
        value = source_authority("rembg")
        value.pop("backgroundRemovalTool")
        self.assertTrue(authority_policy_errors(value))

    def test_gpt_cannot_silently_use_regeneration_mode(self) -> None:
        value = source_authority("GPT Image")
        value["processingMode"] = "gpt-image-regeneration"
        self.assertTrue(any("incompatible" in e for e in authority_policy_errors(value)))


if __name__ == "__main__":
    unittest.main()
