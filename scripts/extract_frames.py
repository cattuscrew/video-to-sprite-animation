#!/usr/bin/env python3
"""Extract consistently framed pose references from a video."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def parse_crop(value: str) -> tuple[int, int, int, int]:
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x,y,width,height")
    return parts[0], parts[1], parts[2], parts[3]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--timestamps", required=True, help="Comma-separated seconds")
    parser.add_argument("--labels", help="Optional comma-separated labels")
    parser.add_argument("--crop", type=parse_crop, help="Shared x,y,width,height crop")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise SystemExit("ffmpeg and ffprobe are required")
    if not args.video.is_file():
        raise SystemExit(f"Video not found: {args.video}")

    timestamps = [float(value.strip()) for value in args.timestamps.split(",") if value.strip()]
    labels = [value.strip() for value in args.labels.split(",")] if args.labels else []
    if labels and len(labels) != len(timestamps):
        raise SystemExit("--labels count must match --timestamps count")
    if not labels:
        labels = [f"pose-{index:03d}" for index in range(1, len(timestamps) + 1)]

    probe = json.loads(
        run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(args.video),
            ]
        ).stdout
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, object]] = []
    for index, (timestamp, label) in enumerate(zip(timestamps, labels), start=1):
        safe_label = "".join(character if character.isalnum() or character in "-_" else "-" for character in label)
        output = args.out_dir / f"{index:03d}-{safe_label}.png"
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.6f}",
            "-i",
            str(args.video),
            "-frames:v",
            "1",
        ]
        if args.crop:
            x, y, width, height = args.crop
            command.extend(["-vf", f"crop={width}:{height}:{x}:{y}"])
        command.append(str(output))
        run(command)
        frames.append({"index": index, "timestamp": timestamp, "label": label, "path": output.name})

    manifest = {
        "source": str(args.video.resolve()),
        "probe": probe,
        "crop": args.crop,
        "frames": frames,
    }
    (args.out_dir / "references.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Extracted {len(frames)} references to {args.out_dir}")


if __name__ == "__main__":
    main()

