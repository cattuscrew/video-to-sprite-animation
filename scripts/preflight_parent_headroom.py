#!/usr/bin/env python3
"""Measure how much temporal budget the authority sequence has already spent.

A repaired frame is gated on acceleration across its neighbours, but part of
that acceleration belongs to the approved sequence itself. Where an authority
transition already sits near the limit, no achievable per-frame accuracy will
keep the repair inside it, and the run will fail at the end for a reason that
was fixed before the first image call.

Run this before generation. Transitions with little headroom are a question for
the user -- list them in the contract's approvedTemporalTransitions or accept a
different authority -- never a reason to relax the limit for the whole batch.
"""

from __future__ import annotations

import argparse
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
)


def load_authority_frames(manifest: dict, manifest_path: Path) -> list[tuple[int, Path]]:
    """Frames in manifest order, never in glob order."""
    if manifest.get("parentFramesDirectory"):
        directory = Path(manifest["parentFramesDirectory"])
        key = "parentFile"
    else:
        directory = Path(manifest["sourceFramesDirectory"])
        key = "sourceFile"
    if not directory.is_absolute():
        directory = (manifest_path.parent / directory).resolve()
    return [
        (int(record["outputFrame"]), directory / str(record[key]))
        for record in manifest["frameMapping"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="parent or source frame manifest")
    parser.add_argument("contract", type=Path, help="frame contract holding temporalLimits")
    parser.add_argument("output", type=Path, help="headroom report JSON")
    parser.add_argument(
        "--min-headroom",
        type=float,
        default=0.3,
        help="flag transitions leaving less than this many pixels of acceleration budget",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    contract = json.loads(args.contract.read_text())
    limits_source = contract.get("temporalLimits", {})
    limits = {
        "maximumSilhouetteSpikeRatio": float(limits_source.get("maximumSilhouetteSpikeRatio", 1.8)),
        "maximumVisibleAreaStepRatio": float(limits_source.get("maximumVisibleAreaStepRatio", 0.03)),
        "maximumBoundingBoxSizeStepPixels": float(limits_source.get("maximumBoundingBoxSizeStepPixels", 12.0)),
        "maximumCentroidStepPixels": float(limits_source.get("maximumCentroidStepPixels", 2.0)),
        "maximumBoundingBoxSizeAccelerationPixels": float(limits_source.get("maximumBoundingBoxSizeAccelerationPixels", 16.0)),
        "maximumCentroidAccelerationPixels": float(limits_source.get("maximumCentroidAccelerationPixels", 1.5)),
    }

    entries = load_authority_frames(manifest, args.manifest)
    missing = [str(path) for _, path in entries if not path.is_file()]
    if missing:
        raise SystemExit(f"authority frames missing: {missing[:5]}")

    silhouettes = [
        silhouette_metrics(np.asarray(Image.open(path).convert("RGBA")))
        for _, path in entries
    ]
    numbers = [number for number, _ in entries]

    accel_limit = limits["maximumCentroidAccelerationPixels"]
    step_limit = limits["maximumCentroidStepPixels"]

    transitions = []
    for index in range(len(silhouettes) - 1):
        first, second = silhouettes[index], silhouettes[index + 1]
        step = float(
            np.linalg.norm(
                np.asarray(second["centroid"]) - np.asarray(first["centroid"])
            )
        )
        transitions.append(
            {
                "transition": f"{numbers[index]}->{numbers[index + 1]}",
                "centroidStepPixels": round(step, 4),
                "headroomPixels": round(step_limit - step, 4),
            }
        )

    triplets = []
    for index in range(1, len(silhouettes) - 1):
        centroids = [
            np.asarray(silhouettes[item]["centroid"], dtype=np.float64)
            for item in (index - 1, index, index + 1)
        ]
        acceleration = float(
            np.linalg.norm(centroids[2] - 2 * centroids[1] + centroids[0])
        )
        triplets.append(
            {
                "frame": numbers[index],
                "centroidAccelerationPixels": round(acceleration, 4),
                "headroomPixels": round(accel_limit - acceleration, 4),
            }
        )

    # Does the authority pass its own gates?
    own_failures = [
        failure
        for index in range(len(silhouettes) - 1)
        if (
            failure := pair_geometry_failure(
                silhouettes[index],
                silhouettes[index + 1],
                (numbers[index], numbers[index + 1]),
                limits,
            )
        )
    ]

    tight_transitions = sorted(
        (t for t in transitions if t["headroomPixels"] < args.min_headroom),
        key=lambda item: item["headroomPixels"],
    )
    tight_triplets = sorted(
        (t for t in triplets if t["headroomPixels"] < args.min_headroom),
        key=lambda item: item["headroomPixels"],
    )

    report = {
        "status": "accepted" if not own_failures else "repair-needed",
        "authorityManifest": str(args.manifest.resolve()),
        "frameCount": len(silhouettes),
        "limits": {
            "maximumCentroidStepPixels": step_limit,
            "maximumCentroidAccelerationPixels": accel_limit,
        },
        "minHeadroomPixels": args.min_headroom,
        "authorityOwnFailures": own_failures,
        "tightTransitions": tight_transitions,
        "tightTriplets": tight_triplets,
        "suggestedApprovedTemporalTransitions": sorted(
            {t["transition"] for t in tight_transitions}
            | {
                f"{t['frame'] - 1}->{t['frame']}"
                for t in tight_triplets
            }
        ),
        "transitions": transitions,
        "triplets": triplets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")

    print(
        json.dumps(
            {
                "status": report["status"],
                "frameCount": report["frameCount"],
                "tightTransitions": len(tight_transitions),
                "tightTriplets": len(tight_triplets),
                "worst": (tight_triplets or tight_transitions or [None])[0],
            },
            indent=2,
        )
    )
    return 0 if not own_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
