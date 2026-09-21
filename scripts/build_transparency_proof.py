#!/usr/bin/env python3
"""Render the transparency proof the step-7 gate is judged on.

Every other evidence artifact in this workflow has a script behind it; this one
did not. The gate said to show the proof on checkerboard, white and black with
magnified fragile-region crops, and then left the rendering to whoever happened
to be running -- so in practice the batch was approved off a single checkerboard
view, and a contaminated or ragged edge is close to invisible against a mid-tone
check pattern. The gate passed on evidence that could not show the defect it
exists to catch.

This renders the three backgrounds and the crops at 100% and 4x, and writes a
report the delivery gate requires. It renders; it does not judge. `userApproved`
stays false and the report stays `pending-review` until `--accept` records a
reviewer who actually looked -- the same shape as the pose and visual-QA
reports, for the same reason.
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

from build_pose_correspondence import (
    FRAGILE_REGIONS,
    checkerboard,
    on_black,
    on_checker,
    sha256,
    visible_box,
)

BACKGROUNDS = ("checkerboard", "white", "black")


def on_solid(path: Path, colour: tuple[int, int, int]) -> Image.Image:
    sprite = Image.open(path).convert("RGBA")
    board = Image.new("RGBA", sprite.size, (*colour, 255))
    board.alpha_composite(sprite)
    return board.convert("RGB")


def background_proof(proof: Path, source: Path | None, native_frame: int | None) -> Image.Image:
    """The proof at full resolution on each background, beside its own source.

    Full resolution because a reduced-scale view resamples the edge away, and
    the edge is the whole subject. The source panel is here so the question is
    "did this lose anything" rather than "does this look fine".
    """
    panels: list[tuple[str, Image.Image]] = []
    if source is not None and source.is_file():
        label = f"native {native_frame}" if native_frame is not None else "native source"
        panels.append((label, Image.open(source).convert("RGB")))
    panels.append(("checkerboard", on_checker(proof)))
    panels.append(("white", on_solid(proof, (255, 255, 255))))
    panels.append(("black", on_black(proof)))

    label_height = 24
    height = max(panel.height for _, panel in panels)
    sheet = Image.new(
        "RGB", (sum(p.width for _, p in panels), height + label_height), (24, 24, 24)
    )
    draw = ImageDraw.Draw(sheet)
    offset = 0
    for label, panel in panels:
        sheet.paste(panel, (offset, label_height))
        draw.text((offset + 6, 7), label, fill="white")
        offset += panel.width
    return sheet


def fragile_crops(
    proof: Path, source: Path | None, zoom: float, native_frame: int | None
) -> Image.Image:
    """One column per fragile region: source, on checkerboard, on black.

    At 4x a two-pixel halo is plain and at 100% it is not, which is why the gate
    asks for both rather than letting one stand in for the other. Regions come
    from quality-gates.md: the gaps that must stay open and the boundaries a
    matte fails at first.
    """
    left, top, right, bottom = visible_box(proof)
    width, height = right - left, bottom - top
    rows: list[tuple[str, Image.Image]] = []
    if source is not None and source.is_file():
        rows.append(("native source", Image.open(source).convert("RGB")))
    rows.append(("on checkerboard", on_checker(proof)))
    rows.append(("on black", on_black(proof)))

    label_height = 16
    columns: list[tuple[str, list[Image.Image]]] = []
    for name, (x0, y0, x1, y1) in FRAGILE_REGIONS.items():
        box = (
            left + int(x0 * width),
            top + int(y0 * height),
            left + int(x1 * width),
            top + int(y1 * height),
        )
        tiles = []
        for _, image in rows:
            patch = image.crop(box)
            # NEAREST: magnifying with a smoothing filter invents the soft edge
            # the reviewer is here to look for.
            patch = patch.resize(
                (max(1, int(patch.width * zoom)), max(1, int(patch.height * zoom))),
                Image.NEAREST,
            )
            tiles.append(patch)
        columns.append((name, tiles))

    row_height = max(tile.height for _, tiles in columns for tile in tiles)
    sheet = Image.new(
        "RGB",
        (
            sum(tiles[0].width for _, tiles in columns),
            label_height * (2 + len(rows)) + row_height * len(rows),
        ),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(sheet)
    frame_label = f"native {native_frame}   " if native_frame is not None else ""
    draw.text((4, 3), f"{frame_label}transparency proof at {zoom:g}x", fill="white")
    x = 0
    for name, tiles in columns:
        draw.text((x + 4, label_height + 1), name, fill="#9ad")
        # Each row carries its own caption above its tiles; without the offset
        # the first one lands on the region name and both become unreadable.
        for row, ((row_label, _), tile) in enumerate(zip(rows, tiles)):
            y = label_height * 2 + row * (row_height + label_height)
            draw.text((x + 4, y + 1), row_label, fill="#888")
            sheet.paste(tile, (x, y + label_height))
        x += tiles[0].width
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proof", type=Path, help="the transparent proof frame")
    parser.add_argument("output", type=Path, help="directory for the artifacts and report")
    parser.add_argument(
        "--source",
        type=Path,
        help="the native frame this proof was edited from; shown beside it",
    )
    parser.add_argument("--native-frame", type=int, help="native frame number, for labels")
    parser.add_argument(
        "--zoom",
        type=float,
        default=4.0,
        help="magnification for the enlarged crop sheet; the 100%% sheet is always rendered",
    )
    parser.add_argument(
        "--accept",
        metavar="REVIEWER",
        help=(
            "record that a reviewer inspected all three backgrounds and both crop "
            "scales and approved the transparency. Only pass this after actually "
            "looking at them."
        ),
    )
    args = parser.parse_args()

    if not args.proof.is_file():
        raise SystemExit(f"proof frame does not exist: {args.proof}")
    if args.source is not None and not args.source.is_file():
        raise SystemExit(f"source frame does not exist: {args.source}")

    args.output.mkdir(parents=True, exist_ok=True)
    proof_path = args.output / "proof-bg-removal.png"
    background_proof(args.proof, args.source, args.native_frame).save(proof_path)
    crops_100 = args.output / "proof-fragile-crops-100.png"
    fragile_crops(args.proof, args.source, 1.0, args.native_frame).save(crops_100)
    crops_zoom = args.output / f"proof-fragile-crops-{args.zoom:g}x.png"
    fragile_crops(args.proof, args.source, args.zoom, args.native_frame).save(crops_zoom)

    report = {
        "status": "accepted" if args.accept else "pending-review",
        "userApproved": bool(args.accept),
        "reviewer": args.accept or None,
        # Named so the delivery gate can tell an approval taken on all three
        # backgrounds from one taken on whichever was rendered.
        "backgroundsRendered": list(BACKGROUNDS),
        "cropScales": [1.0, float(args.zoom)],
        "fragileRegions": sorted(FRAGILE_REGIONS),
        "proofFrame": {"path": str(args.proof.resolve()), "sha256": sha256(args.proof)},
        "sourceFrame": (
            {
                "path": str(args.source.resolve()),
                "sha256": sha256(args.source),
                "nativeFrame": args.native_frame,
            }
            if args.source is not None
            else None
        ),
        "artifacts": {
            "backgroundProof": str(proof_path.resolve()),
            "fragileCrops100": str(crops_100.resolve()),
            "fragileCropsMagnified": str(crops_zoom.resolve()),
        },
    }
    destination = args.output / "transparency-proof-report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "backgroundProof": str(proof_path),
                "fragileCrops": [str(crops_100), str(crops_zoom)],
                "report": str(destination),
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
