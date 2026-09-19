#!/usr/bin/env python3
"""Validate frames against a frame contract and preserve visible repair diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


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


def measured_pivot(alpha: np.ndarray, contract: dict[str, object], threshold: int = 18) -> tuple[float, int]:
    measurement = contract.get("pivotMeasurement", {})
    if not isinstance(measurement, dict) or measurement.get("method") != "two-foot-anatomical":
        return contact_pivot(alpha, threshold)
    contacts: list[tuple[float, int]] = []
    for key in ("leftFootRegion", "rightFootRegion"):
        x, y, width, height = [int(value) for value in measurement[key]]
        patch = alpha[y : y + height, x : x + width]
        ys, xs = np.nonzero(patch > threshold)
        if len(xs) == 0:
            raise ValueError(f"{key} contains no visible pixels")
        bottom = int(ys.max())
        contact = xs[ys >= bottom - 5] + x
        contacts.append((float(contact.min() + contact.max()) / 2.0, y + bottom))
    return (contacts[0][0] + contacts[1][0]) / 2.0, max(value[1] for value in contacts)


def visible_rgb(image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(image.convert("RGBA"))
    visible = rgba[:, :, 3] > 18
    return rgba[:, :, :3][visible].astype(np.float32) / 255.0, rgba[:, :, 3]


def edge_density(rgb: np.ndarray, alpha: np.ndarray) -> float:
    gray = rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114
    dx = np.diff(gray, axis=1, append=gray[:, -1:])
    dy = np.diff(gray, axis=0, append=gray[-1:, :])
    edges = np.sqrt(dx * dx + dy * dy) > 24
    return float(np.mean(edges[alpha > 18]))


def diagnostic(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    actual_pivot: tuple[float, int],
    expected_pivot: tuple[int, int],
    errors: list[str],
    output: Path,
) -> None:
    rgba = image.convert("RGBA")
    board = Image.new("RGB", rgba.size, (238, 238, 238))
    board.paste(rgba, (0, 0), rgba)
    draw = ImageDraw.Draw(board)
    draw.rectangle(bbox, outline=(255, 0, 0), width=2)
    ex, ey = expected_pivot
    ax, ay = actual_pivot
    draw.line((ex - 12, ey, ex + 12, ey), fill=(255, 0, 255), width=2)
    draw.line((ex, ey - 12, ex, ey + 12), fill=(255, 0, 255), width=2)
    draw.ellipse((round(ax) - 4, round(ay) - 4, round(ax) + 4, round(ay) + 4), outline=(0, 128, 255), width=2)
    draw.text((8, 8), " | ".join(errors)[:220], fill=(255, 0, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    board.save(output)


def repair_prompt(frame_name: str, errors: list[str], output: Path) -> None:
    correction = "; ".join(errors)
    text = (
        f"Frame {frame_name} failed the frame contract.\n"
        f"Correction: fix only these measured defects: {correction}.\n"
        "Preserve the canonical design, locked regions, palette, outline thickness, camera, canvas, and all unaffected regions exactly.\n"
        "Do not enlarge, recenter, crop, rescale, recolor, redesign, or add/remove equipment."
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text + "\n")


def authority_errors(contract: dict[str, object]) -> list[str]:
    authority = contract.get("authority", {})
    allowed = {"canonical-original", "native-source-derived"}
    errors: list[str] = []
    if not isinstance(authority, dict) or authority.get("sourceKind") not in allowed:
        errors.append("invalid or missing authority sourceKind")
    if not isinstance(authority, dict) or authority.get("userApproved") is not True:
        errors.append("authority/proof frame is not user-approved")
    if not isinstance(authority, dict) or authority.get("derivedFromRejectedOutput") is not False:
        errors.append("authority may be derived from rejected output")
    if contract.get("processingMode") == "faithful-extraction" and not contract.get(
        "perFrameAuthorityDirectory"
    ):
        errors.append("faithful extraction lacks per-frame authority")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text())
    contract_errors = authority_errors(contract)
    master = Image.open(contract["master"]).convert("RGBA")
    master_rgb, master_alpha = visible_rgb(master)
    master_rgba = np.asarray(master)
    expected_pivot = tuple(contract["pivot"])
    expected_size = tuple(contract["visibleSize"])
    tolerance = contract["tolerances"]
    frame_paths = sorted(args.frames.glob("frame-*.png"))
    if not frame_paths:
        raise SystemExit(f"No PNG frames found in {args.frames}")

    diagnostics = args.output / "diagnostics"
    prompts = args.output / "repair-prompts"
    records: list[dict[str, object]] = []
    failures = 0
    for path in frame_paths:
        errors: list[str] = list(contract_errors)
        image = Image.open(path).convert("RGBA")
        rgba = np.asarray(image)
        alpha = rgba[:, :, 3]
        expected_canvas = tuple(contract["canvas"])
        if image.size != expected_canvas:
            errors.append(f"canvas size {image.size} expected={expected_canvas}")
        try:
            bbox = visible_bbox(alpha)
            actual_pivot = measured_pivot(alpha, contract)
        except ValueError as error:
            errors.append(str(error))
            bbox = (0, 0, 0, 0)
            actual_pivot = (0.0, 0)
            record = {"frame": path.name, "status": "repair-needed", "errors": errors}
            records.append(record)
            failures += 1
            repair_prompt(path.name, errors, prompts / f"{path.stem}.txt")
            continue

        size = [bbox[2] - bbox[0], bbox[3] - bbox[1]]
        height_ratio = size[1] / max(1, expected_size[1])
        width_ratio = size[0] / max(1, expected_size[0])
        if abs(height_ratio - 1.0) > tolerance["visibleScaleRatio"]:
            errors.append(f"visible height scale {height_ratio:.3f}")
        if abs(width_ratio - 1.0) > tolerance["visibleScaleRatio"]:
            errors.append(f"visible width scale {width_ratio:.3f}")
        if abs(actual_pivot[0] - expected_pivot[0]) > tolerance["pivotPixels"] or abs(actual_pivot[1] - expected_pivot[1]) > tolerance["pivotPixels"]:
            errors.append(f"pivot actual=({actual_pivot[0]:.1f},{actual_pivot[1]}) expected={expected_pivot}")
        margins = {
            "left": bbox[0],
            "top": bbox[1],
            "right": image.width - bbox[2],
            "bottom": image.height - bbox[3],
        }
        if min(margins.values()) < tolerance["minimumMarginPixels"]:
            errors.append("visible pixels touch the canvas edge")

        rgb, frame_alpha = visible_rgb(image)
        mean_delta = float(np.max(np.abs(np.mean(rgb, axis=0) - np.asarray(contract["rgbMean"]))))
        if mean_delta > tolerance["paletteMeanAbsolute"]:
            errors.append(f"palette mean delta {mean_delta:.3f}")
        frame_edges = edge_density(rgba[:, :, :3].astype(np.float32), frame_alpha)
        edge_delta = abs(frame_edges - float(contract["edgeDensity"]))
        if edge_delta > tolerance["edgeDensityAbsolute"]:
            errors.append(f"edge density delta {edge_delta:.3f}")
        if image.size == master.size:
            for region in contract.get("lockedRegions", []):
                name = str(region["name"])
                x, y, width, height = [int(value) for value in region["rect"]]
                current_patch = rgba[y : y + height, x : x + width, :3].astype(np.float32) / 255.0
                master_patch = master_rgba[y : y + height, x : x + width, :3].astype(np.float32) / 255.0
                if current_patch.shape != master_patch.shape or current_patch.size == 0:
                    continue
                locked_delta = float(np.mean(np.abs(current_patch - master_patch)))
                if locked_delta > tolerance["lockedRegionMeanAbsolute"]:
                    errors.append(f"locked region {name} delta {locked_delta:.3f}")
            for region in contract.get("requiredSemanticRegions", []):
                name = str(region["name"])
                x, y, width, height = [int(value) for value in region["rect"]]
                current_alpha = rgba[y : y + height, x : x + width, 3]
                master_alpha_region = master_rgba[y : y + height, x : x + width, 3]
                if current_alpha.shape != master_alpha_region.shape or current_alpha.size == 0:
                    errors.append(f"semantic region {name} is outside the canvas")
                    continue
                protected = master_alpha_region > 18
                if contract.get("processingMode") == "faithful-extraction":
                    missing = int(np.count_nonzero(protected & (current_alpha <= 18)))
                    if missing:
                        errors.append(f"semantic region {name} missing protected pixels={missing}")
                else:
                    reference_coverage = int(np.count_nonzero(protected))
                    current_coverage = int(np.count_nonzero(current_alpha > 18))
                    ratio = current_coverage / max(1, reference_coverage)
                    minimum = float(tolerance.get("minimumSemanticCoverageRatio", 0.60))
                    if ratio < minimum:
                        errors.append(f"semantic region {name} coverage ratio={ratio:.3f}")

        record = {
            "frame": path.name,
            "status": "accepted" if not errors else "repair-needed",
            "errors": errors,
            "visibleBounds": list(bbox),
            "visibleSize": size,
            "measuredContactPivot": [round(actual_pivot[0], 2), actual_pivot[1]],
            "margins": margins,
            "paletteMeanDelta": mean_delta,
            "edgeDensity": frame_edges,
        }
        records.append(record)
        if errors:
            failures += 1
            diagnostic(image, bbox, actual_pivot, expected_pivot, errors, diagnostics / path.name)
            repair_prompt(path.name, errors, prompts / f"{path.stem}.txt")

    report = {
        "contract": str(args.contract.resolve()),
        "status": "accepted" if failures == 0 else "repair-needed",
        "failedFrameCount": failures,
        "contractErrors": contract_errors,
        "frames": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "validation-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "failedFrameCount": failures}, indent=2))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
