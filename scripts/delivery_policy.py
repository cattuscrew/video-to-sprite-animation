#!/usr/bin/env python3
"""Shared frame-lineage and background-tool policy checks."""

from __future__ import annotations

from typing import Any


ONE_TO_ONE = "one-to-one-source"
SYNTHESIZED = "synthesized"
SOURCE_MAPPING_ROLE = "selected-source-frame-authority"
MOTION_MAPPING_ROLE = "motion-reference-only"
NON_SOURCE_CLASSIFICATIONS = {
    "source-derived-deformation", "generated", "interpolated", "held/reused"
}


def expected_tool_fields(construction: str, tool: str) -> dict[str, str] | None:
    policies = {
        (ONE_TO_ONE, "rembg"): {
            "processingMode": "rembg-extraction",
            "pixelAuthority": "native-source-rgb",
            "poseAuthority": "selected-native-source-frame",
            "mappingRole": SOURCE_MAPPING_ROLE,
        },
        (ONE_TO_ONE, "GPT Image"): {
            "processingMode": "gpt-image-per-frame-edit",
            "pixelAuthority": "gpt-edited-selected-source-frame",
            "poseAuthority": "selected-native-source-frame",
            "mappingRole": SOURCE_MAPPING_ROLE,
        },
        (SYNTHESIZED, "GPT Image"): {
            "processingMode": "gpt-image-regeneration",
            "pixelAuthority": "approved-gpt-master",
            "poseAuthority": "synthesized-from-motion-reference",
            "mappingRole": MOTION_MAPPING_ROLE,
        },
    }
    return policies.get((construction, tool))


def authority_policy_errors(authority: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    construction = authority.get("frameConstruction")
    tool = authority.get("backgroundRemovalTool")
    if construction not in {ONE_TO_ONE, SYNTHESIZED}:
        return ["authority frameConstruction must be one-to-one-source or synthesized"]
    if tool not in {"rembg", "GPT Image"}:
        return ["authority backgroundRemovalTool must be rembg or GPT Image"]
    expected = expected_tool_fields(str(construction), str(tool))
    if expected is None:
        errors.append(
            f"backgroundRemovalTool={tool!r} cannot construct frames with "
            f"frameConstruction={construction!r}"
        )
    else:
        for field, value in expected.items():
            if authority.get(field) != value:
                errors.append(
                    f"authority {field}={authority.get(field)!r} is incompatible with "
                    f"frameConstruction={construction!r} and tool={tool!r}; "
                    f"expected {value!r}"
                )
    if authority.get("backgroundRemovalToolApproved") is not True:
        errors.append("background-removal tool is not user-approved")
    if authority.get("userApproved") is not True:
        errors.append("authority/proof frame is not user-approved")
    if authority.get("derivedFromRejectedOutput") is not False:
        errors.append("authority may be derived from rejected output")
    approval = authority.get("approvalScope", {})
    if not isinstance(approval, dict):
        approval = {}
    if construction == ONE_TO_ONE:
        if not authority.get("nativeSource"):
            errors.append("one-to-one authority is missing nativeSource")
        if not authority.get("sourceFrameManifest"):
            errors.append("one-to-one authority is missing sourceFrameManifest")
        if authority.get("motionReferenceManifest"):
            errors.append("one-to-one processing must not use motionReferenceManifest")
        if authority.get("masterWarped") is True:
            errors.append("one-to-one processing forbids master warping")
        if approval.get("geometryPreserved") is not True:
            errors.append("one-to-one authority lacks geometryPreserved approval")
        if tool == "rembg" and approval.get("foregroundRgbPreserved") is not True:
            errors.append("rembg authority lacks foregroundRgbPreserved approval")
        if tool == "GPT Image":
            if approval.get("perFrameGptEditApproved") is not True:
                errors.append("per-frame GPT Image editing is not explicitly approved")
            if approval.get("sourcePixelChangesAccepted") is not True:
                errors.append("GPT Image source-pixel changes are not explicitly accepted")
    else:
        if not authority.get("canonicalMaster"):
            errors.append("synthesized authority is missing canonicalMaster")
        if not authority.get("motionReferenceManifest"):
            errors.append("synthesized authority is missing motionReferenceManifest")
        if authority.get("sourceFrameManifest"):
            errors.append("synthesized processing must use motionReferenceManifest")
        if approval.get("synthesizedMotionApproved") is not True:
            errors.append("synthesized motion is not explicitly approved")
    return errors


def mapping_manifest_errors(
    manifest: dict[str, Any], expected_construction: str | None = None
) -> list[str]:
    errors: list[str] = []
    construction = manifest.get("frameConstruction")
    if expected_construction and construction != expected_construction:
        errors.append(
            f"mapping frameConstruction={construction!r} does not match authority "
            f"frameConstruction={expected_construction!r}"
        )
    if construction not in {ONE_TO_ONE, SYNTHESIZED}:
        return errors + [
            "mapping frameConstruction must be one-to-one-source or synthesized"
        ]
    mapping = manifest.get("frameMapping", [])
    if not isinstance(mapping, list) or not mapping:
        return errors + ["mapping manifest has no frameMapping records"]
    if manifest.get("frameCount") != len(mapping):
        errors.append("mapping frameCount does not match frameMapping length")
    if [record.get("outputFrame") for record in mapping] != list(
        range(1, len(mapping) + 1)
    ):
        errors.append("mapping outputFrame values must be complete and ordered")
    native_frames = [record.get("nativeFrame") for record in mapping]
    if not all(isinstance(value, int) for value in native_frames):
        errors.append("mapping nativeFrame values must be integers")
    elif construction == ONE_TO_ONE and len(set(native_frames)) != len(native_frames):
        errors.append("mapping reuses or duplicates a selected native frame")
    elif (
        construction == ONE_TO_ONE
        and manifest.get("sourceFps") == manifest.get("outputFps")
        and native_frames
        and native_frames
        != list(range(native_frames[0], native_frames[0] + len(native_frames)))
    ):
        errors.append("one-to-one native-FPS mapping skips or reorders a source frame")
    tool = manifest.get("backgroundRemovalTool")
    if construction == ONE_TO_ONE:
        if manifest.get("mappingRole") != SOURCE_MAPPING_ROLE:
            errors.append("one-to-one mappingRole must be selected-source-frame-authority")
        if manifest.get("processingType") != "one-to-one-source-processing":
            errors.append("one-to-one processingType is invalid")
        expected_class = (
            "exact-source-extraction" if tool == "rembg" else "source-frame-gpt-edit"
        )
        if tool not in {"rembg", "GPT Image"}:
            errors.append("one-to-one mapping tool must be rembg or GPT Image")
        for index, record in enumerate(mapping, start=1):
            if record.get("outputFile") != f"frame-{index:03d}.png":
                errors.append(f"mapping frame {index} outputFile is incorrect")
            if record.get("classification") != expected_class:
                errors.append(
                    f"mapping frame {index} classification must be {expected_class}"
                )
            if record.get("sourceFrameRequired") is not True:
                errors.append(f"mapping frame {index} does not require its source frame")
            digest = record.get("sourceSha256")
            if not isinstance(digest, str) or len(digest) != 64:
                errors.append(f"mapping frame {index} lacks sourceSha256")
            if any(bool(record.get(field)) for field in ("held", "interpolated")):
                errors.append(f"mapping frame {index} substitutes its selected source frame")
            if record.get("geometryChanged") is not False:
                errors.append(f"mapping frame {index} permits source-pose geometry drift")
    else:
        if manifest.get("mappingRole") != MOTION_MAPPING_ROLE:
            errors.append("synthesized mappingRole must be motion-reference-only")
        if manifest.get("processingType") != "native-motion-reference":
            errors.append("synthesized processingType must be native-motion-reference")
        if tool != "GPT Image":
            errors.append("synthesized mapping backgroundRemovalTool must be GPT Image")
        for index, record in enumerate(mapping, start=1):
            if record.get("classification") not in NON_SOURCE_CLASSIFICATIONS:
                errors.append(f"mapping frame {index} has invalid synthesized classification")
    return errors


def contract_policy_errors(contract: dict[str, Any]) -> list[str]:
    authority = contract.get("authority", {})
    if not isinstance(authority, dict):
        return ["contract authority is missing or invalid"]
    errors = authority_policy_errors(authority)
    for field in (
        "frameConstruction", "processingMode", "backgroundRemovalTool",
        "pixelAuthority", "poseAuthority", "mappingRole",
    ):
        if contract.get(field) != authority.get(field):
            errors.append(f"contract {field} does not match authority")
    construction = authority.get("frameConstruction")
    if construction == ONE_TO_ONE:
        if not contract.get("sourceFrameManifest"):
            errors.append("one-to-one contract is missing sourceFrameManifest")
        if contract.get("motionReferenceManifest"):
            errors.append("one-to-one contract must not use motionReferenceManifest")
        if not contract.get("perFrameAuthorityDirectory"):
            errors.append("one-to-one contract lacks per-frame source authority")
        if contract.get("sourceCorrespondenceRequired") is not True:
            errors.append("one-to-one contract must require source correspondence")
    elif construction == SYNTHESIZED:
        if contract.get("sourceFrameManifest"):
            errors.append("synthesized contract must not use sourceFrameManifest")
        if not contract.get("motionReferenceManifest"):
            errors.append("synthesized contract is missing motionReferenceManifest")
        if contract.get("sourceCorrespondenceRequired") is not False:
            errors.append("synthesized contract must not claim one-to-one correspondence")
    return errors


def delivery_report_errors(report: dict[str, Any], authority: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("frameConstruction", "processingMode", "backgroundRemovalTool"):
        if report.get(field) != authority.get(field):
            errors.append(f"delivery report {field} does not match authority")
    construction = authority.get("frameConstruction")
    tool = authority.get("backgroundRemovalTool")
    classification = report.get("processingClassification")
    if construction == ONE_TO_ONE:
        expected = "exact-source-extraction" if tool == "rembg" else "source-frame-gpt-edit"
        if classification != expected:
            errors.append(f"one-to-one delivery classification must be {expected}")
        if not report.get("selectedSourceFramesOneBased"):
            errors.append("one-to-one delivery is missing selectedSourceFramesOneBased")
        if report.get("motionReferenceFramesOneBased"):
            errors.append("one-to-one delivery must not substitute motion references")
        if report.get("sourceCorrespondenceStatus") != "accepted":
            errors.append("one-to-one delivery lacks accepted source correspondence")
    elif construction == SYNTHESIZED:
        if classification not in NON_SOURCE_CLASSIFICATIONS:
            errors.append("synthesized delivery requires a synthesized classification")
        if report.get("selectedSourceFramesOneBased"):
            errors.append("synthesized delivery falsely claims selected source frames")
        if not report.get("motionReferenceFramesOneBased"):
            errors.append("synthesized delivery is missing motionReferenceFramesOneBased")
        if report.get("sourceCorrespondenceStatus") not in {
            "not-applicable-synthesized", "not-claimed"
        }:
            errors.append("synthesized delivery must not claim one-to-one correspondence")
    return errors


def delivery_mapping_errors(
    report: dict[str, Any], mapping_manifest: dict[str, Any]
) -> list[str]:
    records = mapping_manifest.get("frameMapping", [])
    if not isinstance(records, list) or not records:
        return ["cannot verify delivery frame numbers without frameMapping records"]
    try:
        expected = [int(record["nativeFrame"]) for record in records]
    except (KeyError, TypeError, ValueError):
        return ["mapping manifest contains an invalid nativeFrame value"]
    key = (
        "selectedSourceFramesOneBased"
        if mapping_manifest.get("frameConstruction") == ONE_TO_ONE
        else "motionReferenceFramesOneBased"
    )
    if report.get(key) != expected:
        return [f"delivery report {key} does not exactly match mapping manifest"]
    return []
