import json
import tempfile
import unittest
from pathlib import Path

from scripts.recover_location_pending_sites import Countries, near_name


class RecoveryTest(unittest.TestCase):
    def test_name_matching_does_not_merge_distinct_subsites(self):
        self.assertEqual(near_name('Crystal Rock Dive Site', 'Crystal Rock'), 'same name without dive-site label')
        self.assertEqual(near_name('Lighthouse', 'Lighthouse Wreck'), '')
        self.assertEqual(near_name('Monad Shoel', 'Monad Shoal'), '')  # requires manual alias review

    def test_country_boundary_and_offshore_guard(self):
        feature = {'type': 'Feature', 'properties': {'name': 'Testland', 'ISO3166-1-Alpha-2': 'TT'},
                   'geometry': {'type': 'Polygon', 'coordinates': [[[0,0], [1,0], [1,1], [0,1], [0,0]]]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'countries.json'
            path.write_text(json.dumps({'type': 'FeatureCollection', 'features': [feature]}))
            countries = Countries(path)
            self.assertEqual(countries.locate(0.5, 0.5, '')[:3], ('Testland', 'TT', 'inside country boundary'))
            self.assertEqual(countries.locate(0.5, 1.1, 'TT')[1], 'TT')
            self.assertEqual(countries.locate(0.5, 1.1, '')[1], '')


if __name__ == '__main__': unittest.main()
