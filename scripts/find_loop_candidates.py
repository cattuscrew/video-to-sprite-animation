#!/usr/bin/env python3
"""Rank natural and ping-pong loop candidates from native-FPS source frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def parse_crop(value: str | None) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("crop must be x,y,width,height")
    return tuple(parts)  # type: ignore[return-value]


def load_frame(path: Path, crop: tuple[int, int, int, int] | None) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    if crop:
        x, y, width, height = crop
        image = image.crop((x, y, x + width, y + height))
    image = image.resize((160, 160), Image.Resampling.LANCZOS)
    return np.asarray(image, dtype=np.float32) / 255.0


def edge_map(frame: np.ndarray) -> np.ndarray:
    gray = frame[:, :, 0] * 0.299 + frame[:, :, 1] * 0.587 + frame[:, :, 2] * 0.114
    dx = np.diff(gray, axis=1, append=gray[:, -1:])
    dy = np.diff(gray, axis=0, append=gray[-1:, :])
    return np.sqrt(dx * dx + dy * dy)


def distance(a: np.ndarray, b: np.ndarray, edge_a: np.ndarray, edge_b: np.ndarray) -> float:
    appearance = float(np.mean(np.abs(a - b)))
    outline = float(np.mean(np.abs(edge_a - edge_b)))
    return appearance * 0.7 + outline * 0.3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path, help="Native-FPS frame directory")
    parser.add_argument("output", type=Path, help="Ranking JSON path")
    parser.add_argument("--source-start", type=float, required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--window-frames", type=int, help="Defaults to one second")
    parser.add_argument("--half-cycle-frames", type=int, help="Defaults to half a second")
    parser.add_argument("--crop", type=parse_crop)
    args = parser.parse_args()

    paths = sorted(args.frames.glob("frame-*.png"))
    window = args.window_frames or args.fps
    half_cycle = args.half_cycle_frames or args.fps // 2
    if len(paths) < window + 1:
        raise SystemExit(f"Need at least {window + 1} frames for natural-loop scoring")
    if half_cycle < 2 or len(paths) <= half_cycle:
        raise SystemExit("Not enough frames for ping-pong scoring")

    frames = [load_frame(path, args.crop) for path in paths]
    edges = [edge_map(frame) for frame in frames]
    natural: list[dict[str, float | int]] = []
    for start in range(0, len(frames) - window):
        steps = [
            distance(frames[index], frames[index + 1], edges[index], edges[index + 1])
            for index in range(start, start + window)
        ]
        seam_error = distance(
            frames[start], frames[start + window], edges[start], edges[start + window]
        )
        boundary_step = distance(
            frames[start + window - 1], frames[start], edges[start + window - 1], edges[start]
        )
        typical_step = float(np.median(steps))
        natural.append(
            {
                "startFrameOffset": start,
                "startSeconds": args.source_start + start / args.fps,
                "endSecondsExclusive": args.source_start + (start + window) / args.fps,
                "score": seam_error * 4.0 + abs(boundary_step - typical_step),
                "seamError": seam_error,
                "boundaryVelocityError": abs(boundary_step - typical_step),
                "motionEnergy": float(np.mean(steps)),
            }
        )
    natural.sort(key=lambda item: float(item["score"]))

    ping_pong: list[dict[str, float | int]] = []
    for start in range(0, len(frames) - half_cycle):
        end = start + half_cycle
        steps = [
            distance(frames[index], frames[index + 1], edges[index], edges[index + 1])
            for index in range(start, end)
        ]
        amplitude = distance(frames[start], frames[end], edges[start], edges[end])
        start_velocity = steps[0]
        turn_velocity = steps[-1]
        ping_pong.append(
            {
                "startFrameOffset": start,
                "turnFrameOffset": end,
                "startSeconds": args.source_start + start / args.fps,
                "turnSeconds": args.source_start + end / args.fps,
                "score": (start_velocity + turn_velocity) / (amplitude + 0.002),
                "startVelocity": start_velocity,
                "turnVelocity": turn_velocity,
                "amplitude": amplitude,
                "motionEnergy": float(np.mean(steps)),
            }
        )
    ping_pong.sort(key=lambda item: float(item["score"]))

    result = {
        "sourceStart": args.source_start,
        "fps": args.fps,
        "windowFrames": window,
        "halfCycleFrames": half_cycle,
        "crop": args.crop,
        "bestNatural": natural[0],
        "bestPingPong": ping_pong[0],
        "topNatural": natural[:10],
        "topPingPong": ping_pong[:10],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
