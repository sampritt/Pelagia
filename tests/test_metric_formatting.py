import unittest

from pelagia.metrics import format_metric


class MetricFormattingTest(unittest.TestCase):
    def test_whole_metrics(self):
        for value, expected in ((31.1234, "31"), (31.5, "32"), (0, "0"), (-2.6, "-3"), (-2.5, "-2")):
            with self.subTest(value=value):
                self.assertEqual(format_metric(value), expected)

    def test_weight_uses_nearest_half(self):
        for value, expected in ((8, "8"), (8.24, "8"), (8.25, "8.5"), (8.74, "8.5"), (8.75, "9"), (7.25747792, "7.5")):
            with self.subTest(value=value):
                self.assertEqual(format_metric(value, weight=True), expected)
