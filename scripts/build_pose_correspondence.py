#!/usr/bin/env python3
"""Prepare the per-frame pose review: the bindings, and the picture to judge on.

Source correspondence will not pass without a pose report that binds every
output to its native frame by SHA-256 and links the comparison it was judged
from. Nothing produced one, so the report had to be written by hand -- which
means the bindings were typed from memory and the artifact links pointed at
whatever happened to exist.

Everything mechanical is filled in here: the native frame, both digests, the
rendered comparison. Every judgement is left false. A reviewer opens the
comparisons and sets them, per frame, and `--accept` records who did.

The judgements this report carries cannot be computed. Whether a silhouette
survived, whether the eyes are still two dots and not three, whether the sword
is at the same angle -- a checksum cannot see any of it, which is why the gate
asks a reviewer and not a script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as error:  # pragma: no cover - dependency guidance
    raise SystemExit(
        f"{error}. Install the skill's dependencies: "
        "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    )

JUDGEMENTS = (
    "sourcePosePreserved",
    "silhouettePreserved",
    "topologyPreserved",
    "equipmentGeometryPreserved",
    "eyeStatePreserved",
    "negativeSpacesPreserved",
    "noSubstitutedPose",
    "noMasterWarp",
)

PARENT_JUDGEMENTS = ("parentGeometryPreserved", "parentForegroundPreserved")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkerboard(size: tuple[int, int], tile: int = 16) -> Image.Image:
    board = Image.new("RGBA", size, (235, 235, 235, 255))
    draw = ImageDraw.Draw(board)
    for y in range(0, size[1], tile):
        for x in range(0, size[0], tile):
            if (x // tile + y // tile) % 2:
                draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(200, 200, 200, 255))
    return board


def on_checker(path: Path) -> Image.Image:
    sprite = Image.open(path).convert("RGBA")
    board = checkerboard(sprite.size)
    board.alpha_composite(sprite)
    return board.convert("RGB")


def comparison(panels: list[tuple[str, Image.Image]], destination: Path) -> None:
    """Full resolution, side by side. Reduced scale hides exactly the defects
    this review exists to catch."""
    height = max(panel.height for _, panel in panels)
    sheet = Image.new("RGB", (sum(p.width for _, p in panels), height + 24), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    offset = 0
    for label, panel in panels:
        sheet.paste(panel, (offset, 24))
        draw.text((offset + 6, 7), label, fill="white")
        offset += panel.width
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path, help="directory for comparisons and the report")
    parser.add_argument("--parent-frame-manifest", type=Path)
    parser.add_argument(
        "--accept",
        metavar="REVIEWER",
        help=(
            "record that a reviewer inspected the comparisons and accepted them. "
            "Only pass this after actually looking at them."
        ),
    )
    parser.add_argument(
        "--accept-frames",
        help=(
            "comma-separated frames or ranges (e.g. 1-8,12) this reviewer looked "
            "at. Without it --accept covers every frame. Frames left out stay "
            "pending, so a partial review is recorded as a partial review."
        ),
    )
    args = parser.parse_args()

    reviewed: set[int] | None = None
    if args.accept_frames:
        reviewed = set()
        for part in args.accept_frames.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                reviewed.update(range(int(start), int(end) + 1))
            elif part:
                reviewed.add(int(part))

    def accepted(frame: int) -> bool:
        if not args.accept:
            return False
        return reviewed is None or frame in reviewed

    manifest = json.loads(args.source_manifest.read_text())
    source_dir = Path(manifest["sourceFramesDirectory"])
    parents: dict[int, Path] = {}
    if args.parent_frame_manifest:
        parent_manifest = json.loads(args.parent_frame_manifest.read_text())
        parent_dir = Path(parent_manifest["parentFramesDirectory"])
        parents = {
            int(r["outputFrame"]): parent_dir / str(r["parentFile"])
            for r in parent_manifest.get("frameMapping", [])
        }

    comparisons = args.output / "comparisons"
    records: list[dict[str, object]] = []
    missing: list[int] = []

    for record in manifest.get("frameMapping", []):
        index = int(record["outputFrame"])
        output_path = args.frames / str(record.get("outputFile") or f"frame-{index:03d}.png")
        if not output_path.is_file():
            missing.append(index)
            records.append(
                {
                    "outputFrame": index,
                    "nativeFrame": record.get("nativeFrame"),
                    "status": "user-visible-blocked",
                    "errors": ["missing output frame"],
                }
            )
            continue

        source_path = source_dir / str(record["sourceFile"])
        panels: list[tuple[str, Image.Image]] = []
        if source_path.is_file():
            panels.append((f"native {record.get('nativeFrame')}", Image.open(source_path).convert("RGB")))
        parent_path = parents.get(index)
        if parent_path is not None and parent_path.is_file():
            panels.append((f"parent {index:03d}", on_checker(parent_path)))
        panels.append((f"output {index:03d}", on_checker(output_path)))

        artifact = comparisons / f"frame-{index:03d}.png"
        comparison(panels, artifact)

        entry: dict[str, object] = {
            "outputFrame": index,
            "nativeFrame": record.get("nativeFrame"),
            "sourceFile": record.get("sourceFile"),
            "sourceSha256": sha256(source_path) if source_path.is_file() else None,
            "outputSha256": sha256(output_path),
            "status": "accepted" if accepted(index) else "pending-review",
            "sourceOutputComparisonArtifact": str(artifact.relative_to(args.output)),
            # A checksum cannot see a redrawn eye. These are for a reviewer.
            **{key: accepted(index) for key in JUDGEMENTS},
        }
        if parent_path is not None and parent_path.is_file():
            entry["parentSha256"] = sha256(parent_path)
            entry["parentOutputComparisonArtifact"] = str(artifact.relative_to(args.output))
            entry.update({key: accepted(index) for key in PARENT_JUDGEMENTS})
        records.append(entry)

    pending = [r["outputFrame"] for r in records if r["status"] != "accepted"]
    report = {
        "status": "accepted" if (args.accept and not missing and not pending) else "pending-review",
        "pendingFrames": pending,
        "reviewMethod": "full-frame-source-output-comparison",
        "reviewer": args.accept or None,
        "frameCount": len(records),
        "missingFrames": missing,
        "comparisonsDirectory": str(comparisons.relative_to(args.output)),
        "frames": records,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / "pose-correspondence-report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "frameCount": report["frameCount"],
                "missingFrames": missing,
                "comparisons": str(comparisons),
                "report": str(destination),
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
