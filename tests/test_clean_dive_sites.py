import unittest

from scripts.clean_dive_sites import clean, name_reason


def site(site_id, name, geography='Ecuador', lat='-0.77', lon='-89.52'):
    return {'master_site_id': site_id, 'dive_site_name': name, 'country_or_area': geography,
            'country_code': 'EC', 'latitude': lat, 'longitude': lon, 'description': '',
            'source_count': '1', 'source_record_count': '1', 'sources': 'source',
            'source_record_ids': site_id, 'source_urls': '', 'licenses_and_attribution': '',
            'data_quality_notes': 'NA'}


class CleanDiveSitesTest(unittest.TestCase):
    def test_missing_geography_is_reviewed_and_original_id_preserved(self):
        rows = [site('a', 'Missing', 'NA'), site('b', 'Valid')]
        kept, invalid, merges = clean(rows)
        self.assertEqual(invalid[0]['master_site_id'], 'a')
        self.assertEqual(kept[0]['legacy_import_id'], '2')
        self.assertEqual(merges, [])

    def test_aliases_require_proximity_and_distinct_sites_stay_separate(self):
        rows = [site('a', 'Kicker Rock'), site('b', 'Kicker Rock (León Dormido)', lat='-0.775'),
                site('c', 'Kicker Rock', lat='-1'), site('d', 'Lighthouse'),
                site('e', 'Lighthouse Wreck'), site('f', 'Lighthouse - The Wreck')]
        kept, invalid, merges = clean(rows)
        self.assertEqual(len(kept), 5)
        self.assertEqual(len(merges), 1)
        self.assertEqual({m['row']['master_site_id'] for m in merges[0]['members']}, {'a', 'b'})
        self.assertIsNone(name_reason(rows[3], rows[4]))
        self.assertIsNone(name_reason(rows[3], rows[5]))

    def test_geographic_suffix(self):
        a = site('a', 'Gordon Rocks, Galapagos')
        b = site('b', 'Gordon Rocks', 'Galápagos Islands')
        self.assertIsNotNone(name_reason(a, b))


if __name__ == '__main__': unittest.main()
