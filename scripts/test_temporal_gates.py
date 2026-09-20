#!/usr/bin/env python3
"""Characterisation tests for the extracted pair and triplet geometry gates."""

from __future__ import annotations

import unittest

import numpy as np

from validate_temporal_sequence import (
    pair_geometry_failure,
    silhouette_change,
    silhouette_metrics,
    triplet_acceleration_failure,
)


CANVAS = 64

LIMITS = {
    "maximumSilhouetteSpikeRatio": 1.8,
    "maximumVisibleAreaStepRatio": 0.03,
    "maximumBoundingBoxSizeStepPixels": 3,
    "maximumCentroidStepPixels": 2.0,
    "maximumBoundingBoxSizeAccelerationPixels": 4,
    "maximumCentroidAccelerationPixels": 1.5,
}


def sprite(left: int, width: int = 20, height: int = 30) -> np.ndarray:
    """An opaque rectangle on a transparent canvas."""
    image = np.zeros((CANVAS, CANVAS, 4), dtype=np.uint8)
    image[20 : 20 + height, left : left + width] = (80, 120, 160, 255)
    return image


def metrics(left: int, width: int = 20, height: int = 30) -> dict[str, object]:
    return silhouette_metrics(sprite(left, width, height))


class PairGateTests(unittest.TestCase):
    def test_small_translation_passes(self) -> None:
        self.assertIsNone(
            pair_geometry_failure(metrics(10), metrics(11), (1, 2), LIMITS)
        )

    def test_large_centroid_step_is_named_with_its_own_frames(self) -> None:
        failure = pair_geometry_failure(metrics(10), metrics(14), (1, 2), LIMITS)
        self.assertIsNotNone(failure)
        self.assertEqual(failure["transition"], "1->2")
        self.assertIn("centroid step", failure["reasons"])
        self.assertAlmostEqual(failure["centroidStepPixels"], 4.0, places=6)

    def test_growth_is_reported_as_area_and_bbox_steps(self) -> None:
        failure = pair_geometry_failure(metrics(10), metrics(10, width=28), (4, 5), LIMITS)
        self.assertIn("visible-area step", failure["reasons"])
        self.assertIn("bounding-box size step", failure["reasons"])
        self.assertEqual(failure["boundingBoxSizeStepPixels"], [8, 0])

    def test_approved_transition_is_skipped(self) -> None:
        self.assertIsNone(
            pair_geometry_failure(
                metrics(10), metrics(14), (1, 2), LIMITS, approved={"1->2"}
            )
        )

    def test_approval_is_matched_on_real_frame_numbers(self) -> None:
        """Approving 1->2 must not excuse the transition 6->9."""
        failure = pair_geometry_failure(
            metrics(10), metrics(14), (6, 9), LIMITS, approved={"1->2"}
        )
        self.assertIsNotNone(failure)
        self.assertEqual(failure["transition"], "6->9")

    def test_silhouette_spike_needs_a_median_to_compare_against(self) -> None:
        """A one-pixel slide changes the silhouette while area, bbox and
        centroid all stay inside their limits, so only the median-relative
        gate can see it -- and only once a median exists."""
        first, second = metrics(10), metrics(11)
        without = pair_geometry_failure(first, second, (1, 2), LIMITS)
        with_median = pair_geometry_failure(
            first, second, (1, 2), LIMITS, median_silhouette=0.001
        )
        self.assertIsNone(without)
        self.assertIn("silhouette-change spike", with_median["reasons"])


class TripletGateTests(unittest.TestCase):
    def test_constant_velocity_passes(self) -> None:
        self.assertIsNone(
            triplet_acceleration_failure(
                metrics(10), metrics(12), metrics(14), (1, 2, 3), LIMITS
            )
        )

    def test_reversal_fails_and_names_the_middle_frame(self) -> None:
        failure = triplet_acceleration_failure(
            metrics(10), metrics(13), metrics(10), (22, 23, 24), LIMITS
        )
        self.assertIsNotNone(failure)
        self.assertEqual(failure["frame"], 23)
        self.assertIn("centroid acceleration", failure["reasons"])
        self.assertAlmostEqual(failure["centroidAccelerationPixels"], 6.0, places=5)

    def test_either_approved_transition_skips_the_triplet(self) -> None:
        for approved in ({"22->23"}, {"23->24"}):
            self.assertIsNone(
                triplet_acceleration_failure(
                    metrics(10),
                    metrics(13),
                    metrics(10),
                    (22, 23, 24),
                    LIMITS,
                    approved=approved,
                )
            )

    def test_size_pumping_is_reported_as_bbox_acceleration(self) -> None:
        failure = triplet_acceleration_failure(
            metrics(10), metrics(10, width=26), metrics(10), (1, 2, 3), LIMITS
        )
        self.assertIn("bounding-box size acceleration", failure["reasons"])
        self.assertEqual(failure["boundingBoxSizeAccelerationPixels"], [12, 0])


class SilhouetteChangeTests(unittest.TestCase):
    def test_identical_masks_do_not_change(self) -> None:
        self.assertEqual(silhouette_change(metrics(10), metrics(10)), 0.0)

    def test_disjoint_masks_change_completely(self) -> None:
        self.assertEqual(silhouette_change(metrics(0), metrics(40)), 1.0)


if __name__ == "__main__":
    unittest.main()
