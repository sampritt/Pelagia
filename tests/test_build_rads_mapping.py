import importlib.util
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_rads_mapping.py"
SPEC = importlib.util.spec_from_file_location("build_rads_mapping", SCRIPT)
build = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(build)


class BuildRadsMappingTest(unittest.TestCase):
    def median(self, values):
        grids = [np.array([[value]], dtype=float) for value in values]
        return build.median_dayofyear_grid(grids)[0, 0]

    def test_ordinary_median_rejects_single_year_outlier(self):
        self.assertEqual(self.median([97, 91, 103, 112, 359]), 103)

    def test_balanced_new_year_cluster_is_unwrapped(self):
        self.assertEqual(self.median([354, 359, 2, 5, 10]), 2)

    def test_requires_three_valid_years(self):
        self.assertTrue(np.isnan(self.median([247, 272, np.nan, np.nan, np.nan])))

    def test_menjangan_five_year_boundaries(self):
        onset = self.median([247, 272, 332, 292, 251])
        demise = self.median([97, 91, 103, 112, 359])
        self.assertEqual(build.as_iso_day(onset), "2025-09-29")
        self.assertEqual(build.as_iso_day(demise), "2025-04-13")


if __name__ == "__main__":
    unittest.main()
