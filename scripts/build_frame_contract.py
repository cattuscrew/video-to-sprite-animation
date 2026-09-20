#!/usr/bin/env python3
"""Build measurable identity/placement constraints from an approved RGBA frame."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from delivery_policy import (
    ONE_TO_ONE,
    SYNTHESIZED,
    authority_policy_errors,
    mapping_manifest_errors,
)


def parse_pair(value: str) -> tuple[int, int]:
    parts = [int(part.strip()) for part in value.lower().replace("x", ",").split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected two integers, such as 512x512")
    return parts[0], parts[1]


def parse_rect(value: str) -> list[int]:
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be x,y,width,height")
    return parts


def parse_region(value: str) -> dict[str, object]:
    name, raw = value.split("=", 1)
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be name=x,y,width,height")
    return {"name": name, "rect": parts}


def parse_state_template(value: str) -> tuple[str, str]:
    name, path = value.split("=", 1)
    return name, str(Path(path).resolve())


def validate_authority(authority: dict[str, object]) -> None:
    allowed = {"canonical-original", "native-source-derived"}
    if authority.get("sourceKind") not in allowed:
        raise ValueError(f"authority sourceKind must be one of {sorted(allowed)}")
    if authority.get("userApproved") is not True:
        raise ValueError("authority/proof frame is not user-approved")
    if authority.get("derivedFromRejectedOutput") is not False:
        raise ValueError("authority may be derived from rejected output")
    if not authority.get("canonicalMaster") and not authority.get("nativeSource"):
        raise ValueError("authority names neither canonicalMaster nor nativeSource")
    policy_errors = authority_policy_errors(authority)
    if policy_errors:
        raise ValueError("; ".join(policy_errors))


def visible_bbox(alpha: np.ndarray, threshold: int = 18) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(alpha > threshold)
    if len(xs) == 0:
        raise ValueError("frame has no visible pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def contact_pivot(alpha: np.ndarray, threshold: int = 18) -> tuple[float, int]:
    ys, xs = np.nonzero(alpha > threshold)
    bottom = int(ys.max())
    contact_x = xs[ys >= bottom - 8]
    return float(contact_x.min() + contact_x.max()) / 2.0, bottom


def two_foot_pivot(
    alpha: np.ndarray, left_rect: list[int], right_rect: list[int], threshold: int = 18
) -> tuple[float, int]:
    contacts: list[tuple[float, int]] = []
    for x, y, width, height in (left_rect, right_rect):
        patch = alpha[y : y + height, x : x + width]
        ys, xs = np.nonzero(patch > threshold)
        if len(xs) == 0:
            raise ValueError("foot region contains no visible pixels")
        bottom = int(ys.max())
        contact = xs[ys >= bottom - 5] + x
        contacts.append((float(contact.min() + contact.max()) / 2.0, y + bottom))
    return (contacts[0][0] + contacts[1][0]) / 2.0, max(value[1] for value in contacts)


def edge_density(rgb: np.ndarray, alpha: np.ndarray) -> float:
    gray = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114
    dx = np.diff(gray, axis=1, append=gray[:, -1:])
    dy = np.diff(gray, axis=0, append=gray[-1:, :])
    edges = np.sqrt(dx * dx + dy * dy) > 24
    return float(np.mean(edges[alpha > 18]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("master", type=Path, help="Approved RGBA reference")
    parser.add_argument("output", type=Path, help="frame-contract.json")
    parser.add_argument("--canvas", type=parse_pair, default=(512, 512))
    parser.add_argument("--pivot", type=parse_pair, default=(256, 492))
    parser.add_argument(
        "--scale-tolerance",
        type=float,
        default=0.03,
        help=(
            "permitted visible-size ratio deviation from the master. Must cover "
            "the authority sequence's own variation: an idle animation whose "
            "arms move changes visible width by several percent, and a tolerance "
            "tighter than that rejects the approved animation rather than the repair."
        ),
    )
    parser.add_argument(
        "--pivot-tolerance",
        type=int,
        default=1,
        help=(
            "permitted contact-pivot deviation in pixels. Must likewise cover the "
            "authority's own sway; measure it rather than assuming the default."
        ),
    )
    parser.add_argument(
        "--processing-mode",
        choices=("gpt-image-per-frame-edit", "gpt-image-regeneration"),
        required=True,
    )
    parser.add_argument("--authority-manifest", required=True, type=Path)
    parser.add_argument("--source-frame-manifest", type=Path)
    parser.add_argument("--motion-reference-manifest", type=Path)
    parser.add_argument("--per-frame-authority-dir", type=Path)
    parser.add_argument("--locked-region", action="append", default=[], type=parse_region)
    parser.add_argument("--required-semantic-region", action="append", default=[], type=parse_region)
    parser.add_argument("--allowed-moving", action="append", default=[])
    parser.add_argument("--negative-space-region", action="append", default=[], type=parse_region)
    parser.add_argument("--stateful-region", action="append", default=[], type=parse_region)
    parser.add_argument("--state-template", action="append", default=[], type=parse_state_template)
    parser.add_argument(
        "--state-shift-pixels",
        type=int,
        default=2,
        help="bounded local translation allowed when matching state templates",
    )
    parser.add_argument("--approved-transition", action="append", default=[])
    parser.add_argument("--approved-hold", action="append", default=[])
    parser.add_argument("--left-foot-region", type=parse_rect)
    parser.add_argument("--right-foot-region", type=parse_rect)
    parser.add_argument(
        "--loop-type",
        choices=("natural-loop", "ping-pong-loop", "one-shot"),
        default="natural-loop",
        help=(
            "one-shot plays once and has no seam, so the seam gate is skipped "
            "and the GIF is written without a loop flag."
        ),
    )
    parser.add_argument("--max-duplicate-ratio", type=float, default=0.10)
    parser.add_argument("--max-consecutive-holds", type=int, default=1)
    parser.add_argument("--max-motion-spike-ratio", type=float, default=2.0)
    parser.add_argument("--max-silhouette-spike-ratio", type=float, default=1.8)
    parser.add_argument("--max-visible-area-step-ratio", type=float, default=0.03)
    parser.add_argument("--max-bbox-size-step-pixels", type=float, default=12.0)
    parser.add_argument("--max-bbox-size-acceleration-pixels", type=float, default=16.0)
    parser.add_argument("--max-centroid-step-pixels", type=float, default=2.0)
    parser.add_argument("--max-centroid-acceleration-pixels", type=float, default=2.0)
    parser.add_argument("--max-seam-ratio", type=float, default=3.0)
    args = parser.parse_args()

    authority = json.loads(args.authority_manifest.read_text())
    validate_authority(authority)
    if args.processing_mode != authority["processingMode"]:
        raise SystemExit(
            "--processing-mode must match authority processingMode "
            f"({authority['processingMode']})"
        )
    construction = authority["frameConstruction"]
    if construction == ONE_TO_ONE:
        if not args.per_frame_authority_dir:
            raise SystemExit("one-to-one-source requires --per-frame-authority-dir")
        if not args.source_frame_manifest:
            raise SystemExit("one-to-one-source requires --source-frame-manifest")
        if args.motion_reference_manifest:
            raise SystemExit("one-to-one-source must not use --motion-reference-manifest")
        mapping_manifest = json.loads(args.source_frame_manifest.read_text())
        mapping_errors = mapping_manifest_errors(mapping_manifest, ONE_TO_ONE)
    elif construction == SYNTHESIZED:
        if args.source_frame_manifest:
            raise SystemExit("synthesized must use --motion-reference-manifest")
        if not args.motion_reference_manifest:
            raise SystemExit("synthesized requires --motion-reference-manifest")
        mapping_manifest = json.loads(args.motion_reference_manifest.read_text())
        mapping_errors = mapping_manifest_errors(mapping_manifest, SYNTHESIZED)
    else:
        raise SystemExit(f"unsupported frameConstruction={construction!r}")
    if mapping_errors:
        raise SystemExit("invalid mapping manifest: " + "; ".join(mapping_errors))

    image = Image.open(args.master).convert("RGBA")
    rgba = np.asarray(image)
    alpha = rgba[:, :, 3]
    bbox = visible_bbox(alpha)
    if bool(args.left_foot_region) != bool(args.right_foot_region):
        raise SystemExit("--left-foot-region and --right-foot-region must be supplied together")
    pivot = (
        two_foot_pivot(alpha, args.left_foot_region, args.right_foot_region)
        if args.left_foot_region and args.right_foot_region
        else contact_pivot(alpha)
    )
    visible = alpha > 18
    rgb = rgba[:, :, :3][visible].astype(np.float32) / 255.0
    quantized = np.clip((rgb * 16).astype(np.int32), 0, 15)
    histogram = np.bincount(quantized[:, 0] * 256 + quantized[:, 1] * 16 + quantized[:, 2], minlength=4096)
    histogram = (histogram / max(1, histogram.sum())).round(6).tolist()

    templates: dict[str, list[str]] = {}
    for name, path in args.state_template:
        templates.setdefault(name, []).append(path)
    stateful_regions = []
    for region in args.stateful_region:
        stateful_regions.append(
            {
                **region,
                "templates": templates.get(str(region["name"]), []),
                "maxMeanAbsolute": 0.08,
                "maxTranslationPixels": max(0, args.state_shift_pixels),
            }
        )

    contract = {
        "version": 4,
        "frameConstruction": authority["frameConstruction"],
        "processingMode": args.processing_mode,
        "backgroundRemovalTool": authority["backgroundRemovalTool"],
        "imageExecutionInterface": authority["imageExecutionInterface"],
        "credentialMode": authority["credentialMode"],
        "pixelAuthority": authority["pixelAuthority"],
        "poseAuthority": authority["poseAuthority"],
        "mappingRole": authority["mappingRole"],
        "authorityManifest": str(args.authority_manifest.resolve()),
        "authority": authority,
        "sourceFrameManifest": (
            str(args.source_frame_manifest.resolve())
            if args.source_frame_manifest
            else None
        ),
        "motionReferenceManifest": (
            str(args.motion_reference_manifest.resolve())
            if args.motion_reference_manifest
            else None
        ),
        "sourceCorrespondenceRequired": construction == ONE_TO_ONE,
        "perFrameAuthorityDirectory": (
            str(args.per_frame_authority_dir.resolve())
            if args.per_frame_authority_dir
            else None
        ),
        "master": str(args.master.resolve()),
        "masterSize": list(image.size),
        "canvas": list(args.canvas),
        "pivot": list(args.pivot),
        "groundY": args.pivot[1],
        "visibleBounds": list(bbox),
        "visibleSize": [bbox[2] - bbox[0], bbox[3] - bbox[1]],
        "measuredContactPivot": [round(pivot[0], 2), pivot[1]],
        "pivotMeasurement": (
            {
                "method": "two-foot-anatomical",
                "leftFootRegion": args.left_foot_region,
                "rightFootRegion": args.right_foot_region,
            }
            if args.left_foot_region and args.right_foot_region
            else {"method": "lowest-contact"}
        ),
        "margins": {
            "left": bbox[0],
            "top": bbox[1],
            "right": image.width - bbox[2],
            "bottom": image.height - bbox[3],
        },
        "rgbMean": np.mean(rgb, axis=0).round(6).tolist(),
        "rgbStd": np.std(rgb, axis=0).round(6).tolist(),
        "paletteHistogram16": histogram,
        "paletteFingerprint": hashlib.sha256(bytes(quantized.tobytes())).hexdigest(),
        "edgeDensity": edge_density(rgba[:, :, :3].astype(np.float32), alpha),
        "lockedRegions": args.locked_region,
        "requiredSemanticRegions": args.required_semantic_region,
        "allowedMovingRegions": args.allowed_moving,
        "negativeSpaceRegions": [
            {**region, "maxVisiblePixels": 0} for region in args.negative_space_region
        ],
        "statefulRegions": stateful_regions,
        "approvedTemporalTransitions": args.approved_transition,
        "approvedHoldTransitions": args.approved_hold,
        "loopType": args.loop_type,
        "temporalLimits": {
            "maximumDuplicateRatio": args.max_duplicate_ratio,
            "maximumConsecutiveHolds": args.max_consecutive_holds,
            "maximumMotionSpikeRatio": args.max_motion_spike_ratio,
            "maximumSilhouetteSpikeRatio": args.max_silhouette_spike_ratio,
            "maximumVisibleAreaStepRatio": args.max_visible_area_step_ratio,
            "maximumBoundingBoxSizeStepPixels": args.max_bbox_size_step_pixels,
            "maximumBoundingBoxSizeAccelerationPixels": args.max_bbox_size_acceleration_pixels,
            "maximumCentroidStepPixels": args.max_centroid_step_pixels,
            "maximumCentroidAccelerationPixels": args.max_centroid_acceleration_pixels,
            "maximumLoopSeamRatio": args.max_seam_ratio,
        },
        "tolerances": {
            "pivotPixels": args.pivot_tolerance,
            "visibleScaleRatio": args.scale_tolerance,
            "paletteMeanAbsolute": 0.08,
            "edgeDensityAbsolute": 0.08,
            "lockedRegionMeanAbsolute": 0.06,
            "minimumMarginPixels": 1,
            "missingProtectedPixels": 0,
            "missingDarkOutlinePixels": 0,
            "newInternalHoles": 0,
            "protectedRgbMaxError": 0,
            "componentCountDelta": 0,
            "minimumSemanticCoverageRatio": 0.60,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(contract, indent=2) + "\n")
    print(f"Wrote frame contract to {args.output}")


if __name__ == "__main__":
    main()
