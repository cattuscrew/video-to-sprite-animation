#!/usr/bin/env python3
"""Validate duplicate holds, motion spikes, seams, locked regions, and semantic states."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def region_patch(rgba: np.ndarray, rect: list[int]) -> np.ndarray:
    x, y, width, height = [int(value) for value in rect]
    return rgba[y : y + height, x : x + width]


def shifted_mean_absolute(current: np.ndarray, template: np.ndarray, max_shift: int) -> float:
    """Compare a state patch while allowing only a small local translation.

    Regenerative timelines may deform an approved state by a pixel or two. A
    bounded search absorbs that deterministic motion without allowing a model
    to replace the semantic drawing: eye/face changes still affect most of the
    patch and remain above the contract threshold.
    """
    height, width = current.shape[:2]
    best = float("inf")
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            current_y0 = max(0, dy)
            current_y1 = min(height, height + dy)
            current_x0 = max(0, dx)
            current_x1 = min(width, width + dx)
            template_y0 = max(0, -dy)
            template_y1 = min(height, height - dy)
            template_x0 = max(0, -dx)
            template_x1 = min(width, width - dx)
            if current_y0 >= current_y1 or current_x0 >= current_x1:
                continue
            delta = float(
                np.mean(
                    np.abs(
                        current[current_y0:current_y1, current_x0:current_x1]
                        - template[template_y0:template_y1, template_x0:template_x1]
                    )
                )
            )
            best = min(best, delta)
    return best


def motion_energy(a: np.ndarray, b: np.ndarray, ignored: list[list[int]]) -> float:
    mask = (a[:, :, 3] > 18) | (b[:, :, 3] > 18)
    for rect in ignored:
        x, y, width, height = rect
        mask[y : y + height, x : x + width] = False
    if not np.any(mask):
        return 0.0
    return float(np.mean(np.abs(a.astype(np.float32)[mask] - b.astype(np.float32)[mask])) / 255.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--max-duplicate-ratio", type=float)
    parser.add_argument("--max-consecutive-holds", type=int)
    parser.add_argument("--max-motion-spike-ratio", type=float)
    parser.add_argument("--max-seam-ratio", type=float)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text())
    temporal = contract.get("temporalLimits", {})
    max_duplicate_ratio = args.max_duplicate_ratio if args.max_duplicate_ratio is not None else float(temporal.get("maximumDuplicateRatio", 0.10))
    max_consecutive_holds = args.max_consecutive_holds if args.max_consecutive_holds is not None else int(temporal.get("maximumConsecutiveHolds", 1))
    max_motion_spike_ratio = args.max_motion_spike_ratio if args.max_motion_spike_ratio is not None else float(temporal.get("maximumMotionSpikeRatio", 3.0))
    max_seam_ratio = args.max_seam_ratio if args.max_seam_ratio is not None else float(temporal.get("maximumLoopSeamRatio", 3.0))
    paths = sorted(args.frames.glob("frame-*.png"))
    if len(paths) < 2:
        raise SystemExit("Need at least two PNG frames")
    images = [np.asarray(Image.open(path).convert("RGBA")) for path in paths]
    expected_size = tuple(contract["canvas"])
    if any((image.shape[1], image.shape[0]) != expected_size for image in images):
        raise SystemExit("Frame canvas does not match the contract")

    stateful = contract.get("statefulRegions", [])
    ignored = [list(map(int, region["rect"])) for region in stateful]
    energies = [
        motion_energy(images[index], images[(index + 1) % len(images)], ignored)
        for index in range(len(images))
    ]
    duplicates = [
        index
        for index in range(len(images) - 1)
        if hashlib.sha256(images[index].tobytes()).digest()
        == hashlib.sha256(images[index + 1].tobytes()).digest()
    ]
    approved_holds = set(contract.get("approvedHoldTransitions", []))
    unapproved_duplicates = [
        index for index in duplicates if f"{index + 1}->{index + 2}" not in approved_holds
    ]
    longest_hold_run = 0
    current_run = 0
    for index in range(len(images) - 1):
        if index in unapproved_duplicates:
            current_run += 1
            longest_hold_run = max(longest_hold_run, current_run)
        else:
            current_run = 0
    duplicate_ratio = len(unapproved_duplicates) / max(1, len(images) - 1)
    nonzero = [value for value in energies[:-1] if value > 1e-8]
    median_motion = float(np.median(nonzero)) if nonzero else 0.0
    approved = set(contract.get("approvedTemporalTransitions", []))
    spikes = []
    if median_motion:
        for index, value in enumerate(energies[:-1]):
            transition = f"{index + 1}->{index + 2}"
            if value > median_motion * max_motion_spike_ratio and transition not in approved:
                spikes.append({"transition": transition, "energy": value})
    seam_ratio = energies[-1] / median_motion if median_motion else (0.0 if energies[-1] == 0 else float("inf"))

    locked_failures = []
    locked_limit = float(contract["tolerances"].get("lockedRegionMeanAbsolute", 0.06))
    for region in contract.get("lockedRegions", []):
        for index in range(len(images) - 1):
            first = region_patch(images[index], region["rect"]).astype(np.float32) / 255.0
            second = region_patch(images[index + 1], region["rect"]).astype(np.float32) / 255.0
            delta = float(np.mean(np.abs(first - second)))
            if delta > locked_limit:
                locked_failures.append(
                    {"region": region["name"], "transition": f"{index + 1}->{index + 2}", "delta": delta}
                )

    negative_space_failures = []
    for region in contract.get("negativeSpaceRegions", []):
        allowed = int(region.get("maxVisiblePixels", 0))
        for index, image in enumerate(images, start=1):
            visible = int(np.count_nonzero(region_patch(image, region["rect"])[:, :, 3] > 18))
            if visible > allowed:
                negative_space_failures.append(
                    {"region": region["name"], "frame": index, "visiblePixels": visible, "allowed": allowed}
                )

    state_failures = []
    for region in stateful:
        templates = [np.asarray(Image.open(path).convert("RGBA")) for path in region.get("templates", [])]
        if not templates:
            state_failures.append({"region": region["name"], "error": "no approved templates"})
            continue
        limit = float(region.get("maxMeanAbsolute", 0.08))
        max_shift = max(0, int(region.get("maxTranslationPixels", 2)))
        template_patches = [region_patch(template, region["rect"]).astype(np.float32) / 255.0 for template in templates]
        for index, image in enumerate(images, start=1):
            current = region_patch(image, region["rect"]).astype(np.float32) / 255.0
            delta = min(shifted_mean_absolute(current, template, max_shift) for template in template_patches)
            if delta > limit:
                state_failures.append({"region": region["name"], "frame": index, "nearestDelta": delta})

    errors = []
    if duplicate_ratio > max_duplicate_ratio:
        errors.append(f"duplicate ratio {duplicate_ratio:.3f} exceeds {max_duplicate_ratio:.3f}")
    if longest_hold_run > max_consecutive_holds:
        errors.append(f"consecutive hold run {longest_hold_run} exceeds {max_consecutive_holds}")
    if spikes:
        errors.append(f"unapproved motion spikes: {len(spikes)}")
    if seam_ratio > max_seam_ratio:
        errors.append(f"loop seam ratio {seam_ratio:.3f} exceeds {max_seam_ratio:.3f}")
    if locked_failures:
        errors.append(f"locked-region transitions failed: {len(locked_failures)}")
    if negative_space_failures:
        errors.append(f"negative-space probes failed: {len(negative_space_failures)}")
    if state_failures:
        errors.append(f"semantic-state matches failed: {len(state_failures)}")

    result = {
        "status": "accepted" if not errors else "repair-needed",
        "frameCount": len(images),
        "fps": args.fps,
        "durationSeconds": len(images) / args.fps,
        "duplicateTransitions": [f"{index + 1}->{index + 2}" for index in duplicates],
        "approvedHoldTransitions": sorted(approved_holds),
        "unapprovedDuplicateTransitions": [f"{index + 1}->{index + 2}" for index in unapproved_duplicates],
        "duplicateRatio": duplicate_ratio,
        "longestConsecutiveHoldRun": longest_hold_run,
        "motionEnergy": energies,
        "medianNonzeroMotion": median_motion,
        "motionSpikes": spikes,
        "loopSeamEnergy": energies[-1],
        "loopSeamRatio": seam_ratio,
        "lockedRegionFailures": locked_failures,
        "negativeSpaceFailures": negative_space_failures,
        "stateFailures": state_failures,
        "errors": errors,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "temporal-validation-report.json").write_text(json.dumps(result, indent=2) + "\n")

    width, height = 900, 300
    plot = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(plot)
    maximum = max(energies) or 1.0
    points = []
    for index, value in enumerate(energies):
        x = 30 + round(index * (width - 60) / max(1, len(energies) - 1))
        y = height - 30 - round(value * (height - 60) / maximum)
        points.append((x, y))
    if len(points) > 1:
        draw.line(points, fill=(30, 90, 180), width=2)
    for index in duplicates:
        x, _ = points[index]
        draw.line((x, 20, x, height - 20), fill=(220, 80, 80), width=1)
    draw.text((10, 8), f"status={result['status']} duplicateRatio={duplicate_ratio:.3f} seamRatio={seam_ratio:.3f}", fill="black")
    plot.save(args.output / "temporal-motion-plot.png")

    print(json.dumps({"status": result["status"], "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
