#!/usr/bin/env python3
"""Normalize transparent sprite frames to one root pivot and build QA artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as error:
    raise SystemExit("This script requires Pillow and NumPy") from error


def parse_pair(value: str) -> tuple[int, int]:
    parts = [int(part.strip()) for part in value.lower().replace("x", ",").split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected two integers, such as 512x512 or 256,492")
    return parts[0], parts[1]


def visible_bbox(image: Image.Image, threshold: int = 18) -> tuple[int, int, int, int]:
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.nonzero(alpha > threshold)
    if len(xs) == 0:
        raise ValueError("frame has no visible pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def contact_pivot(image: Image.Image, threshold: int = 18) -> tuple[float, int]:
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.nonzero(alpha > threshold)
    if len(xs) == 0:
        raise ValueError("frame has no visible pixels")
    bottom = int(ys.max())
    contact_x = xs[ys >= bottom - 8]
    return float(contact_x.min() + contact_x.max()) / 2.0, bottom


def clean_alpha(image: Image.Image) -> tuple[Image.Image, int]:
    rgba = np.array(image.convert("RGBA"), copy=True)
    alpha = rgba[:, :, 3]
    invisible = alpha < 5
    contaminated = int(np.count_nonzero(invisible & np.any(rgba[:, :, :3] != 0, axis=2)))
    rgba[invisible, :3] = 0
    rgba[invisible, 3] = 0
    rgba[alpha > 251, 3] = 255
    return Image.fromarray(rgba, "RGBA"), contaminated


def checkerboard(size: tuple[int, int], cell: int = 16) -> Image.Image:
    board = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(board)
    colors = ((238, 238, 238), (210, 210, 210))
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=colors[(x // cell + y // cell) % 2])
    return board


def solid_contact_sheet(
    frames: list[Image.Image],
    size: tuple[int, int],
    background: tuple[int, int, int],
    output: Path,
) -> None:
    columns = math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / columns)
    thumb_width = 256
    thumb_height = round(thumb_width * size[1] / size[0])
    contact = Image.new("RGB", (columns * thumb_width, rows * thumb_height), background)
    draw = ImageDraw.Draw(contact)
    label_color = (255, 255, 255) if sum(background) < 384 else (0, 0, 0)
    for index, frame in enumerate(frames):
        thumb = frame.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_width
        y = (index // columns) * thumb_height
        contact.paste(thumb, (x, y), thumb)
        draw.text((x + 8, y + 8), f"{index + 1:03d}", fill=label_color)
    contact.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--master", type=Path, help="Canonical master; defaults to first input PNG")
    parser.add_argument("--canvas", type=parse_pair, default=(512, 512))
    parser.add_argument("--pivot", type=parse_pair, help="Target x,y; defaults to bottom-center with 20px margin")
    parser.add_argument("--fit-height", type=int, help="Visible master height on final canvas")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--order", help="Comma-separated 1-based playback frame numbers")
    args = parser.parse_args()

    files = sorted(path for path in args.input_dir.glob("*.png") if path.is_file())
    if not files:
        raise SystemExit(f"No PNG frames found in {args.input_dir}")
    master_path = args.master or files[0]
    if not master_path.is_file():
        raise SystemExit(f"Master not found: {master_path}")

    canvas_width, canvas_height = args.canvas
    target_pivot = args.pivot or (canvas_width // 2, canvas_height - 20)
    fit_height = args.fit_height or round(canvas_height * 0.90)

    master = Image.open(master_path).convert("RGBA")
    master_bbox = visible_bbox(master)
    master_visible_height = master_bbox[3] - master_bbox[1]
    scale = fit_height / master_visible_height
    master_size = master.size

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    report_frames: list[dict[str, object]] = []
    warnings: list[str] = []

    for index, path in enumerate(files, start=1):
        source, contaminated = clean_alpha(Image.open(path).convert("RGBA"))
        if source.size != master_size:
            warnings.append(f"{path.name}: source dimensions {source.size} differ from master {master_size}")

        resized = source.resize(
            (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
            Image.Resampling.LANCZOS,
        )
        source_pivot = contact_pivot(resized)
        offset_x = round(target_pivot[0] - source_pivot[0])
        offset_y = round(target_pivot[1] - source_pivot[1])
        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        canvas.alpha_composite(resized, (offset_x, offset_y))
        canvas, post_contaminated = clean_alpha(canvas)
        bbox = visible_bbox(canvas)
        final_pivot = contact_pivot(canvas)
        margins = {
            "left": bbox[0],
            "top": bbox[1],
            "right": canvas_width - bbox[2],
            "bottom": canvas_height - bbox[3],
        }
        if min(margins.values()) <= 0:
            warnings.append(f"{path.name}: visible pixels touch a canvas edge")
        if abs(final_pivot[1] - target_pivot[1]) > 1:
            warnings.append(f"{path.name}: vertical root deviation exceeds 1px")

        output = args.output_dir / f"frame-{index:03d}.png"
        canvas.save(output)
        frames.append(canvas)
        report_frames.append(
            {
                "source": path.name,
                "output": output.name,
                "sourceSize": source.size,
                "sourcePivot": [round(source_pivot[0], 2), source_pivot[1]],
                "translation": [offset_x, offset_y],
                "finalPivot": [round(final_pivot[0], 2), final_pivot[1]],
                "visibleBounds": list(bbox),
                "margins": margins,
                "cleanedInvisibleColorPixels": contaminated + post_contaminated,
            }
        )

    columns = math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / columns)
    thumb_width = 256
    thumb_height = round(thumb_width * canvas_height / canvas_width)
    contact = checkerboard((columns * thumb_width, rows * thumb_height), 12)
    draw = ImageDraw.Draw(contact)
    for index, frame in enumerate(frames):
        thumb = frame.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        x = (index % columns) * thumb_width
        y = (index // columns) * thumb_height
        contact.paste(thumb, (x, y), thumb)
        px = x + round(target_pivot[0] * thumb_width / canvas_width)
        py = y + round(target_pivot[1] * thumb_height / canvas_height)
        draw.line((px - 8, py, px + 8, py), fill=(255, 0, 255), width=1)
        draw.line((px, py - 8, px, py + 8), fill=(255, 0, 255), width=1)
        draw.text((x + 8, y + 8), f"{index + 1:03d}", fill=(0, 0, 0))
    contact.save(args.output_dir / "pivot-contact-sheet.png")
    solid_contact_sheet(frames, (canvas_width, canvas_height), (255, 255, 255), args.output_dir / "white-contact-sheet.png")
    solid_contact_sheet(frames, (canvas_width, canvas_height), (0, 0, 0), args.output_dir / "black-contact-sheet.png")

    if args.order:
        playback = [int(value.strip()) for value in args.order.split(",") if value.strip()]
    else:
        playback = list(range(1, len(frames) + 1))
    if any(value < 1 or value > len(frames) for value in playback):
        raise SystemExit("--order contains a frame number outside the available range")

    preview: list[Image.Image] = []
    for number in playback:
        board = checkerboard((canvas_width, canvas_height), 24)
        board.paste(frames[number - 1], (0, 0), frames[number - 1])
        preview.append(board)
    preview[0].save(
        args.output_dir / "preview.gif",
        save_all=True,
        append_images=preview[1:],
        duration=round(1000 / args.fps),
        loop=0,
        disposal=2,
    )

    pivots_x = [float(item["finalPivot"][0]) for item in report_frames]
    pivots_y = [float(item["finalPivot"][1]) for item in report_frames]
    report = {
        "canvas": [canvas_width, canvas_height],
        "targetPivot": list(target_pivot),
        "master": str(master_path),
        "sharedScale": scale,
        "fps": args.fps,
        "playbackOrder": playback,
        "maxMeasuredRootDeviation": {
            "x": max(abs(value - target_pivot[0]) for value in pivots_x),
            "y": max(abs(value - target_pivot[1]) for value in pivots_y),
        },
        "warnings": warnings,
        "frames": report_frames,
    }
    (args.output_dir / "validation-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Normalized {len(frames)} frames to {args.output_dir}")
    print(f"Warnings: {len(warnings)}")


if __name__ == "__main__":
    main()
