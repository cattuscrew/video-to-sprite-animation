#!/usr/bin/env python3
"""Regression tests for selected-source-frame lineage."""

from __future__ import annotations

import unittest

from delivery_policy import (
    authority_policy_errors,
    delivery_mapping_errors,
    delivery_report_errors,
    mapping_manifest_errors,
)


def authority(tool: str = "GPT Image") -> dict[str, object]:
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
        "masterWarped": False,
        "approvalScope": {
            "geometryPreserved": True,
            "foregroundRgbPreserved": not is_gpt,
            "perFrameGptEditApproved": is_gpt,
            "sourcePixelChangesAccepted": is_gpt,
        },
    }


def mapping(tool: str = "GPT Image") -> dict[str, object]:
    classification = (
        "source-frame-gpt-edit" if tool == "GPT Image" else "exact-source-extraction"
    )
    records = []
    for output_frame, native_frame in enumerate((154, 155), start=1):
        records.append(
            {
                "outputFrame": output_frame,
                "nativeFrame": native_frame,
                "outputFile": f"frame-{output_frame:03d}.png",
                "classification": classification,
                "sourceFrameRequired": True,
                "sourceSha256": "a" * 64,
                "geometryChanged": False,
                "held": False,
                "interpolated": False,
            }
        )
    return {
        "frameConstruction": "one-to-one-source",
        "mappingRole": "selected-source-frame-authority",
        "processingType": "one-to-one-source-processing",
        "backgroundRemovalTool": tool,
        "sourceFps": 24.0,
        "outputFps": 24.0,
        "frameCount": 2,
        "frameMapping": records,
    }


class DeliveryPolicyTests(unittest.TestCase):
    def test_rembg_one_to_one_passes(self) -> None:
        self.assertEqual(authority_policy_errors(authority("rembg")), [])
        self.assertEqual(mapping_manifest_errors(mapping("rembg")), [])

    def test_gpt_one_to_one_passes(self) -> None:
        self.assertEqual(authority_policy_errors(authority()), [])
        self.assertEqual(mapping_manifest_errors(mapping()), [])

    def test_gpt_one_to_one_rejects_master_warp(self) -> None:
        value = authority()
        value["masterWarped"] = True
        self.assertTrue(any("master warping" in e for e in authority_policy_errors(value)))

    def test_unapproved_background_tool_is_rejected(self) -> None:
        value = authority()
        value["backgroundRemovalToolApproved"] = False
        self.assertTrue(any("not user-approved" in e for e in authority_policy_errors(value)))

    def test_mapping_rejects_skipped_or_reordered_output(self) -> None:
        value = mapping()
        value["frameMapping"][1]["outputFrame"] = 3
        self.assertTrue(any("complete and ordered" in e for e in mapping_manifest_errors(value)))

    def test_mapping_rejects_duplicate_selected_frame(self) -> None:
        value = mapping()
        value["frameMapping"][1]["nativeFrame"] = 154
        self.assertTrue(any("duplicates" in e for e in mapping_manifest_errors(value)))

    def test_mapping_rejects_skipped_native_frame_at_native_fps(self) -> None:
        value = mapping()
        value["frameMapping"][1]["nativeFrame"] = 156
        self.assertTrue(any("skips or reorders" in e for e in mapping_manifest_errors(value)))

    def test_mapping_rejects_hold_or_interpolation(self) -> None:
        value = mapping()
        value["frameMapping"][0]["held"] = True
        self.assertTrue(any("substitutes" in e for e in mapping_manifest_errors(value)))

    def test_delivery_must_report_exact_selected_frame_list(self) -> None:
        report = {
            "frameConstruction": "one-to-one-source",
            "processingMode": "gpt-image-per-frame-edit",
            "backgroundRemovalTool": "GPT Image",
            "processingClassification": "source-frame-gpt-edit",
            "selectedSourceFramesOneBased": [154, 155],
            "sourceCorrespondenceStatus": "accepted",
        }
        self.assertEqual(delivery_report_errors(report, authority()), [])
        self.assertEqual(delivery_mapping_errors(report, mapping()), [])
        report["selectedSourceFramesOneBased"] = [154, 156]
        self.assertTrue(delivery_mapping_errors(report, mapping()))


if __name__ == "__main__":
    unittest.main()
