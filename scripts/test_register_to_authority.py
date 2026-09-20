#!/usr/bin/env python3
"""Tests for translation-only registration and the matte clamp."""

from __future__ import annotations

import math
import unittest

import numpy as np
from PIL import Image

from register_to_authority import (
    ALPHA_VISIBLE,
    erode,
    estimate_shift,
    luma,
    register,
    sample_shifted,
)


CANVAS = 96


def authority_frame() -> np.ndarray:
    """A sprite with enough internal structure for a gradient fit: a body, a
    darker outline and two interior features."""
    image = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
    image[20:76, 28:68] = (90, 140, 190, 255)
    image[20:24, 28:68] = (30, 40, 60, 255)
    image[72:76, 28:68] = (30, 40, 60, 255)
    image[20:76, 28:32] = (30, 40, 60, 255)
    image[20:76, 64:68] = (30, 40, 60, 255)
    image[34:42, 38:46] = (240, 220, 180, 255)
    image[34:42, 52:60] = (240, 220, 180, 255)
    image[54:64, 40:58] = (200, 80, 70, 255)
    return image


def shift_rgba(image: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Move content by (dx, dy); the inverse of the sampling convention."""
    moved = np.dstack(
        [
            sample_shifted(image[:, :, channel].astype(np.float64), -dx, -dy)
            for channel in range(4)
        ]
    )
    return np.clip(moved, 0, 255).astype(np.uint8)


def upscale(image: np.ndarray, factor: float) -> np.ndarray:
    size = (int(CANVAS * factor), int(CANVAS * factor))
    return np.asarray(
        Image.fromarray(image, "RGBA").resize(size, Image.LANCZOS), dtype=np.uint8
    )


class EstimatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = authority_frame()
        self.mask = erode(self.authority[:, :, 3] >= 250, 2)

    def recover(self, dx: float, dy: float) -> float:
        moved = luma(shift_rgba(self.authority, dx, dy))
        found_x, found_y = estimate_shift(moved, luma(self.authority), self.mask)
        return math.hypot(found_x - dx, found_y - dy)

    def test_recovers_known_sub_pixel_shifts(self) -> None:
        for dx, dy in [(0.0, 0.0), (0.25, 0.0), (0.0, -0.4), (0.33, 0.47), (-0.6, 0.6)]:
            with self.subTest(dx=dx, dy=dy):
                self.assertLess(self.recover(dx, dy), 0.05)

    def test_recovers_whole_pixel_shifts(self) -> None:
        self.assertLess(self.recover(1.0, -1.0), 0.05)


class RegisterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.authority = authority_frame()

    def test_identical_input_needs_no_shift(self) -> None:
        image, record = register(self.authority.copy(), self.authority)
        self.assertEqual(record["status"], "accepted")
        self.assertLess(record["shiftPixels"], 0.05)
        self.assertIsNotNone(image)

    def test_oversized_input_is_brought_back_to_the_authority_canvas(self) -> None:
        image, record = register(upscale(self.authority, 1.7417), self.authority)
        self.assertEqual(record["status"], "accepted", record.get("errors"))
        self.assertEqual(image.shape, self.authority.shape)

    def test_a_known_offset_is_measured_and_undone(self) -> None:
        moved = shift_rgba(self.authority, 0.4, -0.3)
        image, record = register(moved, self.authority)
        self.assertEqual(record["status"], "accepted", record.get("errors"))
        self.assertAlmostEqual(record["dx"], 0.4, delta=0.08)
        self.assertAlmostEqual(record["dy"], -0.3, delta=0.08)
        residual = estimate_shift(
            luma(image), luma(self.authority), erode(self.authority[:, :, 3] >= 250, 2)
        )
        self.assertLess(math.hypot(*residual), 0.1)

    def test_matte_outside_the_authority_is_removed_and_counted(self) -> None:
        grown = self.authority.copy()
        halo = np.zeros((CANVAS, CANVAS), dtype=bool)
        halo[16:80, 24:72] = True
        halo &= grown[:, :, 3] == 0
        grown[halo] = (90, 140, 190, 90)  # semi-transparent matte, as the tool adds
        image, record = register(grown, self.authority)
        self.assertEqual(record["status"], "accepted", record.get("errors"))
        self.assertEqual(record["clampedPixels"], int(halo.sum()))
        self.assertLessEqual(record["areaGrowth"], 0.0)
        outside = image[:, :, 3][self.authority[:, :, 3] <= ALPHA_VISIBLE]
        self.assertEqual(int(outside.max()), 0)

    def test_a_scaled_sprite_is_rejected_as_warp(self) -> None:
        bigger = np.zeros_like(self.authority)
        scaled = upscale(self.authority, 1.05)
        offset = (scaled.shape[0] - CANVAS) // 2
        bigger[:, :] = scaled[offset : offset + CANVAS, offset : offset + CANVAS]
        _, record = register(bigger, self.authority)
        self.assertEqual(record["status"], "repair-needed")
        self.assertTrue(any("scale or warp" in e for e in record["errors"]))

    def test_a_shrunken_sprite_is_rejected_rather_than_silently_clamped(self) -> None:
        smaller = np.zeros_like(self.authority)
        smaller[30:66, 34:62] = self.authority[30:66, 34:62]
        _, record = register(smaller, self.authority)
        self.assertEqual(record["status"], "repair-needed")
        self.assertTrue(any("shrank" in e for e in record["errors"]))

    def test_an_empty_repair_cannot_be_registered(self) -> None:
        _, record = register(np.zeros_like(self.authority), self.authority)
        self.assertEqual(record["status"], "repair-needed")
        self.assertTrue(any("stable opaque interior" in e for e in record["errors"]))

    def test_an_offset_beyond_the_cap_is_rejected(self) -> None:
        _, record = register(
            shift_rgba(self.authority, 1.2, 0.0), self.authority, max_shift=0.5
        )
        self.assertEqual(record["status"], "repair-needed")
        self.assertTrue(any("exceeds" in e for e in record["errors"]))


if __name__ == "__main__":
    unittest.main()
