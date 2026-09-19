from __future__ import annotations

import unittest

import numpy as np

from validate_source_correspondence import transformed_source


class SourceCorrespondenceRegressionTests(unittest.TestCase):
    def test_shared_translation_preserves_exact_source_pixels(self) -> None:
        source = np.zeros((4, 8, 3), dtype=np.uint8)
        source[:, 2:6] = [10, 20, 30]
        transformed = transformed_source(source, (4, 4), (-2, 0))
        self.assertTrue(np.all(transformed == [10, 20, 30]))

    def test_shared_translation_does_not_recenter_content(self) -> None:
        source = np.zeros((4, 8, 3), dtype=np.uint8)
        source[1, 3] = [1, 2, 3]
        transformed = transformed_source(source, (4, 4), (-2, 0))
        self.assertTrue(np.array_equal(transformed[1, 1], [1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
