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


def on_black(path: Path) -> Image.Image:
    """The view a coloured or ragged rim actually shows up in."""
    sprite = Image.open(path).convert("RGBA")
    board = Image.new("RGBA", sprite.size, (0, 0, 0, 255))
    board.alpha_composite(sprite)
    return board.convert("RGB")


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


FRAGILE_REGIONS = {
    # Fractions of the visible bounding box. quality-gates.md names these as the
    # places a repair fails first: gaps that should stay open, thin geometry, and
    # boundaries between materials.
    "head-chin-collar": (0.20, 0.00, 0.85, 0.32),
    "hands-and-weapon": (0.00, 0.35, 0.55, 0.70),
    "equipment-edge": (0.50, 0.30, 1.00, 0.70),
    "boots-groundline": (0.15, 0.78, 0.90, 1.00),
}


def visible_box(path: Path) -> tuple[int, int, int, int]:
    alpha = Image.open(path).convert("RGBA").getchannel("A")
    box = alpha.getbbox()
    return box or (0, 0, alpha.width, alpha.height)


def fragile_strip(
    source: Path, output: Path, frame: int, zoom: float = 1.6
) -> Image.Image:
    """Native source above, output below, one column per fragile region.

    Magnified, because a halo two pixels wide is invisible at 100% and obvious
    when enlarged. Every tile is the same size and the two rows line up, so the
    eye compares the pair rather than hunting for it.

    The output is shown on black, not on the checkerboard: a coloured or ragged
    rim disappears against a mid-tone check pattern and is plain against black.
    """
    left, top, right, bottom = visible_box(output)
    width, height = right - left, bottom - top
    source_image = Image.open(source).convert("RGB")
    output_image = on_black(output)

    columns: list[tuple[str, Image.Image, Image.Image]] = []
    for name, (x0, y0, x1, y1) in FRAGILE_REGIONS.items():
        box = (
            left + int(x0 * width),
            top + int(y0 * height),
            left + int(x1 * width),
            top + int(y1 * height),
        )
        pair = []
        for image in (source_image, output_image):
            patch = image.crop(box)
            patch = patch.resize(
                (max(1, int(patch.width * zoom)), max(1, int(patch.height * zoom))),
                Image.NEAREST,
            )
            pair.append(patch)
        columns.append((name, pair[0], pair[1]))

    label_height = 16
    row_height = max(c[1].height for c in columns)
    sheet = Image.new(
        "RGB",
        (sum(c[1].width for c in columns), label_height * 3 + row_height * 2),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (4, 3),
        f"frame {frame:03d}   native source (upper) / output on black (lower)",
        fill="white",
    )
    x = 0
    for name, source_tile, output_tile in columns:
        draw.text((x + 4, label_height + 1), name, fill="#9ad")
        sheet.paste(source_tile, (x, label_height * 2))
        sheet.paste(output_tile, (x, label_height * 2 + row_height + label_height))
        x += source_tile.width
    return sheet


def region_strip(
    frames: list[tuple[int, Path]], region: str, zoom: float = 1.4, per_row: int = 6
) -> Image.Image:
    """One fragile region across the whole sequence.

    A redrawn eye, a weapon that changed angle or a gap that filled in is hard
    to see against the frame's own source, where the difference is small and
    expected. Against the frames either side it is obvious: everything moves
    smoothly except the one that does not. This is the view the numeric gates
    cannot give, because they measure silhouettes and not what is drawn inside.
    """
    x0, y0, x1, y1 = FRAGILE_REGIONS[region]
    tiles: list[tuple[int, Image.Image]] = []
    for number, path in frames:
        image = on_checker(path)
        left, top, right, bottom = visible_box(path)
        width, height = right - left, bottom - top
        patch = image.crop(
            (
                left + int(x0 * width),
                top + int(y0 * height),
                left + int(x1 * width),
                top + int(y1 * height),
            )
        )
        patch = patch.resize(
            (max(1, int(patch.width * zoom)), max(1, int(patch.height * zoom))),
            Image.NEAREST,
        )
        tiles.append((number, patch))

    tile_width = max(t.width for _, t in tiles)
    tile_height = max(t.height for _, t in tiles)
    label = 15
    rows = (len(tiles) + per_row - 1) // per_row
    sheet = Image.new(
        "RGB",
        (tile_width * min(per_row, len(tiles)), label + rows * (tile_height + label)),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((4, 2), f"{region} across the sequence", fill="white")
    for position, (number, patch) in enumerate(tiles):
        row, column = divmod(position, per_row)
        x = column * tile_width
        y = label + row * (tile_height + label)
        draw.text((x + 3, y + 1), f"{number:03d}", fill="#9ad")
        sheet.paste(patch, (x, y + label))
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path, help="directory for comparisons and the report")
    parser.add_argument(
        "--fragile-crops",
        action="store_true",
        help="also render 4x crops of the fragile regions, source over output",
    )
    parser.add_argument(
        "--region-strips",
        action="store_true",
        help="render each fragile region across the whole sequence, for spotting "
        "the one frame that does not move like its neighbours",
    )
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
        panels.append((f"output {index:03d}", on_checker(output_path)))
        panels.append((f"output {index:03d} on black", on_black(output_path)))

        artifact = comparisons / f"frame-{index:03d}.png"
        comparison(panels, artifact)
        if args.fragile_crops and source_path.is_file():
            strip = fragile_strip(source_path, output_path, index)
            strip_path = args.output / "fragile" / f"frame-{index:03d}.png"
            strip_path.parent.mkdir(parents=True, exist_ok=True)
            strip.save(strip_path)

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
        records.append(entry)

    if args.region_strips:
        landed = [
            (int(r["outputFrame"]), args.frames / str(r.get("outputFile") or f"frame-{int(r['outputFrame']):03d}.png"))
            for r in manifest.get("frameMapping", [])
            if (args.frames / str(r.get("outputFile") or f"frame-{int(r['outputFrame']):03d}.png")).is_file()
        ]
        strips = args.output / "region-strips"
        strips.mkdir(parents=True, exist_ok=True)
        for region in FRAGILE_REGIONS:
            region_strip(landed, region).save(strips / f"{region}.png")

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
