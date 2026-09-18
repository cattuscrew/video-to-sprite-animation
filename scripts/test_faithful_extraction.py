#!/usr/bin/env python3
from __future__ import annotations

import unittest

import numpy as np

from protected_background import (
    extract_protected_foreground,
    place_rgba,
    resize_rgba_premultiplied,
)
from validate_protected_frames import validate_authority


class FaithfulExtractionRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.background = np.array([234, 228, 212], dtype=np.uint8)

    def test_enclosed_neck_and_collar_colors_survive(self) -> None:
        image = np.full((64, 64, 3), self.background, dtype=np.uint8)
        image[12:52, 12:52] = [10, 10, 10]
        image[14:50, 14:50] = [238, 218, 202]
        image[38:45, 20:44] = [244, 239, 220]
        result = extract_protected_foreground(image)
        self.assertEqual(int(result.rgba[30, 30, 3]), 255)
        self.assertEqual(int(result.rgba[41, 30, 3]), 255)

    def test_open_background_gap_is_removed(self) -> None:
        image = np.full((64, 64, 3), self.background, dtype=np.uint8)
        image[12:52, 12:52] = [10, 10, 10]
        image[14:50, 14:50] = [238, 218, 202]
        image[:34, 29:35] = self.background
        result = extract_protected_foreground(image)
        self.assertEqual(int(result.rgba[25, 32, 3]), 0)

    def test_dark_outline_and_source_rgb_survive(self) -> None:
        image = np.full((64, 64, 3), self.background, dtype=np.uint8)
        image[20:44, 20:44] = [8, 9, 10]
        image[22:42, 22:42] = [40, 150, 55]
        result = extract_protected_foreground(image)
        self.assertTrue(np.array_equal(result.rgba[20, 30], [8, 9, 10, 255]))
        self.assertTrue(np.array_equal(result.rgba[30, 30], [40, 150, 55, 255]))

    def test_premultiplied_resize_does_not_import_matte_rgb(self) -> None:
        rgba = np.zeros((16, 16, 4), dtype=np.uint8)
        rgba[4:12, 4:12, :3] = [10, 20, 30]
        rgba[4:12, 4:12, 3] = 255
        resized = resize_rgba_premultiplied(rgba, (8, 8))
        visible = resized[:, :, 3] > 0
        self.assertLessEqual(int(resized[:, :, :3][visible].max()), 31)
        self.assertTrue(np.all(resized[:, :, :3][~visible] == 0))

    def test_fixed_integer_placement_does_not_recenter(self) -> None:
        rgba = np.zeros((8, 8, 4), dtype=np.uint8)
        rgba[2, 3] = [1, 2, 3, 255]
        placed = place_rgba(rgba, (16, 16), (4, 5))
        self.assertTrue(np.array_equal(placed[7, 7], [1, 2, 3, 255]))
        self.assertEqual(int(np.count_nonzero(placed[:, :, 3])), 1)

    def test_rejected_or_circular_authority_cannot_pass(self) -> None:
        errors = validate_authority(
            {
                "sourceKind": "rejected-color-key-derived",
                "userApproved": False,
                "derivedFromRejectedOutput": True,
            }
        )
        self.assertEqual(len(errors), 4)


if __name__ == "__main__":
    unittest.main()
