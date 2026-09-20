#!/usr/bin/env python3
"""Render the artifacts a visual QA judgement has to be made on.

The delivery gate requires a visual QA report whose artifacts exist on disk,
because a prose claim that a sequence was reviewed is not reviewable. Nothing
produced them, so the claim was the only thing on offer. This renders the five:

- the sequence at its exact delivery FPS, which is the only speed at which
  judder reads the way a player will see it;
- the same sequence slowed down, where a single bad frame stops hiding inside
  motion;
- previous/current/next triplets for whichever frames were flagged;
- an onion sheet over the whole batch, where drift accumulates visibly;
- each output beside the frames it answers to: the approved parent it was
  edited from and the native frame that is still its pose authority.

It renders; it does not judge. The report it writes leaves every reviewed flag
false, and a reviewer sets them after looking. Writing them true here would
recreate exactly the gap this closes.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as error:  # pragma: no cover - dependency guidance
    raise SystemExit(
        f"{error}. Install the skill's dependencies: "
        "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    )


def load_frames(manifest: dict, frames_dir: Path) -> tuple[list[int], list[Path]]:
    numbers, paths = [], []
    for record in manifest.get("frameMapping", []):
        index = int(record["outputFrame"])
        candidate = frames_dir / str(record.get("outputFile") or f"frame-{index:03d}.png")
        if candidate.is_file():
            numbers.append(index)
            paths.append(candidate)
    return numbers, paths


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


def write_gif(paths: list[Path], output: Path, fps: float) -> None:
    frames = [on_checker(path) for path in paths]
    output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=max(1, int(round(1000.0 / fps))),
        loop=0,
        disposal=2,
    )


def write_mp4(paths: list[Path], output: Path, fps: float) -> bool:
    """Exact-FPS preview via ffmpeg when it is available."""
    if not paths:
        return False
    listing = output.parent / "_frames.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text("".join(f"file '{path.resolve()}'\nduration {1/fps:.6f}\n" for path in paths))
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                "-i", str(listing), "-r", str(fps),
                "-vf", "format=yuv420p,scale=trunc(iw/2)*2:trunc(ih/2)*2",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    finally:
        listing.unlink(missing_ok=True)


def onion_sheet(paths: list[Path], output: Path) -> None:
    """Every silhouette stacked, so drift across the batch is one picture."""
    accumulator = None
    for index, path in enumerate(paths):
        alpha = (np.asarray(Image.open(path).convert("RGBA"))[:, :, 3] > 18).astype(np.float64)
        if accumulator is None:
            accumulator = np.zeros((*alpha.shape, 3), dtype=np.float64)
        weight = index / max(1, len(paths) - 1)
        accumulator[:, :, 0] += alpha * (1.0 - weight)
        accumulator[:, :, 2] += alpha * weight
        accumulator[:, :, 1] += alpha * 0.25
    scaled = 255.0 * accumulator / max(1e-9, accumulator.max())
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(scaled.astype(np.uint8), "RGB").save(output)


def triplet_sheets(numbers: list[int], paths: list[Path], flagged: list[int], output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    position = {number: index for index, number in enumerate(numbers)}
    written = 0
    for number in flagged:
        if number not in position:
            continue
        index = position[number]
        window = [index - 1, index, index + 1]
        panels = [on_checker(paths[i]) for i in window if 0 <= i < len(paths)]
        if not panels:
            continue
        width = sum(panel.width for panel in panels)
        sheet = Image.new("RGB", (width, panels[0].height + 22), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        offset = 0
        for i, panel in zip([i for i in window if 0 <= i < len(paths)], panels):
            sheet.paste(panel, (offset, 22))
            draw.text((offset + 6, 6), f"frame {numbers[i]:03d}", fill="white")
            offset += panel.width
        sheet.save(output / f"frame-{number:03d}-triplet.png")
        written += 1
    return written


def resolve_source_directory(manifest: dict, manifest_path: Path) -> Path | None:
    """Where the native frames live.

    A parent manifest names the source frames per record but keeps the
    directory in the source manifest it points at, so follow that link rather
    than reporting no pairs and letting the gate pass on an empty folder.
    """
    direct = manifest.get("sourceFramesDirectory")
    if direct and Path(direct).is_dir():
        return Path(direct)
    linked = manifest.get("sourceFrameManifest")
    if linked:
        path = Path(linked)
        if not path.is_absolute():
            path = manifest_path.parent / path
        if path.is_file():
            nested = json.loads(path.read_text()).get("sourceFramesDirectory")
            if nested and Path(nested).is_dir():
                return Path(nested)
    return None


def comparison_sheets(
    manifest: dict,
    manifest_path: Path,
    numbers: list[int],
    paths: list[Path],
    output: Path,
    limit: int,
) -> int:
    """Each output beside the frames it answers to.

    For alpha repair that is two comparisons, not one: the approved parent it
    was edited from, and the native frame that remains its pose authority. A
    repair can hold its pose perfectly and still have redrawn the parent.
    """
    source_dir = resolve_source_directory(manifest, manifest_path)
    parent_dir = manifest.get("parentFramesDirectory")
    parent_dir = Path(parent_dir) if parent_dir else None
    records = {int(r["outputFrame"]): r for r in manifest.get("frameMapping", [])}
    output.mkdir(parents=True, exist_ok=True)
    step = max(1, len(numbers) // max(1, limit))
    written = 0
    for number, path in list(zip(numbers, paths))[::step]:
        record = records.get(number, {})
        panels: list[tuple[str, Image.Image]] = []
        if source_dir is not None:
            source = source_dir / str(record.get("sourceFile", ""))
            if source.is_file():
                panels.append((f"native {record.get('nativeFrame')}", Image.open(source).convert("RGB")))
        if parent_dir is not None and record.get("parentFile"):
            parent = parent_dir / str(record["parentFile"])
            if parent.is_file():
                panels.append((f"parent {number:03d}", on_checker(parent)))
        panels.append((f"output {number:03d}", on_checker(path)))
        if len(panels) < 2:
            continue
        height = max(panel.height for _, panel in panels)
        sheet = Image.new("RGB", (sum(p.width for _, p in panels), height + 22), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        offset = 0
        for label, panel in panels:
            sheet.paste(panel, (offset, 22))
            draw.text((offset + 6, 6), label, fill="white")
            offset += panel.width
        sheet.save(output / f"frame-{number:03d}-comparison.png")
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--slow-factor", type=float, default=4.0)
    parser.add_argument("--temporal-report", type=Path)
    parser.add_argument("--source-pairs", type=int, default=12)
    parser.add_argument("--reviewer", default="agent")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    numbers, paths = load_frames(manifest, args.frames)
    expected = [int(r["outputFrame"]) for r in manifest.get("frameMapping", [])]
    missing = [n for n in expected if n not in numbers]
    if len(paths) < 2:
        raise SystemExit("need at least two frames to render QA artifacts")

    flagged: list[int] = []
    if args.temporal_report and args.temporal_report.is_file():
        report = json.loads(args.temporal_report.read_text())
        flagged = sorted(
            {int(f["frame"]) for f in report.get("geometryAccelerationFailures", [])}
            | {
                int(part)
                for f in report.get("geometryTransitionFailures", [])
                for part in str(f["transition"]).split("->")
            }
        )
    if not flagged:
        # Nothing flagged: sample across the batch so there is still something
        # to look at rather than an empty directory standing in for a review.
        flagged = numbers[:: max(1, len(numbers) // 6)]

    args.output.mkdir(parents=True, exist_ok=True)
    exact_gif = args.output / "preview-exact-fps.gif"
    slow_gif = args.output / "preview-slow.gif"
    write_gif(paths, exact_gif, args.fps)
    write_gif(paths, slow_gif, max(1.0, args.fps / args.slow_factor))
    exact = exact_gif
    if write_mp4(paths, args.output / "preview-exact-fps.mp4", args.fps):
        exact = args.output / "preview-exact-fps.mp4"

    onion = args.output / "alpha-onion-sheet.png"
    onion_sheet(paths, onion)
    triplets = args.output / "triplets"
    triplet_count = triplet_sheets(numbers, paths, flagged, triplets)
    pairs = args.output / "comparisons"
    pair_count = comparison_sheets(
        manifest, args.manifest, numbers, paths, pairs, args.source_pairs
    )

    report = {
        "status": "pending-review",
        "reviewer": args.reviewer,
        "frameCount": len(paths),
        "missingFrames": missing,
        "flaggedFrames": flagged,
        "tripletSheets": triplet_count,
        "comparisonSheets": pair_count,
        # Every flag stays false. A reviewer looks at the artifacts below and
        # sets them; rendering a picture is not the same as having seen it.
        "normalSpeedReviewed": False,
        "slowSpeedReviewed": False,
        "tripletsReviewed": False,
        "onionSkinReviewed": False,
        "sourceOutputPairsReviewed": False,
        "parentOutputPairsReviewed": False,
        "sourceMotionCompared": False,
        "topologyAndLandmarksReviewed": False,
        "artifacts": {
            "exactFpsPreview": str(exact.relative_to(args.output.parent)),
            "slowPreview": str(slow_gif.relative_to(args.output.parent)),
            "triplets": str(triplets.relative_to(args.output.parent)),
            "onionSkin": str(onion.relative_to(args.output.parent)),
            "sourceMotionComparison": str(pairs.relative_to(args.output.parent)),
        },
    }
    destination = args.output.parent / "visual-qa-report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "frameCount": report["frameCount"],
                "missingFrames": missing,
                "tripletSheets": triplet_count,
                "comparisonSheets": pair_count,
                "report": str(destination),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
