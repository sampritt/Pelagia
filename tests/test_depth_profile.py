import json
import unittest

from pelagia.depth_profile import depth_profile_chart


class ProfileChartTest(unittest.TestCase):
    def chart(self, points):
        data = {'version': 1, 'source': 'garmin', 'started_at': '2026-10-10T00:00:00+00:00',
                'bottom_time_seconds': 60, 'recording_duration_seconds': 60, 'depth_profile': points}
        class Database:
            def execute(self, *args):
                return self
            def fetchone(self):
                return {'data_json': json.dumps(data)}
        return depth_profile_chart(Database(), 1)

    def test_elapsed_time_and_inverted_depth_geometry(self):
        chart = self.chart([{'elapsed_seconds': t, 'depth_m': d} for t, d in [(0, 0), (15, 20), (60, 0)]])
        self.assertEqual(chart['line'], 'M 44.00,28.00 L 223.00,250.00 L 760.00,28.00')
        self.assertTrue(chart['fill'].endswith('L 760.00,28 L 44.00,28 Z'))

    def test_dense_profile_retains_brief_extremes_and_bounds_svg(self):
        points = [{'elapsed_seconds': i / 2000, 'depth_m': 40 if i == 23457 else 10} for i in range(100000)]
        chart = self.chart(points)
        self.assertEqual(chart['max_depth_m'], 40)
        self.assertIn(',250.00', chart['line'])
        self.assertLessEqual(chart['line'].count(' L '), 1201)
        self.assertEqual(len(points), 100000)

    def test_surface_only_profile_is_finite(self):
        chart = self.chart([{'elapsed_seconds': t, 'depth_m': 0} for t in (0, 60)])
        self.assertNotIn('nan', chart['line'])
        self.assertEqual(chart['max_depth_m'], 0)
