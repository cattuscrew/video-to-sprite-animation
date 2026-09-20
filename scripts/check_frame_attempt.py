#!/usr/bin/env python3
"""Gate one landed attempt, without waiting for the rest of the sequence.

Three things are checked here that nothing else can check:

Identity. An output is claimed to be frame N. At 24 fps neighbouring frames
differ so little that frame N's output can sit inside every per-frame limit
against parent N-1 as well, so "it matches its parent" is not evidence it is
the right frame. It must match its own parent better than either neighbour's.

Drift, against a fixed target rather than against whatever landed nearby.
A neighbour-relative check depends on arrival order and cannot be re-run
cheaply; a fixed target taken from the approved proof frame is order-free, so
a frame can be accepted the moment it lands and never revisited.

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

from validate_temporal_sequence import (
    pair_geometry_failure,
    silhouette_metrics,
    triplet_acceleration_failure,
)

DEFAULT_DRIFT_RADIUS = 0.35  # px; observed post-registration max was 0.074


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def centroid(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return np.array([0.0, 0.0])
    return np.array([float(xs.mean()), float(ys.mean())])


def alpha_disagreement(first: np.ndarray, second: np.ndarray) -> float:
    """Fraction of the union silhouette the two images disagree about."""
    a, b = first[:, :, 3] > 18, second[:, :, 3] > 18
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
    for label, digest_key in (("authority", "parentSha256"), ("source", "sourceSha256")):
        expected = job.get(digest_key)
        candidate = job.get("parentFile" if label == "authority" else "sourceFile")
        if expected and candidate and Path(candidate).is_file():
            if sha256(Path(candidate)) != expected:
                errors.append(f"{label} frame no longer matches the SHA-256 the job froze")

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

    # Order-independent drift: measured against this frame's own authority and
    # compared with a fixed approved target, never with whatever landed nearby.
    target = np.array(args.drift_target if args.drift_target else (0.0, 0.0))
    drift = centroid(output[:, :, 3] > 18) - centroid(authority[:, :, 3] > 18)
    deviation = float(np.linalg.norm(drift - target))
    check["driftPixels"] = [round(float(drift[0]), 4), round(float(drift[1]), 4)]
    check["driftTargetPixels"] = [round(float(target[0]), 4), round(float(target[1]), 4)]
    check["driftDeviationPixels"] = round(deviation, 4)
    check["driftRadiusPixels"] = args.drift_radius
    if deviation > args.drift_radius:
        errors.append(
            f"drift sits {deviation:.3f}px from the approved target, outside "
            f"{args.drift_radius}px"
        )

    # Neighbour gates, only among frames already selected. A frame that has not
    # landed is simply absent; nothing stands in for it.
    neighbour_failures: list[dict[str, object]] = []
    if not args.skip_neighbours:
        contract_path = args.run / "frame-contract.json"
        limits = {
            "maximumSilhouetteSpikeRatio": 1.8,
            "maximumVisibleAreaStepRatio": 0.03,
            "maximumBoundingBoxSizeStepPixels": 12.0,
            "maximumCentroidStepPixels": 2.0,
            "maximumBoundingBoxSizeAccelerationPixels": 16.0,
            "maximumCentroidAccelerationPixels": 1.5,
        }
        if contract_path.is_file():
            limits.update(
                {
                    key: float(value)
                    for key, value in json.loads(contract_path.read_text())
                    .get("temporalLimits", {})
                    .items()
                    if key in limits
                }
            )
        metrics = {args.frame: silhouette_metrics(output)}
        for offset in (-2, -1, 1, 2):
            neighbour = args.frame + offset
            path = selected_image(args.run, neighbour)
            if path is not None:
                metrics[neighbour] = silhouette_metrics(rgba(path))

        for left, right in ((args.frame - 1, args.frame), (args.frame, args.frame + 1)):
            if left in metrics and right in metrics:
                failure = pair_geometry_failure(
                    metrics[left], metrics[right], (left, right), limits
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
