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
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "processingMode": "gpt-image-per-frame-edit" if is_gpt else "rembg-extraction",
        "pixelAuthority": (
            "gpt-edited-selected-source-frame" if is_gpt else "native-source-rgb"
        ),
        "poseAuthority": "selected-native-source-frame",
        "mappingRole": "selected-source-frame-authority",
        "nativeSource": "/tmp/source.mp4",
        "sourceFrameManifest": "/tmp/source-frame-manifest.json",
        "userApproved": True,
        "derivedFromRejectedOutput": False,
        "canonicalColorReference": ({
            "path": "/tmp/color-reference.png",
            "sha256": "c" * 64,
            "role": "appearance-only",
        } if is_gpt else None),
        "colorConsistencyStrategy": (
            "reference-guided-gpt-with-deterministic-palette-normalization"
            if is_gpt else None
        ),
        "approvalScope": {
            "geometryPreserved": True,
            "foregroundRgbPreserved": not is_gpt,
            "perFrameGptEditApproved": is_gpt,
            "sourcePixelChangesAccepted": is_gpt,
            "canonicalColorReferenceApproved": is_gpt,
            "colorConsistencyStrategyApproved": is_gpt,
            "batchExecutionApproved": is_gpt,
        },
    }


class ToolChoiceGateTests(unittest.TestCase):
    def test_only_builtin_gpt_supports_one_to_one_mapping(self) -> None:
        self.assertEqual(authority_policy_errors(source_authority("GPT Image")), [])
        self.assertTrue(authority_policy_errors(source_authority("rembg")))

    def test_fixed_tool_remains_mandatory(self) -> None:
        value = source_authority("GPT Image")
        value.pop("backgroundRemovalTool")
        self.assertTrue(authority_policy_errors(value))

    def test_external_image_api_is_rejected(self) -> None:
        value = source_authority("GPT Image")
        value["imageExecutionInterface"] = "external-api"
        self.assertTrue(any("built-in-image-tool" in e for e in authority_policy_errors(value)))

    def test_api_credentials_are_rejected(self) -> None:
        value = source_authority("GPT Image")
        value["credentialMode"] = "api-key"
        self.assertTrue(any("credentials are forbidden" in e for e in authority_policy_errors(value)))

    def test_gpt_cannot_silently_use_regeneration_mode(self) -> None:
        value = source_authority("GPT Image")
        value["processingMode"] = "gpt-image-regeneration"
        self.assertTrue(authority_policy_errors(value))


if __name__ == "__main__":
    unittest.main()
