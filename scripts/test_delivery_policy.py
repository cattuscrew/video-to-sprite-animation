#!/usr/bin/env python3
"""Regression tests for selected-source-frame lineage."""

from __future__ import annotations

import unittest

from delivery_policy import (
    authority_policy_errors,
    delivery_mapping_errors,
    delivery_report_errors,
    mapping_manifest_errors,
    parent_frame_manifest_errors,
    visual_qa_report_errors,
)


def authority(tool: str = "GPT Image") -> dict[str, object]:
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
        "masterWarped": False,
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
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "sourceFps": 24.0,
        "outputFps": 24.0,
        "frameCount": 2,
        "frameMapping": records,
    }


def alpha_authority() -> dict[str, object]:
    value = authority()
    value.update(
        {
            "processingMode": "gpt-image-alpha-repair",
            "pixelAuthority": "approved-parent-frame-foreground",
            "parentFrameManifest": "/tmp/parent-frame-manifest.json",
            "parentFramesDirectory": "/tmp/parent-frames",
        }
    )
    value["approvalScope"]["parentFrameRepairApproved"] = True
    return value


def parent_mapping() -> dict[str, object]:
    return {
        "processingMode": "gpt-image-alpha-repair",
        "backgroundRemovalTool": "GPT Image",
        "imageExecutionInterface": "built-in-image-tool",
        "credentialMode": "none",
        "frameCount": 2,
        "frameMapping": [
            {
                "outputFrame": index,
                "nativeFrame": source["nativeFrame"],
                "sourceSha256": source["sourceSha256"],
                "parentFile": f"frame-{index:03d}.png",
                "parentSha256": "b" * 64,
                "parentRole": "approved-foreground-edit-target",
                "classification": "source-frame-gpt-alpha-repair",
                "geometryChanged": False,
            }
            for index, source in enumerate(mapping()["frameMapping"], start=1)
        ],
    }


class DeliveryPolicyTests(unittest.TestCase):
    def test_rembg_one_to_one_is_rejected(self) -> None:
        self.assertTrue(authority_policy_errors(authority("rembg")))
        self.assertTrue(mapping_manifest_errors(mapping("rembg")))

    def test_gpt_one_to_one_passes(self) -> None:
        self.assertEqual(authority_policy_errors(authority()), [])
        self.assertEqual(mapping_manifest_errors(mapping()), [])

    def test_gpt_alpha_repair_requires_parent_lineage(self) -> None:
        value = alpha_authority()
        self.assertEqual(authority_policy_errors(value), [])
        value.pop("parentFrameManifest")
        self.assertTrue(
            any("parentFrameManifest" in e for e in authority_policy_errors(value))
        )

    def test_parent_manifest_binds_same_native_sources(self) -> None:
        self.assertEqual(parent_frame_manifest_errors(parent_mapping(), mapping()), [])
        value = parent_mapping()
        value["frameMapping"][1]["nativeFrame"] = 999
        self.assertTrue(
            any("nativeFrame differs" in e for e in parent_frame_manifest_errors(value, mapping()))
        )

    def test_gpt_one_to_one_rejects_master_warp(self) -> None:
        value = authority()
        value["masterWarped"] = True
        self.assertTrue(any("master warping" in e for e in authority_policy_errors(value)))

    def test_gpt_batch_requires_approved_color_reference(self) -> None:
        value = authority()
        value.pop("canonicalColorReference")
        value["approvalScope"]["canonicalColorReferenceApproved"] = False
        errors = authority_policy_errors(value)
        self.assertTrue(any("canonicalColorReference" in error for error in errors))
        self.assertTrue(any("not explicitly approved" in error for error in errors))

    def test_gpt_batch_requires_color_strategy_and_batch_approval(self) -> None:
        value = authority()
        value.pop("colorConsistencyStrategy")
        value["approvalScope"]["colorConsistencyStrategyApproved"] = False
        value["approvalScope"]["batchExecutionApproved"] = False
        errors = authority_policy_errors(value)
        self.assertTrue(any("color-consistency strategy" in error for error in errors))
        self.assertTrue(any("batch execution" in error for error in errors))

    def test_non_gpt_background_tool_is_rejected(self) -> None:
        value = authority()
        value["backgroundRemovalTool"] = "chroma-key"
        self.assertTrue(authority_policy_errors(value))

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
            "imageExecutionInterface": "built-in-image-tool",
            "credentialMode": "none",
            "processingClassification": "source-frame-gpt-edit",
            "selectedSourceFramesOneBased": [154, 155],
            "sourceCorrespondenceStatus": "accepted",
        }
        self.assertEqual(delivery_report_errors(report, authority()), [])
        self.assertEqual(delivery_mapping_errors(report, mapping()), [])
        report["selectedSourceFramesOneBased"] = [154, 156]
        self.assertTrue(delivery_mapping_errors(report, mapping()))

    def test_alpha_repair_delivery_is_truthfully_classified(self) -> None:
        report = {
            "frameConstruction": "one-to-one-source",
            "processingMode": "gpt-image-alpha-repair",
            "backgroundRemovalTool": "GPT Image",
            "imageExecutionInterface": "built-in-image-tool",
            "credentialMode": "none",
            "processingClassification": "source-frame-gpt-alpha-repair",
            "selectedSourceFramesOneBased": [154, 155],
            "sourceCorrespondenceStatus": "accepted",
        }
        self.assertEqual(delivery_report_errors(report, alpha_authority()), [])

    def test_delivery_requires_complete_visual_temporal_review(self) -> None:
        report = {
            "status": "accepted",
            "normalSpeedReviewed": True,
            "slowSpeedReviewed": True,
            "tripletsReviewed": True,
            "onionSkinReviewed": True,
            "sourceOutputPairsReviewed": True,
            "sourceMotionCompared": True,
            "topologyAndLandmarksReviewed": True,
            "reviewer": "agent",
            "artifacts": {
                "exactFpsPreview": "/tmp/normal.mp4",
                "slowPreview": "/tmp/slow.mp4",
                "triplets": "/tmp/triplets",
                "onionSkin": "/tmp/onion.png",
                "sourceMotionComparison": "/tmp/source-motion.png",
            },
        }
        self.assertEqual(visual_qa_report_errors(report), [])
        report["onionSkinReviewed"] = False
        self.assertTrue(any("onionSkinReviewed" in error for error in visual_qa_report_errors(report)))


if __name__ == "__main__":
    unittest.main()
