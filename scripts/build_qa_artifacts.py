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
- each output beside the native frame it was edited from, on the checkerboard
  and on black, because a coloured or ragged rim shows only against black.

It renders; it does not judge. The report it writes leaves every reviewed flag
false, and a reviewer sets them after looking. Writing them true here would
recreate exactly the gap this closes.
"""

from __future__ import annotations

import argparse
import json
import shutil
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


def write_gif(
    paths: list[Path],
    output: Path,
    fps: float,
    loops: bool = True,
    background: str = "checker",
) -> None:
    """`loops=False` writes a GIF that plays once and holds its last frame.

    A one-shot looped back to its first frame reads as a stutter that the
    sprites do not have, and reviewing playback on it reviews the preview.

    `background="black"` for a preview meant for watching motion: a sprite
    moving over a static checkerboard is hard to read, and black is what the
    exact-FPS MP4 uses, so both previews show an edge the same way.
    """
    render = on_black if background == "black" else on_checker
    frames = [render(path) for path in paths]
    output.parent.mkdir(parents=True, exist_ok=True)
    options = {"loop": 0} if loops else {}
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=max(1, int(round(1000.0 / fps))),
        disposal=2,
        **options,
    )


# Lossless h264 still round-trips through RGB->YUV->RGB, which costs a level
# or two. Anything beyond that is the encoder inventing detail.
PREVIEW_MAX_CHANNEL_ERROR = 4


def on_black(path: Path) -> Image.Image:
    sprite = Image.open(path).convert("RGBA")
    board = Image.new("RGBA", sprite.size, (0, 0, 0, 255))
    board.alpha_composite(sprite)
    return board.convert("RGB")


def write_mp4(paths: list[Path], output: Path, fps: float) -> bool:
    """Exact-FPS preview via ffmpeg when it is available.

    Two things here are not defaults, and both were learned the hard way.

    The frames are composited onto black in Pillow rather than by letting
    ffmpeg drop the alpha channel, so what the encoder receives is exactly what
    a viewer would see.

    The encode is lossless 4:4:4. The obvious `format=yuv420p` at default
    quality halves the chroma resolution and then quantises it, which on a hard
    sprite edge against black produces ringing that looks precisely like a
    dirty, contaminated outline. On the 2026-09-20 delivery that put 14,569
    non-black pixels into what should have been empty space, up to 45 levels
    off, hugging the outline -- artifacts of the preview, not of the frames.
    Reviewing edge quality on a lossy preview cannot work.
    """
    if not paths:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = output.parent / f"_{output.stem}-frames"
    staging.mkdir(parents=True, exist_ok=True)
    try:
        for index, path in enumerate(paths, start=1):
            on_black(path).save(staging / f"frame-{index:04d}.png")
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error",
                "-framerate", str(fps),
                "-i", str(staging / "frame-%04d.png"),
                "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def preview_fidelity(video: Path, paths: list[Path]) -> dict[str, object]:
    """Decode the preview back and compare it with the frames it claims to show.

    A preview is evidence, so it has to be checked like evidence. Without this
    the reviewer is judging the encoder as much as the sprites, and a defect
    the encoder invented is indistinguishable from one the image tool did.
    """
    result: dict[str, object] = {"video": str(video)}
    if not video.is_file() or not paths:
        result["status"] = "not-checked"
        return result
    decoded = video.parent / f"_{video.stem}-decoded.png"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
             "-vframes", "1", str(decoded)],
            check=True,
            capture_output=True,
        )
        actual = np.asarray(Image.open(decoded).convert("RGB"), dtype=np.int16)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        result["status"] = "not-checked"
        return result
    finally:
        decoded.unlink(missing_ok=True)

    expected = np.asarray(on_black(paths[0]), dtype=np.int16)
    if actual.shape != expected.shape:
        result.update({"status": "repair-needed", "error": "preview size differs"})
        return result
    difference = np.abs(actual - expected).max(axis=2)
    transparent = np.asarray(Image.open(paths[0]).convert("RGBA"))[:, :, 3] == 0
    result.update(
        {
            "maxChannelError": int(difference.max()),
            "pixelsAlteredInEmptySpace": int((difference[transparent] > 0).sum()),
            "status": (
                "accepted"
                if difference.max() <= PREVIEW_MAX_CHANNEL_ERROR
                else "repair-needed"
            ),
        }
    )
    return result


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

    A manifest may name the source files per record but keep the
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
    """Each output beside the native frame it answers to, and on black."""
    source_dir = resolve_source_directory(manifest, manifest_path)
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
        panels.append((f"output {number:03d}", on_checker(path)))
        panels.append((f"output {number:03d} on black", on_black(path)))
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
    parser.add_argument(
        "--loop-type",
        choices=("natural-loop", "ping-pong-loop", "one-shot"),
        default="natural-loop",
        help="one-shot previews play once instead of looping",
    )
    parser.add_argument("--slow-factor", type=float, default=4.0)
    parser.add_argument("--temporal-report", type=Path)
    parser.add_argument("--source-pairs", type=int, default=12)
    parser.add_argument("--reviewer", default="agent")
    parser.add_argument(
        "--review-method",
        default="played-back",
        help=(
            "how the motion checks were performed: 'played-back' when a "
            "reviewer watched the preview run, or a named alternative such as "
            "'frame-transition-analysis' when it was judged from per-transition "
            "motion rather than from playback. Recorded verbatim."
        ),
    )
    parser.add_argument(
        "--reviewed",
        help=(
            "comma-separated checks this reviewer actually performed, from: "
            "normalSpeed, slowSpeed, triplets, onionSkin, sourceOutputPairs, "
            "sourceMotion, topologyAndLandmarks. Anything left out stays false. "
            "The playback checks need someone who can watch the preview run; a "
            "reviewer who only read still frames should not claim them."
        ),
    )
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
    loops = args.loop_type != "one-shot"
    write_gif(paths, exact_gif, args.fps, loops)
    write_gif(
        paths,
        slow_gif,
        max(1.0, args.fps / args.slow_factor),
        loops,
        background="black",
    )
    # GIF frame delays are whole centiseconds, so 24fps becomes 25 and the
    # "exact FPS" preview would not be exact. That preview is the one timing is
    # judged on, so it stays MP4 when ffmpeg exists.
    exact = exact_gif
    if write_mp4(paths, args.output / "preview-exact-fps.mp4", args.fps):
        exact = args.output / "preview-exact-fps.mp4"
    # The slow preview is for looking at motion, not timing, so the
    # centisecond rounding costs nothing and a GIF loops by itself in any
    # viewer. An MP4 of it has to be opened, played and replayed by hand.
    slow = slow_gif

    onion = args.output / "alpha-onion-sheet.png"
    onion_sheet(paths, onion)
    triplets = args.output / "triplets"
    triplet_count = triplet_sheets(numbers, paths, flagged, triplets)
    pairs = args.output / "comparisons"
    pair_count = comparison_sheets(
        manifest, args.manifest, numbers, paths, pairs, args.source_pairs
    )

    fidelity = preview_fidelity(exact, paths)

    checks = {
        "normalSpeed": "normalSpeedReviewed",
        "slowSpeed": "slowSpeedReviewed",
        "triplets": "tripletsReviewed",
        "onionSkin": "onionSkinReviewed",
        "sourceOutputPairs": "sourceOutputPairsReviewed",
        "sourceMotion": "sourceMotionCompared",
        "topologyAndLandmarks": "topologyAndLandmarksReviewed",
    }
    requested = {c.strip() for c in (args.reviewed or "").split(",") if c.strip()}
    unknown = requested - set(checks)
    if unknown:
        raise SystemExit(f"unknown checks: {sorted(unknown)}; known: {sorted(checks)}")
    done = {flag: (name in requested) for name, flag in checks.items()}
    # A preview that does not match its frames is not evidence about the
    # frames, so no amount of reviewing it can complete the report.
    complete = (
        all(done.values())
        and not missing
        and fidelity.get("status") != "repair-needed"
    )

    report = {
        "status": "accepted" if complete else "pending-review",
        "outstandingChecks": sorted(n for n, f in checks.items() if not done[f]),
        "motionReviewMethod": args.review_method,
        "reviewer": args.reviewer,
        "frameCount": len(paths),
        "missingFrames": missing,
        "previewFidelity": fidelity,
        "flaggedFrames": flagged,
        "tripletSheets": triplet_count,
        "comparisonSheets": pair_count,
        # Only what --reviewed names. Rendering a picture is not seeing it.
        **done,
        "artifacts": {
            "exactFpsPreview": str(exact.relative_to(args.output.parent)),
            "slowPreview": str(slow.relative_to(args.output.parent)),
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
                "outstandingChecks": report["outstandingChecks"],
                "frameCount": report["frameCount"],
                "missingFrames": missing,
        "previewFidelity": fidelity,
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
