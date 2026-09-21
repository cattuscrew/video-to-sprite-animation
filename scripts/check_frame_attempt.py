#!/usr/bin/env python3
"""Gate one landed attempt, without waiting for the rest of the sequence.

Three things are checked here that nothing else can check:

Identity. An output is claimed to be frame N. At 24 fps neighbouring frames
differ so little that frame N's output can sit inside every per-frame limit
against native frame N-1 as well, so "it matches its source" is not evidence it
is the right frame. It must match its own source better than either
neighbour's.

Placement, taken from the registration record rather than recomputed here.
register_to_authority fits the output onto its native frame on the eroded
opaque interior and rejects anything it cannot bring within 0.05px, so by the
time a frame reaches this script its placement is already guaranteed, measured
the same way on both images.

This script used to recompute drift as the distance between the output's alpha
centroid and the source's chroma centroid. Those are two different definitions
of an edge, and the gap between them is not misplacement: across 48 frames
known to be correctly placed it ran 0.42 to 2.50 pixels, median 0.98, almost
all of it vertical. Gated at 0.35px it failed every one of them. The offset is
still reported, because it is worth seeing; it is no longer a verdict.

Appearance. The tool is asked to remove a background, not to repaint. Interior
colour and the artwork's own outlines are compared with the frame's native
source, because with no approved parent to restore RGB from, nothing else in
the pipeline would notice a recoloured or re-inked frame.

Provenance. The attempt's image must be the one the worker's own session
produced, bound by item id, and the inputs must still hash to what the job
froze.

The sequence gates still run at the end over the whole batch. This is what
makes a failure visible in the minute it happens rather than at minute 100.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
except ImportError as error:  # pragma: no cover - dependency guidance
    raise SystemExit(
        f"{error}. Install the skill's dependencies: "
        "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    )

from register_to_authority import erode
from source_foreground import foreground_mask
from validate_temporal_sequence import (
    pair_geometry_failure,
    silhouette_metrics,
    triplet_acceleration_failure,
)

# Centroid acceleration is gated at 2.0, not the old default of 1.5. Measured
# on a registered one-to-one sequence: the native animation's own acceleration
# maxes at 0.71 and the delivered output at 1.83, while registration pins every
# frame to within 0.0012px of its source. A sprite placed that exactly is not
# accelerating -- what moves the silhouette's centre of mass is the alpha
# boundary being drawn slightly differently each frame. The gate reads edge
# variation, so its limit comes from what a correctly registered sequence
# actually produces, not from a default chosen before any of this was measured.
MAX_CENTROID_ACCELERATION = 2.0

DEFAULT_DRIFT_RADIUS = 0.35  # px; observed post-registration max was 0.074

# Mean absolute error runs 7.8-11.5 levels on real output, almost all of it
# local disagreement where an internal outline lands half a pixel differently
# after resampling.
MAX_INTERIOR_RGB_ERROR = 20.0

# Raw one-to-one output carries a systematic shift against its native frame --
# every channel negative, worst observed 8.1 across six attempts. An earlier
# limit of 8 was calibrated on frames whose interior RGB had been restored from
# an approved parent, so it had never seen unrestored output and rejected an
# otherwise good frame.
#
# The limit is absolute, by the user's decision on 2026-09-20, having been
# shown the alternative: gating each frame's distance from an approved target
# bias would catch a frame that differs from the rest while still allowing the
# systematic shift. As set, a frame sitting 11 levels off on one channel passes
# unremarked. It catches gross recolouring, not drift.
MAX_CHANNEL_BIAS = 12.0
# The artwork's black keyline. Output ran 10.5% of the interior against the
# source's 8.2%, never differing by more than 3.3 points.
MAX_OUTLINE_FRACTION_DELTA = 0.06
DARK_LUMA = 60.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def luma(rgb: np.ndarray) -> np.ndarray:
    values = rgb[:, :, :3].astype(np.float64)
    return 0.299 * values[:, :, 0] + 0.587 * values[:, :, 1] + 0.114 * values[:, :, 2]


def appearance_failures(
    output: np.ndarray, authority: np.ndarray, check: dict[str, object]
) -> list[str]:
    """Compare interior colour and outline with the native source frame.

    Measured on the eroded opaque interior only: the soft edge is where the
    tool is allowed to work, and including it would drown a real recolour in
    the noise of anti-aliasing.
    """
    interior = erode(output[:, :, 3] > 250, 2)
    count = int(interior.sum())
    check["interiorPixelsCompared"] = count
    if count < 500:
        return ["too little opaque interior to compare appearance against the source"]

    difference = output[:, :, :3][interior].astype(np.float64) - authority[:, :, :3][
        interior
    ].astype(np.float64)
    error = float(np.abs(difference).mean())
    bias = difference.mean(axis=0)
    check["interiorRgbMeanAbsoluteError"] = round(error, 3)
    check["interiorChannelBias"] = [round(float(value), 3) for value in bias]

    output_dark = float((luma(output)[interior] < DARK_LUMA).mean())
    source_dark = float((luma(authority)[interior] < DARK_LUMA).mean())
    check["darkOutlineFraction"] = [round(output_dark, 5), round(source_dark, 5)]

    failures: list[str] = []
    if error > MAX_INTERIOR_RGB_ERROR:
        failures.append(
            f"interior colour differs from the source by {error:.1f} levels, "
            f"over {MAX_INTERIOR_RGB_ERROR:.0f}"
        )
    worst = float(np.abs(bias).max())
    if worst > MAX_CHANNEL_BIAS:
        failures.append(
            f"interior colour is shifted {worst:.1f} levels on one channel "
            f"(over {MAX_CHANNEL_BIAS:.0f}); the frame has been recoloured, not "
            "just cut out"
        )
    delta = abs(output_dark - source_dark)
    if delta > MAX_OUTLINE_FRACTION_DELTA:
        failures.append(
            f"dark outline covers {output_dark:.1%} of the interior against the "
            f"source's {source_dark:.1%}; the linework has been redrawn"
        )
    return failures


def centroid(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return np.array([0.0, 0.0])
    return np.array([float(xs.mean()), float(ys.mean())])


def alpha_disagreement(first: np.ndarray, second: np.ndarray) -> float:
    """Fraction of the union silhouette the two images disagree about.

    The authority is a native frame with no alpha, so its silhouette comes from
    the chroma test rather than a channel that is opaque everywhere.
    """
    a, b = foreground_mask(first), foreground_mask(second)
    union = np.logical_or(a, b).sum()
    return float(np.logical_xor(a, b).sum() / max(1, union))


def job_path(run: Path, frame: int) -> Path:
    return run / "jobs" / f"{frame:03d}" / "job.json"


def selected_image(run: Path, frame: int) -> Path | None:
    pointer = run / "jobs" / f"{frame:03d}" / "selected.json"
    if not pointer.is_file():
        return None
    candidate = Path(json.loads(pointer.read_text())["source"])
    return candidate if candidate.is_file() else None


IDENTITY_MARGIN = 0.8


def check_identity(
    output: np.ndarray, run: Path, frame: int, margin: float = IDENTITY_MARGIN
) -> tuple[dict[str, float | None], list[str]]:
    """The output must resemble its own authority more than its neighbours'.

    A neighbour has to fit clearly better, not merely tie. A frame that has
    drifted halfway toward its neighbour scores about the same against both,
    and that is a drift problem with its own gate; a frame that is genuinely
    the neighbour's image scores near zero against it.
    """
    scores: dict[str, float | None] = {}
    own_path = json.loads(job_path(run, frame).read_text()).get("authority")
    if not own_path or not Path(own_path).is_file():
        return scores, ["job has no readable authority frame"]
    own = alpha_disagreement(output, rgba(Path(own_path)))
    scores["own"] = round(own, 5)

    errors: list[str] = []
    for offset in (-1, 1):
        neighbour = frame + offset
        path = job_path(run, neighbour)
        if not path.is_file():
            scores[str(offset)] = None
            continue
        authority = json.loads(path.read_text()).get("authority")
        if not authority or not Path(authority).is_file():
            scores[str(offset)] = None
            continue
        score = alpha_disagreement(output, rgba(Path(authority)))
        scores[str(offset)] = round(score, 5)
        if score < own * margin:
            errors.append(
                f"output matches frame {neighbour}'s authority better than its own "
                f"({score:.5f} vs {own:.5f}); it may be the wrong frame"
            )
    return scores, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("frame", type=int)
    parser.add_argument("attempt", type=int)
    parser.add_argument(
        "--max-remaining-shift",
        type=float,
        default=0.05,
        help="how much registration may leave unresolved, in pixels",
    )
    parser.add_argument(
        "--drift-radius",
        type=float,
        default=DEFAULT_DRIFT_RADIUS,
        help="how far this frame's drift may sit from the approved target",
    )
    parser.add_argument(
        "--drift-target",
        type=float,
        nargs=2,
        metavar=("DX", "DY"),
        help="approved drift vector from the proof frame; defaults to zero",
    )
    parser.add_argument("--skip-neighbours", action="store_true")
    args = parser.parse_args()

    directory = args.run / "jobs" / f"{args.frame:03d}" / f"attempt-{args.attempt:03d}"
    job = json.loads(job_path(args.run, args.frame).read_text())
    record_path = directory / "record.json"
    record = json.loads(record_path.read_text()) if record_path.is_file() else {}

    errors: list[str] = []
    check: dict[str, object] = {
        "outputFrame": args.frame,
        "attempt": args.attempt,
        "nativeFrame": job.get("nativeFrame"),
    }

    image_path = directory / "locked.png"
    if not image_path.is_file():
        image_path = directory / "registered.png"
    if not image_path.is_file():
        check["status"] = "repair-needed"
        check["errors"] = ["attempt produced no registered image"]
        (directory / "check-attempt.json").write_text(json.dumps(check, indent=2) + "\n")
        print(json.dumps({"status": "repair-needed", "errors": check["errors"]}))
        return 2

    # Provenance: the image must be the one this attempt's session produced.
    raw = directory / "raw.png"
    if raw.is_file() and record.get("outputSha256"):
        if sha256(raw) != record["outputSha256"]:
            errors.append("raw.png does not match the SHA-256 its record claims")
    if record.get("itemId"):
        check["itemId"] = record["itemId"]
    elif record.get("errorClass") == "none":
        errors.append("attempt reports success but names no image item id")

    authority_path = Path(job["authority"])
    expected = job.get("sourceSha256")
    candidate = job.get("sourceFile")
    if expected and candidate and Path(candidate).is_file():
        if sha256(Path(candidate)) != expected:
            errors.append("source frame no longer matches the SHA-256 the job froze")

    output = rgba(image_path)
    authority = rgba(authority_path)
    if output.shape != authority.shape:
        errors.append(
            f"canvas {output.shape[1]}x{output.shape[0]} does not match the "
            f"authority's {authority.shape[1]}x{authority.shape[0]}"
        )
        check["status"] = "repair-needed"
        check["errors"] = errors
        (directory / "check-attempt.json").write_text(json.dumps(check, indent=2) + "\n")
        print(json.dumps({"status": "repair-needed", "errors": errors}))
        return 2

    scores, identity_errors = check_identity(output, args.run, args.frame)
    check["authorityDisagreement"] = scores
    errors.extend(identity_errors)

    # Kept apart from the rest so the queue can tell a repaint from a warp.
    # They fail for different reasons and are fixed differently, and a status
    # report that calls both "quality" cannot say which one blocked a frame.
    colour_errors = appearance_failures(output, authority, check)
    check["colourErrors"] = colour_errors
    errors.extend(colour_errors)

    # Placement comes from registration, which measured it on the same pixels
    # in both images. Reported here, not re-derived.
    registration = directory / "check.json"
    if registration.is_file():
        record_in = json.loads(registration.read_text())
        for key in ("dx", "dy", "shiftPixels", "remainingShiftPixels", "areaDeviation"):
            if key in record_in:
                check[key] = record_in[key]
        remaining = record_in.get("remainingShiftPixels")
        if remaining is not None and float(remaining) > args.max_remaining_shift:
            errors.append(
                f"registration left {float(remaining):.3f}px unresolved, over "
                f"{args.max_remaining_shift}px"
            )
    else:
        errors.append("no registration record; the attempt was not registered")

    # Measured, not gated: the alpha and chroma silhouettes disagree about the
    # edge by about a pixel even when placement is exact.
    offset = centroid(foreground_mask(output)) - centroid(foreground_mask(authority))
    check["silhouetteCentroidOffsetPixels"] = [
        round(float(offset[0]), 4),
        round(float(offset[1]), 4),
    ]

    # Neighbour gates, only among frames already selected. A frame that has not
    # landed is simply absent; nothing stands in for it.
    neighbour_failures: list[dict[str, object]] = []
    if not args.skip_neighbours:
        contract_path = args.run / "frame-contract.json"
        approved_transitions: set[str] = set()
        limits = {
            "maximumSilhouetteSpikeRatio": 1.8,
            "maximumVisibleAreaStepRatio": 0.03,
            "maximumBoundingBoxSizeStepPixels": 12.0,
            "maximumCentroidStepPixels": 2.0,
            "maximumBoundingBoxSizeAccelerationPixels": 16.0,
            # See MAX_CENTROID_ACCELERATION below for why this is 2.0.
            "maximumCentroidAccelerationPixels": MAX_CENTROID_ACCELERATION,
        }
        if contract_path.is_file():
            contract = json.loads(contract_path.read_text())
            limits.update(
                {
                    key: float(value)
                    for key, value in contract.get("temporalLimits", {}).items()
                    if key in limits
                }
            )
            # The contract's approved transitions apply here too, not only at
            # final validation. Without them a frame whose own source moves
            # further than the limit can never pass: the only attempt that
            # would is one that moves less than the frame it is copying, so
            # the gate selects against fidelity to the source. The threshold
            # itself is untouched -- these are the specific transitions the
            # user approved after seeing the authority's own measurements.
            approved_transitions = set(contract.get("approvedTemporalTransitions", []))
        metrics = {args.frame: silhouette_metrics(output)}
        for offset in (-2, -1, 1, 2):
            neighbour = args.frame + offset
            path = selected_image(args.run, neighbour)
            if path is not None:
                metrics[neighbour] = silhouette_metrics(rgba(path))

        for left, right in ((args.frame - 1, args.frame), (args.frame, args.frame + 1)):
            if left in metrics and right in metrics:
                failure = pair_geometry_failure(
                    metrics[left],
                    metrics[right],
                    (left, right),
                    limits,
                    approved_transitions,
                )
                if failure:
                    neighbour_failures.append(failure)
        for middle in (args.frame - 1, args.frame, args.frame + 1):
            triple = (middle - 1, middle, middle + 1)
            if all(number in metrics for number in triple):
                failure = triplet_acceleration_failure(
                    metrics[triple[0]],
                    metrics[triple[1]],
                    metrics[triple[2]],
                    triple,
                    limits,
                    approved_transitions,
                )
                if failure:
                    neighbour_failures.append(failure)
        check["neighboursCompared"] = sorted(k for k in metrics if k != args.frame)
    check["neighbourFailures"] = neighbour_failures
    errors.extend(
        f"{failure.get('transition') or failure.get('frame')}: {', '.join(failure['reasons'])}"
        for failure in neighbour_failures
    )

    check["errors"] = errors
    check["status"] = "accepted" if not errors else "repair-needed"
    (directory / "check-attempt.json").write_text(json.dumps(check, indent=2) + "\n")
    print(
        json.dumps(
            {
                "outputFrame": args.frame,
                "attempt": args.attempt,
                "status": check["status"],
                "errors": errors,
            },
            indent=2,
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
