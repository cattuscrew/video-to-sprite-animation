from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage


@dataclass(frozen=True)
class BackgroundResult:
    rgba: np.ndarray
    key_rgb: tuple[float, float, float]
    background_pixels: int
    foreground_pixels: int
    foreground_components: int


def sample_border_key(rgb: np.ndarray, border_width: int = 24) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("expected an HxWx3 RGB array")
    width = max(1, min(border_width, rgb.shape[0] // 4, rgb.shape[1] // 4))
    border = np.concatenate(
        [
            rgb[:width].reshape(-1, 3),
            rgb[-width:].reshape(-1, 3),
            rgb[:, :width].reshape(-1, 3),
            rgb[:, -width:].reshape(-1, 3),
        ]
    )
    return np.median(border.astype(np.float32), axis=0)


def border_connected_background(
    rgb: np.ndarray,
    *,
    seed_threshold: float = 12.0,
    grow_threshold: float = 80.0,
    border_width: int = 24,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return only background-like pixels reachable from the canvas border.

    A global color key is unsafe because skin, collars, highlights, and antialiased
    linework may resemble the background. Connectivity makes those enclosed pixels
    foreground even when their color is close to the sampled matte.
    """
    if seed_threshold <= 0 or grow_threshold < seed_threshold:
        raise ValueError("require 0 < seed_threshold <= grow_threshold")
    key = sample_border_key(rgb, border_width)
    distance = np.linalg.norm(rgb.astype(np.float32) - key, axis=2)
    growable = distance <= grow_threshold
    seeds = np.zeros(distance.shape, dtype=bool)
    seed_like = distance <= seed_threshold
    seeds[0, :] = seed_like[0, :]
    seeds[-1, :] = seed_like[-1, :]
    seeds[:, 0] = seed_like[:, 0]
    seeds[:, -1] = seed_like[:, -1]
    background = ndimage.binary_propagation(seeds, mask=growable)
    return background, distance, key


def extract_protected_foreground(
    rgb: np.ndarray,
    *,
    seed_threshold: float = 12.0,
    grow_threshold: float = 80.0,
    border_width: int = 24,
) -> BackgroundResult:
    """Extract foreground without erosion, component deletion, or RGB rewriting."""
    background, _, key = border_connected_background(
        rgb,
        seed_threshold=seed_threshold,
        grow_threshold=grow_threshold,
        border_width=border_width,
    )
    foreground = ~background
    _, components = ndimage.label(foreground)
    rgba = np.zeros((*rgb.shape[:2], 4), dtype=np.uint8)
    rgba[foreground, :3] = rgb[foreground]
    rgba[foreground, 3] = 255
    return BackgroundResult(
        rgba=rgba,
        key_rgb=tuple(round(float(value), 2) for value in key),
        background_pixels=int(np.count_nonzero(background)),
        foreground_pixels=int(np.count_nonzero(foreground)),
        foreground_components=int(components),
    )


def resize_rgba_premultiplied(rgba: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Resize straight RGBA through premultiplied channels to avoid matte bleed."""
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("expected an HxWx4 RGBA array")
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    premultiplied = rgba[:, :, :3].astype(np.float32) * alpha[:, :, None]

    resized_alpha = np.asarray(
        Image.fromarray(alpha, "F").resize(size, Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    resized_premultiplied = np.stack(
        [
            np.asarray(
                Image.fromarray(premultiplied[:, :, channel], "F").resize(
                    size, Image.Resampling.LANCZOS
                ),
                dtype=np.float32,
            )
            for channel in range(3)
        ],
        axis=2,
    )
    resized_alpha = np.clip(resized_alpha, 0.0, 1.0)
    straight = np.zeros_like(resized_premultiplied)
    visible = resized_alpha > (1.0 / 255.0)
    straight[visible] = resized_premultiplied[visible] / resized_alpha[visible, None]

    output = np.zeros((*resized_alpha.shape, 4), dtype=np.uint8)
    output[:, :, :3] = np.clip(np.round(straight), 0, 255).astype(np.uint8)
    output[:, :, 3] = np.clip(np.round(resized_alpha * 255.0), 0, 255).astype(np.uint8)
    output[output[:, :, 3] == 0, :3] = 0
    return output


def place_rgba(
    rgba: np.ndarray,
    canvas_size: tuple[int, int],
    offset: tuple[int, int],
) -> np.ndarray:
    canvas_width, canvas_height = canvas_size
    offset_x, offset_y = offset
    canvas = np.zeros((canvas_height, canvas_width, 4), dtype=np.uint8)
    source_height, source_width = rgba.shape[:2]
    source_x0 = max(0, -offset_x)
    source_y0 = max(0, -offset_y)
    destination_x0 = max(0, offset_x)
    destination_y0 = max(0, offset_y)
    copy_width = min(source_width - source_x0, canvas_width - destination_x0)
    copy_height = min(source_height - source_y0, canvas_height - destination_y0)
    if copy_width <= 0 or copy_height <= 0:
        raise ValueError("transformed image does not intersect the canvas")
    canvas[
        destination_y0 : destination_y0 + copy_height,
        destination_x0 : destination_x0 + copy_width,
    ] = rgba[
        source_y0 : source_y0 + copy_height,
        source_x0 : source_x0 + copy_width,
    ]
    return canvas
