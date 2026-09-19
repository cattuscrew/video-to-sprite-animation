#!/usr/bin/env python3
"""Regression tests for the mandatory rembg/GPT Image choice gate."""

from __future__ import annotations

import copy
import unittest

from build_frame_contract import validate_authority as validate_contract_authority
from validate_and_diagnose import authority_errors


BASE_AUTHORITY = {
    "sourceKind": "native-source-derived",
    "nativeSource": "/tmp/source.mp4",
    "userApproved": True,
    "derivedFromRejectedOutput": False,
    "backgroundRemovalTool": "rembg",
    "backgroundRemovalToolApproved": True,
    "processingMode": "rembg-extraction",
    "sourceFrameManifest": "/tmp/source-frame-manifest.json",
    "approvalScope": {"foregroundRgbPreserved": True},
}


class ToolChoiceGateTests(unittest.TestCase):
    def test_approved_rembg_passes_both_authority_validators(self) -> None:
        authority = copy.deepcopy(BASE_AUTHORITY)
        contract = {
            "authority": authority,
            "backgroundRemovalTool": "rembg",
            "processingMode": "rembg-extraction",
            "perFrameAuthorityDirectory": "/tmp/per-frame-authority",
        }
        self.assertEqual(authority_errors(contract), [])
        validate_contract_authority(authority)

    def test_missing_tool_choice_is_rejected(self) -> None:
        authority = copy.deepcopy(BASE_AUTHORITY)
        authority.pop("backgroundRemovalTool")
        authority.pop("backgroundRemovalToolApproved")
        authority.pop("processingMode")
        errors = authority_errors(
            {
                "authority": authority,
                "backgroundRemovalTool": "rembg",
                "processingMode": "rembg-extraction",
            }
        )
        self.assertTrue(any("backgroundRemovalTool" in error for error in errors))
        with self.assertRaises(ValueError):
            validate_contract_authority(authority)

    def test_gpt_image_requires_its_regenerative_mode(self) -> None:
        authority = copy.deepcopy(BASE_AUTHORITY)
        authority["backgroundRemovalTool"] = "GPT Image"
        errors = authority_errors(
            {
                "authority": authority,
                "backgroundRemovalTool": "GPT Image",
                "processingMode": "rembg-extraction",
            }
        )
        self.assertTrue(any("processingMode" in error for error in errors))
        with self.assertRaises(ValueError):
            validate_contract_authority(authority)

    def test_unapproved_tool_is_rejected(self) -> None:
        authority = copy.deepcopy(BASE_AUTHORITY)
        authority["backgroundRemovalToolApproved"] = False
        errors = authority_errors(
            {
                "authority": authority,
                "backgroundRemovalTool": "rembg",
                "processingMode": "rembg-extraction",
            }
        )
        self.assertTrue(any("not user-approved" in error for error in errors))
        with self.assertRaises(ValueError):
            validate_contract_authority(authority)


if __name__ == "__main__":
    unittest.main()
