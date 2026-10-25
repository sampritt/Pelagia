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
        self.now = datetime.now(timezone.utc).timestamp()
        self.day = datetime.fromtimestamp(self.now, timezone.utc).date().isoformat()

    def log(self, exposure='3mm', temperature=22, comfort=3, weight=6, weight_rating=3,
            salinity='salt', user=1, site=1, deleted=0, day=None):
        cursor = self.db.execute('''INSERT INTO dives (user_id,dive_site_id,site_name,date,exposure,
            water_temp_c,temperature_rating,weight_kg,weight_rating,water_type,is_deleted)
            VALUES (?,?, 'Test site', ?,?,?,?,?,?,?,?)''',
            (user, site, day or self.day, exposure, temperature, comfort, weight, weight_rating, salinity, deleted))
        self.db.commit()
        return cursor.lastrowid

    def advice(self, temp=22, user=1):
        return recommend(self.db, user, 1, temp, self.now)

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

    def test_prefer_nearby_comfortable_then_nearest_and_recent(self):
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

    def test_weight_requires_matching_exposure_and_latest_site_salinity(self):
        self.log(weight=6)
        self.assertEqual(self.advice()['weight'],'6 kg')
        self.log(exposure='5mm',temperature=5,weight=10)  # Wrong protection, cannot replace weight.
        self.assertEqual(self.advice()['weight'],'6 kg')
        self.log(salinity='fresh', weight=4)
        self.assertEqual(self.advice()['weight'],'4 kg')
        self.log(salinity='none')  # Latest site salinity unknown; don't search backward.
        self.assertIsNone(self.advice()['weight'])

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

    def test_cross_user_privacy_and_site_salinity_from_latest_log(self):
        self.db.execute("INSERT INTO users (username) VALUES ('another')"); self.db.commit()
        self.log(exposure='7mm',user=2,weight=12)
        self.assertEqual(self.advice()['exposure'],'3mm wetsuit')
        self.assertIsNone(self.advice()['weight'])
        self.log(exposure='3mm',site=2,salinity='fresh',weight=4)
        self.assertIsNone(self.advice()['weight']) # The site's latest log still says salt.
        self.log(exposure='3mm',user=2,salinity='fresh',weight=6)
        self.assertEqual(self.advice()['weight'],'4 kg')

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

    def test_belize_84f_does_not_inherit_a_neutral_5mm_log(self):
        for historical_temp in (26.5, (84-32)*5/9):
            self.log(exposure='5mm',temperature=historical_temp,comfort=3,weight=8)
            result=self.advice((84-32)*5/9)
            self.assertEqual(result['exposure'],'swimsuit or shorty')
            self.assertFalse(result['personalized'])
            self.assertIsNone(result['source_dive_id'])
            self.assertIsNone(result['weight'])

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
            older = self.log(exposure='shorty', temperature=28.3, weight=8)
            newer = self.log(exposure='2mm', temperature=28.3, weight=6)
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
