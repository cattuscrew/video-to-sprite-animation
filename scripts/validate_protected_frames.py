#!/usr/bin/env python3
"""Reject rembg frames that lose protected artwork or use circular authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from delivery_policy import ONE_TO_ONE, authority_policy_errors


ALLOWED_SOURCE_KINDS = {"canonical-original", "native-source-derived"}


def components(mask: np.ndarray) -> int:
    return int(ndimage.label(mask)[1])


def internal_holes(visible: np.ndarray) -> int:
    transparent = ~visible
    labels, count = ndimage.label(transparent)
    if not count:
        return 0
    border_labels = np.unique(
        np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    )
    return sum(label not in set(int(value) for value in border_labels) for label in range(1, count + 1))


def validate_authority(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if manifest.get("sourceKind") not in ALLOWED_SOURCE_KINDS:
        errors.append(f"authority sourceKind must be one of {sorted(ALLOWED_SOURCE_KINDS)}")
    if manifest.get("userApproved") is not True:
        errors.append("authority/proof frame is not user-approved")
    if manifest.get("derivedFromRejectedOutput") is not False:
        errors.append("authority may be derived from rejected output")
    if not manifest.get("canonicalMaster") and not manifest.get("nativeSource"):
        errors.append("authority names neither canonicalMaster nor nativeSource")
    errors.extend(authority_policy_errors(manifest))
    if manifest.get("frameConstruction") != ONE_TO_ONE:
        errors.append("protected-frame validation requires one-to-one-source")
    if manifest.get("backgroundRemovalTool") != "rembg":
        errors.append("protected-frame RGB validation is only valid for rembg")
    return errors


def semantic_region_errors(
    rgba: np.ndarray,
    reference: np.ndarray,
    regions: list[dict[str, object]],
) -> list[str]:
    errors: list[str] = []
    for region in regions:
        name = str(region["name"])
        x, y, width, height = [int(value) for value in region["rect"]]
        expected = reference[y : y + height, x : x + width]
        actual = rgba[y : y + height, x : x + width]
        if expected.size == 0 or actual.shape != expected.shape:
            errors.append(f"semantic region {name} is outside the canvas")
            continue
        protected = expected[:, :, 3] > 18
        missing = int(np.count_nonzero(protected & (actual[:, :, 3] <= 18)))
        if missing:
            errors.append(f"semantic region {name} missing protected pixels={missing}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("authority_dir", type=Path)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("authority_manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.authority_manifest.read_text())
    errors = validate_authority(manifest)
    references = sorted(args.authority_dir.glob("*.png"))
    frames = sorted(args.frames_dir.glob("*.png"))
    if not references or len(references) != len(frames):
        errors.append(f"authority/frame count mismatch {len(references)}/{len(frames)}")
    regions = list(manifest.get("requiredSemanticRegions", []))
    records: list[dict[str, object]] = []
    diagnostics = args.output / "diagnostics"

    for index, (reference_path, frame_path) in enumerate(zip(references, frames), start=1):
        reference = np.asarray(Image.open(reference_path).convert("RGBA"), dtype=np.uint8)
        frame = np.asarray(Image.open(frame_path).convert("RGBA"), dtype=np.uint8)
        frame_errors: list[str] = []
        if reference.shape != frame.shape:
            frame_errors.append(f"shape={frame.shape} expected={reference.shape}")
        else:
            reference_visible = reference[:, :, 3] > 18
            frame_visible = frame[:, :, 3] > 18
            dark_outline = reference_visible & (np.mean(reference[:, :, :3], axis=2) < 96)
            missing = reference_visible & ~frame_visible
            missing_dark = dark_outline & ~frame_visible
            added = frame_visible & ~reference_visible
            rgb_delta = np.max(
                np.abs(
                    frame[:, :, :3][reference_visible].astype(int)
                    - reference[:, :, :3][reference_visible].astype(int)
                ),
                axis=1,
            )
            missing_count = int(np.count_nonzero(missing))
            missing_dark_count = int(np.count_nonzero(missing_dark))
            added_count = int(np.count_nonzero(added))
            protected_rgb_max = int(rgb_delta.max()) if len(rgb_delta) else 0
            reference_components = components(reference_visible)
            frame_components = components(frame_visible)
            reference_holes = internal_holes(reference_visible)
            frame_holes = internal_holes(frame_visible)
            if missing_count:
                frame_errors.append(f"missing protected pixels={missing_count}")
            if missing_dark_count:
                frame_errors.append(f"missing dark-outline pixels={missing_dark_count}")
            if added_count:
                frame_errors.append(f"added visible pixels={added_count}")
            if protected_rgb_max:
                frame_errors.append(f"protected RGB max error={protected_rgb_max}")
            if frame_components != reference_components:
                frame_errors.append(
                    f"component count={frame_components} expected={reference_components}"
                )
            if frame_holes != reference_holes:
                frame_errors.append(f"internal holes={frame_holes} expected={reference_holes}")
            frame_errors.extend(semantic_region_errors(frame, reference, regions))

            if frame_errors:
                overlay = frame.copy()
                overlay[missing] = [255, 0, 255, 255]
                overlay[added] = [0, 255, 255, 255]
                diagnostics.mkdir(parents=True, exist_ok=True)
                Image.fromarray(overlay, "RGBA").save(diagnostics / frame_path.name)
            records.append(
                {
                    "frame": index,
                    "status": "accepted" if not frame_errors else "repair-needed",
                    "errors": frame_errors,
                    "missingProtectedPixels": missing_count,
                    "missingDarkOutlinePixels": missing_dark_count,
                    "addedVisiblePixels": added_count,
                    "protectedRgbMaxError": protected_rgb_max,
                    "componentCount": frame_components,
                    "referenceComponentCount": reference_components,
                    "internalHoles": frame_holes,
                    "referenceInternalHoles": reference_holes,
                }
            )
        errors.extend(f"frame {index}: {error}" for error in frame_errors)

    report = {
        "status": "accepted" if not errors else "repair-needed",
        "authorityManifest": str(args.authority_manifest.resolve()),
        "authority": manifest,
        "errors": errors,
        "failedFrameCount": sum(record["status"] != "accepted" for record in records),
        "frames": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "protected-validation-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps({"status": report["status"], "errors": len(errors)}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
