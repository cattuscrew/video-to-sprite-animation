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


def expected_tool_fields(
    construction: str, tool: str, processing_mode: str
) -> dict[str, str] | None:
    policies = {
        (ONE_TO_ONE, "GPT Image", "gpt-image-per-frame-edit"): {
            "processingMode": "gpt-image-per-frame-edit",
            "pixelAuthority": "gpt-edited-selected-source-frame",
            "poseAuthority": "selected-native-source-frame",
            "mappingRole": SOURCE_MAPPING_ROLE,
        },
        (SYNTHESIZED, "GPT Image", "gpt-image-regeneration"): {
            "processingMode": "gpt-image-regeneration",
            "pixelAuthority": "approved-gpt-master",
            "poseAuthority": "synthesized-from-motion-reference",
            "mappingRole": MOTION_MAPPING_ROLE,
        },
    }
    return policies.get((construction, tool, processing_mode))


def authority_policy_errors(authority: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    construction = authority.get("frameConstruction")
    tool = authority.get("backgroundRemovalTool")
    if construction not in {ONE_TO_ONE, SYNTHESIZED}:
        return ["authority frameConstruction must be one-to-one-source or synthesized"]
    if tool != "GPT Image":
        return ["authority backgroundRemovalTool must be GPT Image"]
    if authority.get("imageExecutionInterface") != "built-in-image-tool":
        errors.append("authority imageExecutionInterface must be built-in-image-tool")
    if authority.get("credentialMode") != "none":
        errors.append("authority credentialMode must be none; API credentials are forbidden")
    processing_mode = str(authority.get("processingMode", ""))
    expected = expected_tool_fields(str(construction), str(tool), processing_mode)
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
        if authority.get("parentFrameManifest") or authority.get("parentFramesDirectory"):
            errors.append(
                "parent-frame repair lineage is no longer a mode; every output is "
                "edited from its own mapped native frame"
            )
        if tool == "GPT Image":
            if approval.get("perFrameGptEditApproved") is not True:
                errors.append("per-frame GPT Image editing is not explicitly approved")
            if approval.get("sourcePixelChangesAccepted") is not True:
                errors.append("GPT Image source-pixel changes are not explicitly accepted")
            color_reference = authority.get("canonicalColorReference")
            if not isinstance(color_reference, dict):
                errors.append("GPT Image authority lacks canonicalColorReference")
            else:
                if color_reference.get("role") != "appearance-only":
                    errors.append("canonical color reference role must be appearance-only")
                digest = color_reference.get("sha256")
                if not isinstance(digest, str) or len(digest) != 64:
                    errors.append("canonical color reference lacks SHA-256")
                if not color_reference.get("path"):
                    errors.append("canonical color reference lacks path")
            if approval.get("canonicalColorReferenceApproved") is not True:
                errors.append("canonical color reference is not explicitly approved")
            strategy = authority.get("colorConsistencyStrategy")
            if strategy not in {
                "reference-guided-gpt",
                "reference-guided-gpt-with-deterministic-palette-normalization",
            }:
                errors.append("GPT Image authority lacks an approved color-consistency strategy")
            if approval.get("colorConsistencyStrategyApproved") is not True:
                errors.append("color-consistency strategy is not explicitly approved")
            if approval.get("batchExecutionApproved") is not True:
                errors.append("GPT Image batch execution is not explicitly approved")
            errors.extend(retry_budget_errors(approval))
            errors.extend(registration_policy_errors(authority))
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


RETRY_BUDGET_KINDS = ("safetyBlock", "quality")

REGISTRATION_POLICIES = {
    "translation-only-to-authority",
    "not-applied",
}


def retry_budget_errors(approval: dict[str, Any]) -> list[str]:
    """Retry budgets are optional, but a stated one must be usable.

    The two kinds are counted separately because they mean different things: an
    output-stage moderation block says nothing about the frame, while a failed
    gate says everything about it. One shared number lets random blocks eat the
    budget meant for real defects.
    """
    budgets = approval.get("retryBudgets")
    if budgets is None:
        return []
    if not isinstance(budgets, dict):
        return ["approvalScope retryBudgets must be an object"]
    errors: list[str] = []
    for kind in RETRY_BUDGET_KINDS:
        if kind not in budgets:
            errors.append(f"retryBudgets is missing {kind}")
            continue
        value = budgets[kind]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"retryBudgets {kind} must be a non-negative integer")
    unknown = set(budgets) - set(RETRY_BUDGET_KINDS)
    if unknown:
        errors.append(f"retryBudgets has unknown kinds: {sorted(unknown)}")
    return errors


def registration_policy_errors(authority: dict[str, Any]) -> list[str]:
    """Registration policy is optional, but must be declared honestly.

    Translation onto a frame's own authority is not per-frame recentering: the
    offset is measured against that frame's own mapped native frame, never
    against a neighbour, and never changes scale or rotation.
    """
    errors: list[str] = []
    registration = authority.get("registrationPolicy")
    if registration is not None:
        if not isinstance(registration, dict):
            return ["registrationPolicy must be an object"]
        kind = registration.get("type")
        if kind not in REGISTRATION_POLICIES:
            errors.append(
                f"registrationPolicy type must be one of {sorted(REGISTRATION_POLICIES)}"
            )
        if kind == "translation-only-to-authority":
            limit = registration.get("maxPixels")
            if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
                errors.append("registrationPolicy maxPixels must be a positive number")

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
        expected_class = "source-frame-gpt-edit"
        if tool != "GPT Image":
            errors.append("one-to-one mapping tool must be GPT Image")
        if manifest.get("imageExecutionInterface") != "built-in-image-tool":
            errors.append("one-to-one mapping must use built-in-image-tool")
        if manifest.get("credentialMode") != "none":
            errors.append("one-to-one mapping credentialMode must be none")
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
        "imageExecutionInterface", "credentialMode",
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
        if contract.get("parentFrameManifest") or contract.get("parentFramesDirectory"):
            errors.append("contract must not claim parent-frame repair lineage")
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
    for field in (
        "frameConstruction", "processingMode", "backgroundRemovalTool",
        "imageExecutionInterface", "credentialMode",
    ):
        if report.get(field) != authority.get(field):
            errors.append(f"delivery report {field} does not match authority")
    construction = authority.get("frameConstruction")
    tool = authority.get("backgroundRemovalTool")
    classification = report.get("processingClassification")
    if construction == ONE_TO_ONE:
        if classification != "source-frame-gpt-edit":
            errors.append(
                "one-to-one delivery classification must be source-frame-gpt-edit"
            )
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


def visual_qa_report_errors(report: dict[str, Any]) -> list[str]:
    """Require evidence that subtle temporal redraw drift was actually reviewed."""
    errors: list[str] = []
    if report.get("status") != "accepted":
        errors.append("visual QA report status is not accepted")
    required_checks = (
        "normalSpeedReviewed",
        "slowSpeedReviewed",
        "tripletsReviewed",
        "onionSkinReviewed",
        "sourceOutputPairsReviewed",
        "sourceMotionCompared",
        "topologyAndLandmarksReviewed",
    )
    for field in required_checks:
        if report.get(field) is not True:
            errors.append(f"visual QA report lacks {field}")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("visual QA report lacks artifact paths")
    else:
        for field in (
            "exactFpsPreview",
            "slowPreview",
            "triplets",
            "onionSkin",
            "sourceMotionComparison",
        ):
            if not artifacts.get(field):
                errors.append(f"visual QA report lacks {field} artifact")
    reviewer = report.get("reviewer")
    if reviewer not in {"agent", "user", "agent-and-user"}:
        errors.append("visual QA report has invalid reviewer")
    return errors
