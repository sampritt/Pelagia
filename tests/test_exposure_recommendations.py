from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database
from pelagia.exposure_recommendations import default_exposures, recommend
from test_marine import payload, NOW


class ExposureRecommendationsTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.app, _, _ = self.make_app(Path(tmp.name))
        self.client = self.app.test_client(); self.signup(self.client)
        self.ctx = self.app.app_context(); self.ctx.push(); self.addCleanup(self.ctx.pop)
        self.db = database.get_db()
        classifier = patch('pelagia.marine.water_type.classify_site', return_value={'feature': 'OCEAN', 'water_type': 'salt'})
        classifier.start(); self.addCleanup(classifier.stop)
        self.now = datetime.now(timezone.utc).timestamp()
        self.day = datetime.fromtimestamp(self.now, timezone.utc).date().isoformat()

    def log(self, exposure='3mm', temperature=22, comfort=3, weight=6, weight_rating=3,
            salinity='salt', user=1, site=1, deleted=0, day=None, country=None):
        cursor = self.db.execute('''INSERT INTO dives (user_id,dive_site_id,site_name,country_or_area,date,exposure,
            water_temp_c,temperature_rating,weight_kg,weight_rating,water_type,is_deleted)
            VALUES (?,?, 'Test site', ?,?,?,?,?,?,?,?,?)''',
            (user, site, country, day or self.day, exposure, temperature, comfort, weight, weight_rating, salinity, deleted))
        self.db.commit()
        return cursor.lastrowid

    def advice(self, temp=22, user=1, salinity='salt'):
        return recommend(self.db, user, 1, temp, self.now, salinity)

    def test_default_thresholds_and_missing_temperature(self):
        for fahrenheit, expected in ((81, ('swimsuit','shorty')), (80, ('3mm',)), (69, ('3mm',)),
                (68, ('5mm',)), (61, ('5mm',)), (60, ('7mm',)), (51, ('7mm',)), (50, ('dry suit',)), (40, ('dry suit',))):
            self.assertEqual(default_exposures((fahrenheit - 32)*5/9), expected)
        self.assertIsNone(self.advice(None))
        self.assertIsNone(self.advice(float('nan')))
        result=self.advice(28)
        self.assertEqual(result['exposure'],'swimsuit or shorty')
        self.assertIsNone(result['weight'])
        self.assertFalse(result['personalized'])

    def test_comfortable_dive_overrides_default_and_adjusts_cold_warm_feedback(self):
        self.log(exposure='5mm', temperature=22, comfort=3)
        self.assertEqual(self.advice()['exposure'],'5mm wetsuit')
        self.assertTrue(self.advice()['personalized'])
        self.db.execute('DELETE FROM dives'); self.db.commit()
        self.log(exposure='3mm',comfort=1)
        self.assertEqual(self.advice()['exposure'],'5mm wetsuit')
        self.db.execute('UPDATE dives SET temperature_rating=5'); self.db.commit()
        self.assertEqual(self.advice()['exposure'],'2mm wetsuit')

    def test_prefer_comfortable_then_minimum_exposure(self):
        self.log(exposure='5mm',temperature=23,comfort=3)
        self.log(exposure='3mm',temperature=22,comfort=1)
        self.assertEqual(self.advice()['exposure'],'5mm wetsuit')
        self.log(exposure='3mm',temperature=22,comfort=3)
        self.assertEqual(self.advice()['exposure'],'3mm wetsuit')
        self.log(exposure='2mm',temperature=22,comfort=3)
        self.assertEqual(self.advice()['exposure'],'2mm wetsuit')

    def test_missing_ratings_distant_deleted_future_logs_do_not_personalize(self):
        self.log(exposure='dry suit', temperature=10)
        self.log(exposure='7mm', comfort=None)
        self.log(exposure='7mm', deleted=1)
        self.log(exposure='7mm', day='2099-01-01')
        self.assertEqual(self.advice()['exposure'],'3mm wetsuit')
        self.assertFalse(self.advice()['personalized'])

    def test_weight_requires_matching_exposure_and_classified_site_salinity(self):
        self.log(weight=6)
        self.assertEqual(self.advice()['weight'],'6 kg')
        self.log(exposure='5mm',temperature=5,weight=10)  # Wrong protection, cannot replace weight.
        self.assertEqual(self.advice()['weight'],'6 kg')
        self.log(salinity='fresh', weight=4)
        self.assertEqual(self.advice()['weight'],'6 kg')
        self.assertEqual(self.advice(salinity='fresh')['weight'], '4 kg')
        self.log(salinity='none')
        self.assertEqual(self.advice(salinity='fresh')['weight'], '4 kg')

    def test_kicker_rock_weight_uses_cached_site_classification_despite_site_logs(self):
        self.db.execute("UPDATE dive_sites SET name='Kicker Rock (León Dormido)' WHERE id=1")
        self.db.execute("INSERT INTO users (username) VALUES ('another')")
        self.db.execute("UPDATE users SET weight_unit='lb' WHERE id=1")
        self.db.commit()
        self.log(exposure='5mm', temperature=28.3, weight=8, site=2)
        self.log(exposure=None, temperature=None, comfort=None, weight=None,
                 weight_rating=None, user=2, salinity='salt')
        self.log(exposure=None, temperature=None, comfort=None, weight=None,
                 weight_rating=None, user=2, salinity='none')
        with patch('pelagia.marine.fetch', return_value=payload()):
            response = self.client.get('/api/dive-sites/1/conditions')
        self.assertEqual(response.status_code, 200)
        advice = response.json['recommendations']
        self.assertEqual(advice['exposure'], '5mm wetsuit')
        self.assertEqual(advice['salinity'], 'salt')
        self.assertEqual(advice['weight'], '17.5 lb')

    def test_logged_site_salinity_does_not_override_classification(self):
        self.log(salinity='salt', weight=6)
        self.log(salinity='fresh', weight=4)
        self.assertEqual(self.advice(salinity='salt')['weight'], '6 kg')
        self.assertEqual(self.advice(salinity='fresh')['weight'], '4 kg')

    def test_missing_site_classification_has_no_weight_estimate(self):
        self.log(salinity='salt', weight=6)
        advice = self.advice(salinity=None)
        self.assertIsNone(advice['salinity'])
        self.assertIsNone(advice['weight'])

    def test_weight_requires_neutral_valid_weight_and_is_most_recent(self):
        self.log(weight=6,weight_rating=2)
        self.assertIsNone(self.advice()['weight'])
        self.log(weight=None)
        self.assertIsNone(self.advice()['weight'])
        self.log(weight=8)
        self.log(weight=5)
        self.assertEqual(self.advice()['weight'],'5 kg')
        self.db.execute("UPDATE users SET weight_unit='lb' WHERE id=1"); self.db.commit()
        self.assertEqual(self.advice()['weight'],'11 lb')
        self.log(weight=0)
        self.assertEqual(self.advice()['weight'],'0 lb')

    def test_cross_user_logs_do_not_supply_site_salinity_or_weight(self):
        self.db.execute("INSERT INTO users (username) VALUES ('another')"); self.db.commit()
        self.log(exposure='7mm',user=2,weight=12)
        self.assertEqual(self.advice()['exposure'],'3mm wetsuit')
        self.assertIsNone(self.advice()['weight'])
        self.log(exposure='3mm',site=2,salinity='fresh',weight=4)
        self.assertIsNone(self.advice()['weight'])
        self.assertEqual(self.advice(salinity='fresh')['weight'], '4 kg')
        self.log(exposure='3mm',user=2,salinity='fresh',weight=6)
        self.assertEqual(self.advice(salinity='fresh')['weight'],'4 kg')

    def test_warm_default_can_match_shorty_weight_without_guessing(self):
        self.log(exposure='shorty',temperature=None,comfort=None,weight=3)
        result=self.advice(28)
        self.assertEqual(result['exposure'],'swimsuit or shorty')
        self.assertEqual(result['weight'],'3 kg')

    def test_personalization_is_recomputed_outside_shared_forecast_cache(self):
        self.log(exposure='2mm', temperature=28.3, weight=9)
        with patch('pelagia.marine.fetch',return_value=payload()) as fetch:
            first=self.client.get('/api/dive-sites/1/conditions')
            self.assertEqual(first.json['recommendations']['exposure'],'2mm wetsuit')
            self.db.execute("INSERT INTO users (username) VALUES ('second')"); self.db.commit()
            other=self.app.test_client(); self.signup(other,'second')
            second=other.get('/api/dive-sites/1/conditions')
            self.assertEqual(second.json['recommendations']['exposure'],'swimsuit or shorty')
            self.assertIsNone(second.json['recommendations']['weight'])
            self.assertEqual(fetch.call_count,1)
            self.assertNotIn('recommendations',self.db.execute('SELECT payload FROM marine_forecast_cache').fetchone()[0])

    def test_belize_84f_uses_a_comfortable_5mm_log_within_three_fahrenheit(self):
        for historical_temp in ((82-32)*5/9, (84-32)*5/9):
            dive_id = self.log(exposure='5mm',temperature=historical_temp,comfort=3,weight=8)
            result=self.advice((84-32)*5/9)
            self.assertEqual(result['exposure'],'5mm wetsuit')
            self.assertTrue(result['personalized'])
            self.assertEqual(result['source_dive_id'], dive_id)
            self.assertEqual(result['weight'], '8 kg')

    def test_gordon_rocks_83f_uses_comfortable_5mm_from_82f_with_history_link(self):
        self.db.execute("UPDATE dive_sites SET name='Gordon Rocks' WHERE id=1")
        self.log(exposure='5mm', temperature=(82-32)*5/9, comfort=3, weight=8)
        dive_id = self.log(exposure='5mm', temperature=(82-32)*5/9, comfort=3, weight=8)
        forecast = payload()
        forecast['current']['sea_surface_temperature'] = (83-32)*5/9
        with patch('pelagia.marine.fetch', return_value=forecast):
            response = self.client.get('/api/dive-sites/1/conditions')
        self.assertEqual(response.status_code, 200)
        advice = response.json['recommendations']
        self.assertEqual(advice['exposure'], '5mm wetsuit')
        self.assertTrue(advice['personalized'])
        self.assertEqual(advice['source_dive_url'], f'/dive/{dive_id}')
        self.assertEqual(advice['weight'], '8 kg')

    def test_personal_temperature_window_is_inclusive_three_fahrenheit(self):
        current_temp = (83-32)*5/9
        for logged_fahrenheit in (80, 86, 79.99, 86.01):
            with self.subTest(logged_fahrenheit=logged_fahrenheit):
                self.db.execute('DELETE FROM dives')
                dive_id = self.log(exposure='5mm', temperature=(logged_fahrenheit-32)*5/9)
                result = self.advice(current_temp)
                within_range = 80 <= logged_fahrenheit <= 86
                self.assertEqual(result['exposure'], '5mm wetsuit' if within_range else 'swimsuit or shorty')
                self.assertEqual(result['source_dive_id'], dive_id if within_range else None)
                self.assertEqual(result['personalized'], within_range)

    def test_minimum_exposure_wins_over_more_frequent_exposure(self):
        self.log(exposure='5mm', temperature=28, site=2)
        self.log(exposure='5mm', temperature=28, site=2)
        supporting_dive = self.log(exposure='3mm', temperature=28.3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '3mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)
        self.assertTrue(result['personalized'])

    def test_same_region_history_wins_over_closer_measurements_elsewhere(self):
        self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id IN (1,2)")
        supporting_dive = self.log(exposure='5mm', temperature=28, site=2)
        for _ in range(3):
            self.log(exposure='3mm', temperature=28.3, site=3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '5mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_without_regional_history_use_closest_global_measurement(self):
        self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id=1")
        for _ in range(3):
            self.log(exposure='5mm', temperature=28, site=3)
        supporting_dive = self.log(exposure='3mm', temperature=28.3, site=3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '3mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_existing_regional_history_without_qualifying_feedback_uses_default(self):
        self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id=1")
        for temperature, comfort in ((22, 3), (28.3, None), (None, 3)):
            with self.subTest(temperature=temperature, comfort=comfort):
                self.db.execute('DELETE FROM dives')
                self.log(exposure='5mm', temperature=temperature, comfort=comfort)
                self.log(exposure='3mm', temperature=28.3, site=3)
                result = self.advice(28.3)
                self.assertEqual(result['exposure'], 'swimsuit or shorty')
                self.assertIsNone(result['source_dive_id'])

    def test_deleted_future_and_other_users_regional_logs_allow_global_fallback(self):
        self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id=1")
        self.db.execute("INSERT INTO users (username) VALUES ('other-diver')")
        self.db.commit()
        self.log(exposure='3mm', temperature=28.3, deleted=1)
        self.log(exposure='3mm', temperature=28.3, day='2099-01-01')
        self.log(exposure='3mm', temperature=28.3, user=2)
        supporting_dive = self.log(exposure='5mm', temperature=28, site=3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '5mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_recorded_region_matches_case_and_spaces_without_catalog_site(self):
        self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id=1")
        supporting_dive = self.log(exposure='5mm', temperature=28, site=None, country='  kOmOdO  ')
        self.log(exposure='3mm', temperature=28.3, site=3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '5mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_missing_site_region_uses_closest_global_history(self):
        for region in (None, '', '   '):
            with self.subTest(region=region):
                self.db.execute('UPDATE dive_sites SET country_or_area=? WHERE id=1', (region,))
                self.db.execute('DELETE FROM dives')
                self.log(exposure='5mm', temperature=28, country='Komodo')
                supporting_dive = self.log(exposure='3mm', temperature=28.3, site=3)
                self.assertEqual(self.advice(28.3)['source_dive_id'], supporting_dive)

    def test_minimum_comfortable_exposure_wins_even_at_a_farther_temperature(self):
        self.log(exposure='5mm', temperature=28.3)
        supporting_dive = self.log(exposure='3mm', temperature=28)
        for _ in range(3):
            self.log(exposure='5mm', temperature=28.3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '3mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_minimum_comfortable_exposure_applies_to_regional_and_global_history(self):
        for has_regional_history in (True, False):
            with self.subTest(has_regional_history=has_regional_history):
                self.db.execute('DELETE FROM dives')
                self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id=1")
                self.db.execute('UPDATE dive_sites SET country_or_area=? WHERE id=2',
                                ('Komodo' if has_regional_history else 'Bonaire',))
                supporting_dive = self.log(exposure='3mm', temperature=28, site=2)
                for _ in range(3):
                    self.log(exposure='5mm', temperature=28.3, site=2)
                result = self.advice(28.3)
                self.assertEqual(result['exposure'], '3mm wetsuit')
                self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_minimum_exposure_uses_protection_order_across_all_supported_types(self):
        for lighter, heavier, expected in (
            ('swimsuit', 'shorty', 'swimsuit'), ('shorty', '2mm', 'shorty'),
            ('2mm', '3mm', '2mm wetsuit'), ('3mm', '5mm', '3mm wetsuit'),
            ('5mm', '6mm', '5mm wetsuit'), ('6mm', '7mm', '6mm wetsuit'),
            ('7mm', 'dry suit', '7mm wetsuit'),
        ):
            with self.subTest(lighter=lighter, heavier=heavier):
                self.db.execute('DELETE FROM dives')
                supporting_dive = self.log(exposure=lighter, temperature=28)
                self.log(exposure=heavier, temperature=28.3)
                result = self.advice(28.3)
                self.assertEqual(result['exposure'], expected)
                self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_comfortable_feedback_is_preferred_at_the_same_closest_temperature(self):
        supporting_dive = self.log(exposure='5mm', temperature=28.3)
        for _ in range(3):
            self.log(exposure='3mm', temperature=28.3, comfort=1)
        self.assertEqual(self.advice(28.3)['source_dive_id'], supporting_dive)

    def test_api_refreshes_region_scope_and_history_outside_forecast_cache(self):
        self.db.execute("UPDATE dive_sites SET country_or_area='Komodo' WHERE id IN (1,2)")
        regional_dive = self.log(exposure='5mm', temperature=28, site=2)
        global_dive = self.log(exposure='3mm', temperature=28.3, site=3)
        with patch('pelagia.marine.fetch', return_value=payload()) as fetch:
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertEqual(advice['exposure'], '5mm wetsuit')
            self.assertEqual(advice['source_dive_url'], f'/dive/{regional_dive}')
            self.db.execute('UPDATE dives SET is_deleted=1 WHERE id=?', (regional_dive,))
            self.db.commit()
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertEqual(advice['exposure'], '3mm wetsuit')
            self.assertEqual(advice['source_dive_url'], f'/dive/{global_dive}')
            self.assertEqual(fetch.call_count, 1)

    def test_only_qualifying_personal_logs_can_lower_exposure(self):
        self.db.execute("INSERT INTO users (username) VALUES ('other-diver')")
        self.db.commit()
        self.log(exposure='5mm', temperature=28)
        supporting_dive = self.log(exposure='5mm', temperature=28)
        for _ in range(3):
            self.log(exposure='3mm', temperature=28.3, user=2)
            self.log(exposure='3mm', temperature=28.3, deleted=1)
            self.log(exposure='3mm', temperature=28.3, day='2099-01-01')
            self.log(exposure='3mm', temperature=28.3, comfort=None)
            self.log(exposure='3mm', temperature=26)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '5mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_comfortable_logs_take_priority_over_closer_cold_feedback(self):
        supporting_dive = self.log(exposure='5mm', temperature=28)
        for _ in range(3):
            self.log(exposure='3mm', temperature=28.3, comfort=1)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '5mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_minimum_exposure_history_uses_closest_temperature_then_recency(self):
        self.log(exposure='3mm', temperature=28)
        closest = self.log(exposure='3mm', temperature=28.3)
        self.log(exposure='3mm', temperature=28.6)
        self.log(exposure='5mm', temperature=28.3)
        self.assertEqual(self.advice(28.3)['source_dive_id'], closest)
        newest = self.log(exposure='3mm', temperature=28.3)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '3mm wetsuit')
        self.assertEqual(result['source_dive_id'], newest)

    def test_without_comfortable_logs_adjust_the_closest_recorded_suit(self):
        self.log(exposure='5mm', temperature=28, comfort=1)
        self.log(exposure='5mm', temperature=28, comfort=1)
        supporting_dive = self.log(exposure='3mm', temperature=28.3, comfort=1)
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '5mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_without_comfortable_logs_choose_minimum_adjusted_exposure(self):
        self.log(exposure='3mm', temperature=28.3, comfort=1)  # Suggests 5mm.
        supporting_dive = self.log(exposure='5mm', temperature=28.3, comfort=5)  # Suggests 3mm.
        self.log(exposure='shorty', temperature=28, comfort=5)  # More distant fallback.
        result = self.advice(28.3)
        self.assertEqual(result['exposure'], '3mm wetsuit')
        self.assertEqual(result['source_dive_id'], supporting_dive)

    def test_api_refreshes_minimum_exposure_and_history_outside_forecast_cache(self):
        self.log(exposure='5mm', temperature=28.3)
        self.log(exposure='5mm', temperature=28.3)
        supporting_dive = self.log(exposure='3mm', temperature=28.3, weight=6)
        with patch('pelagia.marine.fetch', return_value=payload()) as fetch:
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertEqual(advice['exposure'], '3mm wetsuit')
            self.assertEqual(advice['source_dive_url'], f'/dive/{supporting_dive}')
            self.assertEqual(advice['weight'], '6 kg')
            self.log(exposure='5mm', temperature=28.3)
            new_supporting_dive = self.log(exposure='2mm', temperature=28.3, weight=4)
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertEqual(advice['exposure'], '2mm wetsuit')
            self.assertEqual(advice['source_dive_url'], f'/dive/{new_supporting_dive}')
            self.assertEqual(advice['weight'], '4 kg')
            self.assertEqual(fetch.call_count, 1)

    def test_personal_feedback_adjusts_logged_suit_without_default_band_limit(self):
        for comfort, expected in ((1, '6mm wetsuit'), (2, '6mm wetsuit'), (3, '5mm wetsuit'),
                                  (4, '3mm wetsuit'), (5, '3mm wetsuit')):
            with self.subTest(comfort=comfort):
                self.db.execute('DELETE FROM dives')
                dive_id = self.log(exposure='5mm', temperature=(82-32)*5/9, comfort=comfort)
                result = self.advice((83-32)*5/9)
                self.assertEqual(result['exposure'], expected)
                self.assertEqual(result['source_dive_id'], dive_id)

    def test_history_identifies_logs_that_confirm_or_adjust_the_default(self):
        for exposure, temperature, comfort, expected, personalized in (
            ('3mm', 22, 3, '3mm wetsuit', False),
            ('5mm', 22, 5, '3mm wetsuit', False),
            ('shorty', 29, 3, 'shorty', False),
            ('5mm', 22, 3, '5mm wetsuit', True),
        ):
            with self.subTest(exposure=exposure, comfort=comfort):
                self.db.execute('DELETE FROM dives')
                dive_id = self.log(exposure=exposure, temperature=temperature, comfort=comfort)
                result = self.advice(temperature)
                self.assertEqual(result['exposure'], expected)
                self.assertEqual(result['personalized'], personalized)
                self.assertEqual(result['source_dive_id'], dive_id)

    def test_history_links_to_nearest_comfortable_dive_with_recent_tiebreak(self):
        self.log(exposure='5mm', temperature=23, comfort=3)
        self.log(exposure='3mm', temperature=22, comfort=1)
        nearest = self.log(exposure='3mm', temperature=22, comfort=3)
        self.assertEqual(self.advice()['source_dive_id'], nearest)
        newest = self.log(exposure='2mm', temperature=22, comfort=3)
        self.assertEqual(self.advice()['source_dive_id'], newest)
        self.log(exposure='3mm', temperature=22, comfort=3, deleted=1)
        self.log(exposure='3mm', temperature=22, comfort=3, day='2099-01-01')
        self.assertEqual(self.advice()['source_dive_id'], newest)

    def test_api_provides_history_links_for_confirmation_and_override(self):
        with patch('pelagia.marine.fetch', return_value=payload()):
            for exposure, personalized in (('shorty', False), ('2mm', True)):
                self.db.execute('DELETE FROM dives')
                dive_id = self.log(exposure=exposure, temperature=28.3)
                advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
                self.assertEqual(advice['personalized'], personalized)
                self.assertEqual(advice['source_dive_id'], dive_id)
                self.assertEqual(advice['source_dive_url'], f'/dive/{dive_id}')
                self.assertEqual(self.client.get(advice['source_dive_url']).status_code, 200)
            self.db.execute("INSERT INTO users (username) VALUES ('no-history')")
            self.db.commit()
            other = self.app.test_client()
            self.signup(other, 'no-history')
            advice = other.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertIsNone(advice['source_dive_id'])
            self.assertNotIn('source_dive_url', advice)
            self.assertIsNone(advice['weight'])

    def test_site_template_emphasizes_equipment_and_weight(self):
        response = self.client.get('/dive-sites/1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<strong data-exposure-name></strong>', response.data)
        self.assertIn(b'Estimated weight: <strong data-weight-advice>-</strong>', response.data)
        self.assertIn(b'Based on your dive log <a data-exposure-history-link', response.data)
        self.assertIn(b'aria-label="View dive log history supporting this recommendation">history</a>', response.data)

    def test_history_and_units_refresh_after_log_and_profile_changes(self):
        with patch('pelagia.marine.fetch', return_value=payload()) as fetch:
            older = self.log(exposure='2mm', temperature=28.3, weight=8)
            newer = self.log(exposure='shorty', temperature=28.3, weight=6)
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertEqual(advice['source_dive_url'], f'/dive/{newer}')
            self.db.execute('UPDATE dives SET is_deleted=1 WHERE id=?', (newer,))
            self.db.execute("UPDATE users SET weight_unit='lb' WHERE id=1")
            self.db.commit()
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertEqual(advice['source_dive_url'], f'/dive/{older}')
            self.assertEqual(advice['weight'], '17.5 lb')
            self.db.execute('UPDATE dives SET temperature_rating=NULL, weight_rating=NULL WHERE id=?', (older,))
            self.db.commit()
            advice = self.client.get('/api/dive-sites/1/conditions').json['recommendations']
            self.assertIsNone(advice['source_dive_id'])
            self.assertNotIn('source_dive_url', advice)
            self.assertIsNone(advice['weight'])
            self.assertEqual(fetch.call_count, 1)

    def test_personalization_still_allows_a_nearby_one_step_preference(self):
        self.log(exposure='shorty',temperature=29,comfort=1)
        self.assertEqual(self.advice(29)['exposure'],'2mm wetsuit')
        self.assertTrue(self.advice(29)['personalized'])

    def test_imperial_weight_is_compact_and_never_borrows_another_users_log(self):
        self.log(weight=8)
        self.db.execute("UPDATE users SET weight_unit='lb' WHERE id=1"); self.db.commit()
        self.assertEqual(self.advice()['weight'],'17.5 lb')
        self.db.execute("INSERT INTO users (username) VALUES ('no-history')");self.db.commit()
        self.assertIsNone(self.advice(user=2)['weight'])
