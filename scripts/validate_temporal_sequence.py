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


def silhouette_metrics(image: np.ndarray) -> dict[str, object]:
    mask = image[:, :, 3] > 18
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return {"mask": mask, "area": 0, "bbox": [0, 0, 0, 0], "size": [0, 0], "centroid": [0.0, 0.0]}
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    return {
        "mask": mask,
        "area": int(mask.sum()),
        "bbox": [left, top, right, bottom],
        "size": [right - left, bottom - top],
        "centroid": [float(xs.mean()), float(ys.mean())],
    }


def silhouette_change(first: dict[str, object], second: dict[str, object]) -> float:
    union = np.logical_or(first["mask"], second["mask"])
    changed = np.logical_xor(first["mask"], second["mask"])
    return float(changed.sum() / max(1, union.sum()))


def pair_geometry_failure(
    first: dict[str, object],
    second: dict[str, object],
    frames: tuple[int, int],
    limits: dict[str, float],
    approved: set[str] | None = None,
    median_silhouette: float = 0.0,
) -> dict[str, object] | None:
    """Gate one transition. `frames` carries real frame numbers, so a partial
    run never treats two frames either side of a gap as neighbours."""
    transition = f"{frames[0]}->{frames[1]}"
    if approved and transition in approved:
        return None
    change = silhouette_change(first, second)
    area_step = abs(int(second["area"]) - int(first["area"])) / max(1, int(first["area"]))
    bbox_step = [
        abs(int(second["size"][axis]) - int(first["size"][axis])) for axis in (0, 1)
    ]
    centroid_step = float(
        np.linalg.norm(np.asarray(second["centroid"]) - np.asarray(first["centroid"]))
    )
    reasons = []
    if median_silhouette and change > median_silhouette * limits["maximumSilhouetteSpikeRatio"]:
        reasons.append("silhouette-change spike")
    if area_step > limits["maximumVisibleAreaStepRatio"]:
        reasons.append("visible-area step")
    if max(bbox_step) > limits["maximumBoundingBoxSizeStepPixels"]:
        reasons.append("bounding-box size step")
    if centroid_step > limits["maximumCentroidStepPixels"]:
        reasons.append("centroid step")
    if not reasons:
        return None
    return {
        "transition": transition,
        "reasons": reasons,
        "silhouetteChange": change,
        "visibleAreaStepRatio": area_step,
        "boundingBoxSizeStepPixels": bbox_step,
        "centroidStepPixels": centroid_step,
    }


def triplet_acceleration_failure(
    first: dict[str, object],
    second: dict[str, object],
    third: dict[str, object],
    frames: tuple[int, int, int],
    limits: dict[str, float],
    approved: set[str] | None = None,
) -> dict[str, object] | None:
    """Gate the second difference across one triplet of consecutive frames."""
    if approved and {
        f"{frames[0]}->{frames[1]}",
        f"{frames[1]}->{frames[2]}",
    } & approved:
        return None
    sizes = [first["size"], second["size"], third["size"]]
    bbox_acceleration = [
        abs(int(sizes[2][axis]) - 2 * int(sizes[1][axis]) + int(sizes[0][axis]))
        for axis in (0, 1)
    ]
    centroids = [
        np.asarray(item["centroid"], dtype=np.float32) for item in (first, second, third)
    ]
    centroid_acceleration = float(
        np.linalg.norm(centroids[2] - 2 * centroids[1] + centroids[0])
    )
    reasons = []
    if max(bbox_acceleration) > limits["maximumBoundingBoxSizeAccelerationPixels"]:
        reasons.append("bounding-box size acceleration")
    if centroid_acceleration > limits["maximumCentroidAccelerationPixels"]:
        reasons.append("centroid acceleration")
    if not reasons:
        return None
    return {
        "frame": frames[1],
        "reasons": reasons,
        "boundingBoxSizeAccelerationPixels": bbox_acceleration,
        "centroidAccelerationPixels": centroid_acceleration,
    }


def alpha_onion(first: np.ndarray, second: np.ndarray) -> Image.Image:
    a = first[:, :, 3] > 18
    b = second[:, :, 3] > 18
    rgb = np.zeros((*a.shape, 3), dtype=np.uint8)
    rgb[:, :, 0] = a.astype(np.uint8) * 255
    rgb[:, :, 1] = b.astype(np.uint8) * 255
    rgb[:, :, 2] = b.astype(np.uint8) * 255
    return Image.fromarray(rgb, "RGB")


def thumbnail(image: Image.Image, size: tuple[int, int] = (240, 240)) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (32, 32, 32, 255))
    canvas.alpha_composite(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2))
    return canvas


def write_temporal_diagnostics(
    output: Path,
    images: list[np.ndarray],
    flagged_frames: set[int],
) -> dict[str, object]:
    diagnostic_dir = output / "temporal-triplets"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    for frame_number in sorted(flagged_frames):
        index = frame_number - 1
        panels = []
        for item in (max(0, index - 1), index, min(len(images) - 1, index + 1)):
            panels.append(thumbnail(Image.fromarray(images[item], "RGBA")))
        sheet = Image.new("RGBA", (720, 270), (255, 255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        for panel_index, panel in enumerate(panels):
            sheet.alpha_composite(panel, (panel_index * 240, 30))
        draw.text((8, 8), f"previous / frame {frame_number:03d} / next", fill="black")
        sheet.convert("RGB").save(diagnostic_dir / f"frame-{frame_number:03d}-triplet.png")

    onions = [alpha_onion(images[index], images[index + 1]) for index in range(len(images) - 1)]
    tile = 120
    columns = min(8, max(1, len(onions)))
    rows = (len(onions) + columns - 1) // columns
    onion_sheet = Image.new("RGB", (columns * tile, rows * (tile + 18)), "white")
    draw = ImageDraw.Draw(onion_sheet)
    for index, item in enumerate(onions):
        item.thumbnail((tile, tile), Image.Resampling.NEAREST)
        x = (index % columns) * tile
        y = (index // columns) * (tile + 18)
        onion_sheet.paste(item, (x, y))
        draw.text((x + 2, y + tile + 2), f"{index + 1}->{index + 2}", fill="black")
    onion_path = output / "temporal-alpha-onion-sheet.png"
    onion_sheet.save(onion_path)
    return {
        "flaggedTripletDirectory": str(diagnostic_dir.resolve()),
        "flaggedTripletCount": len(flagged_frames),
        "alphaOnionSheet": str(onion_path.resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--max-duplicate-ratio", type=float)
    parser.add_argument("--max-consecutive-holds", type=int)
    parser.add_argument("--max-motion-spike-ratio", type=float)
    parser.add_argument("--max-silhouette-spike-ratio", type=float)
    parser.add_argument("--max-visible-area-step-ratio", type=float)
    parser.add_argument("--max-bbox-size-step-pixels", type=float)
    parser.add_argument("--max-bbox-size-acceleration-pixels", type=float)
    parser.add_argument("--max-centroid-step-pixels", type=float)
    parser.add_argument("--max-centroid-acceleration-pixels", type=float)
    parser.add_argument("--max-seam-ratio", type=float)
    parser.add_argument(
        "--frame-manifest",
        type=Path,
        help=(
            "Source or parent frame manifest. Supplying it makes a missing frame "
            "an error instead of letting the frames either side become neighbours."
        ),
    )
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text())
    temporal = contract.get("temporalLimits", {})
    max_duplicate_ratio = args.max_duplicate_ratio if args.max_duplicate_ratio is not None else float(temporal.get("maximumDuplicateRatio", 0.10))
    max_consecutive_holds = args.max_consecutive_holds if args.max_consecutive_holds is not None else int(temporal.get("maximumConsecutiveHolds", 1))
    max_motion_spike_ratio = args.max_motion_spike_ratio if args.max_motion_spike_ratio is not None else float(temporal.get("maximumMotionSpikeRatio", 2.0))
    max_silhouette_spike_ratio = args.max_silhouette_spike_ratio if args.max_silhouette_spike_ratio is not None else float(temporal.get("maximumSilhouetteSpikeRatio", 1.8))
    max_area_step = args.max_visible_area_step_ratio if args.max_visible_area_step_ratio is not None else float(temporal.get("maximumVisibleAreaStepRatio", 0.03))
    max_bbox_step = args.max_bbox_size_step_pixels if args.max_bbox_size_step_pixels is not None else float(temporal.get("maximumBoundingBoxSizeStepPixels", 12.0))
    max_bbox_accel = args.max_bbox_size_acceleration_pixels if args.max_bbox_size_acceleration_pixels is not None else float(temporal.get("maximumBoundingBoxSizeAccelerationPixels", 16.0))
    max_centroid_step = args.max_centroid_step_pixels if args.max_centroid_step_pixels is not None else float(temporal.get("maximumCentroidStepPixels", 2.0))
    max_centroid_accel = args.max_centroid_acceleration_pixels if args.max_centroid_acceleration_pixels is not None else float(temporal.get("maximumCentroidAccelerationPixels", 1.5))
    max_seam_ratio = args.max_seam_ratio if args.max_seam_ratio is not None else float(temporal.get("maximumLoopSeamRatio", 3.0))
    missing: list[int] = []
    numbers: list[int] = []
    if args.frame_manifest:
        # With a manifest the expected set is known, so a hole is reported
        # rather than closed. Globbing alone cannot tell a missing frame from
        # a shorter sequence, and would make frames either side of the gap
        # neighbours -- which reads as a smooth sequence that was never made.
        mapping = json.loads(args.frame_manifest.read_text()).get("frameMapping", [])
        paths = []
        for record in mapping:
            index = int(record["outputFrame"])
            candidate = args.frames / str(
                record.get("outputFile") or f"frame-{index:03d}.png"
            )
            if candidate.is_file():
                paths.append(candidate)
                numbers.append(index)
            else:
                missing.append(index)
    else:
        paths = sorted(args.frames.glob("frame-*.png"))
        numbers = list(range(1, len(paths) + 1))
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

    silhouettes = [silhouette_metrics(image) for image in images]
    silhouette_deltas = []
    area_steps = []
    bbox_steps = []
    centroid_steps = []
    for index in range(len(images) - 1):
        first, second = silhouettes[index], silhouettes[index + 1]
        silhouette_deltas.append(silhouette_change(first, second))
        area_steps.append(abs(int(second["area"]) - int(first["area"])) / max(1, int(first["area"])))
        bbox_steps.append([
            abs(int(second["size"][0]) - int(first["size"][0])),
            abs(int(second["size"][1]) - int(first["size"][1])),
        ])
        centroid_steps.append(float(np.linalg.norm(np.asarray(second["centroid"]) - np.asarray(first["centroid"]))))
    nonzero_silhouette = [value for value in silhouette_deltas if value > 1e-8]
    median_silhouette = float(np.median(nonzero_silhouette)) if nonzero_silhouette else 0.0
    limits = {
        "maximumSilhouetteSpikeRatio": max_silhouette_spike_ratio,
        "maximumVisibleAreaStepRatio": max_area_step,
        "maximumBoundingBoxSizeStepPixels": max_bbox_step,
        "maximumCentroidStepPixels": max_centroid_step,
        "maximumBoundingBoxSizeAccelerationPixels": max_bbox_accel,
        "maximumCentroidAccelerationPixels": max_centroid_accel,
    }
    geometry_failures = []
    flagged_frames: set[int] = set()
    for index in range(len(images) - 1):
        failure = pair_geometry_failure(
            silhouettes[index],
            silhouettes[index + 1],
            (numbers[index], numbers[index + 1]),
            limits,
            approved,
            median_silhouette,
        )
        if failure:
            geometry_failures.append(failure)
            flagged_frames.update((numbers[index], numbers[index + 1]))

    acceleration_failures = []
    for index in range(1, len(images) - 1):
        failure = triplet_acceleration_failure(
            silhouettes[index - 1],
            silhouettes[index],
            silhouettes[index + 1],
            (numbers[index - 1], numbers[index], numbers[index + 1]),
            limits,
            approved,
        )
        if failure:
            acceleration_failures.append(failure)
            flagged_frames.add(numbers[index])
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

    errors = [f"missing output frame {number}" for number in missing]
    if duplicate_ratio > max_duplicate_ratio:
        errors.append(f"duplicate ratio {duplicate_ratio:.3f} exceeds {max_duplicate_ratio:.3f}")
    if longest_hold_run > max_consecutive_holds:
        errors.append(f"consecutive hold run {longest_hold_run} exceeds {max_consecutive_holds}")
    if spikes:
        errors.append(f"unapproved motion spikes: {len(spikes)}")
    if geometry_failures:
        errors.append(f"local silhouette/geometry transitions failed: {len(geometry_failures)}")
    if acceleration_failures:
        errors.append(f"local silhouette/geometry accelerations failed: {len(acceleration_failures)}")
    if seam_ratio > max_seam_ratio:
        errors.append(f"loop seam ratio {seam_ratio:.3f} exceeds {max_seam_ratio:.3f}")
    if locked_failures:
        errors.append(f"locked-region transitions failed: {len(locked_failures)}")
    if negative_space_failures:
        errors.append(f"negative-space probes failed: {len(negative_space_failures)}")
    if state_failures:
        errors.append(f"semantic-state matches failed: {len(state_failures)}")

    args.output.mkdir(parents=True, exist_ok=True)
    diagnostics = write_temporal_diagnostics(args.output, images, flagged_frames)
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
        "silhouetteChange": silhouette_deltas,
        "medianNonzeroSilhouetteChange": median_silhouette,
        "visibleAreaStepRatio": area_steps,
        "boundingBoxSizeStepPixels": bbox_steps,
        "centroidStepPixels": centroid_steps,
        "geometryTransitionFailures": geometry_failures,
        "geometryAccelerationFailures": acceleration_failures,
        "diagnostics": diagnostics,
        "loopSeamEnergy": energies[-1],
        "loopSeamRatio": seam_ratio,
        "lockedRegionFailures": locked_failures,
        "negativeSpaceFailures": negative_space_failures,
        "stateFailures": state_failures,
        "errors": errors,
    }
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
