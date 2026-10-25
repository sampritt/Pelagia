from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

import requests
import test_reference_autocomplete as fixtures
from pelagia import marine, db as database

NOW = datetime(2026, 10, 25, 15, 15, tzinfo=timezone.utc).timestamp()


def payload(zone='Pacific/Galapagos'):
    start = NOW - 15 * 60 - 36 * 3600
    times = [start + i * 3600 for i in range(216)]
    return dict(timezone=zone, current=dict(time=NOW - 900, ocean_current_velocity=.5,
                sea_level_height_msl=.2, sea_surface_temperature=28.3),
                current_units=dict(zip(marine.FIELDS, ('kn', 'm', '°C'))),
                hourly_units=dict(zip(marine.FIELDS, ('kn', 'm', '°C'))),
                hourly=dict(time=times, ocean_current_velocity=[.4] * len(times),
                            sea_level_height_msl=[(i % 12 if i % 12 <= 6 else 12 - i % 12) / 10 for i in range(len(times))],
                            sea_surface_temperature=[28.1] * len(times)))


class MarineRulesTest(unittest.TestCase):
    def test_strength_boundaries(self):
        for value, expected in [(0, 'Light'), (.4999, 'Light'), (.5, 'Moderate'), (.999, 'Moderate'),
                                (1, 'Strong'), (1.999, 'Strong'), (2, 'Very Strong'), (5, 'Very Strong'),
                                (None, '-'), (-1, '-'), (float('nan'), '-'), (True, '-')]:
            self.assertEqual(marine.strength(value), expected)

    def test_tide_phase_extrema_slope_plateau_gaps(self):
        def phase(values, hour):
            return marine.tide_phase([dict(time=i * 3600, value=v) for i, v in enumerate(values)], hour * 3600)
        self.assertEqual(phase([0, 1, 2, 1, 0], 2), 'High')
        self.assertEqual(phase([0, 1, 2, 1, 0], 1), 'High')
        self.assertEqual(phase([0, 1, 2, 1, 0], 3), 'High')
        self.assertEqual(phase([2, 1, 0, 1, 2], 2), 'Low')
        self.assertEqual(phase([0, 1, 2, 3, 4], 2.2), 'Rising')
        self.assertEqual(phase([4, 3, 2, 1, 0], 2.2), 'Falling')
        self.assertEqual(phase([0, 1, 2, 2, 1, 0], 2.5), 'High')
        self.assertEqual(phase([0, 0, 0, 0], 1.5), '-')
        self.assertEqual(phase([0, None, 2, None, 0], 2), '-')
        self.assertEqual(phase([0, 2, 0, 2, 0], 1.5), 'High')  # tie: earlier
        self.assertEqual(marine.tide_phase([dict(time=0, value=0), dict(time=7200, value=2), dict(time=10800, value=0)], 7200), '-')

    def test_normalize_fallback_partial_and_window_sizes(self):
        data = marine.validate(payload())
        result = marine.normalize(data, NOW, NOW)
        self.assertEqual(result['current']['strength'], 'Moderate')
        self.assertEqual([len(result['charts'][k]) for k in ('current_daily', 'current_hourly', 'tide_hourly')], [7, 48, 24])
        self.assertEqual(result['charts']['current_hourly'][0]['time'], NOW - 900)
        data['current']['time'] = NOW - 3600
        self.assertEqual(marine.normalize(data, NOW, NOW)['current']['temperature_c'], 28.1)
        data['hourly']['sea_surface_temperature'] = [None] * len(data['hourly']['time'])
        self.assertIsNone(marine.normalize(data, NOW, NOW)['current']['temperature_c'])
        self.assertEqual(marine.normalize(data, NOW, NOW)['current']['strength'], 'Light')

    def test_site_day_dst_and_daily_maxima(self):
        for zone in ('Pacific/Galapagos', 'America/New_York', 'Asia/Kathmandu'):
            data = marine.validate(payload(zone))
            result = marine.normalize(data, NOW, NOW)
            self.assertEqual(len(result['charts']['current_daily']), 7)
            self.assertTrue(all(p['value'] == .4 for p in result['charts']['current_daily']))
        data = payload('America/New_York')
        fall_back = datetime(2026, 11, 1, 5, 15, tzinfo=timezone.utc).timestamp()
        data['hourly']['time'] = [fall_back - 900 + (i - 36) * 3600 for i in range(216)]
        result = marine.normalize(data, fall_back, fall_back)
        days = result['charts']['current_daily']
        self.assertEqual(days[1]['time'] - days[0]['time'], 25 * 3600)
        self.assertEqual(result['charts']['current_hourly'][1]['time'] - result['charts']['current_hourly'][0]['time'], 3600)

    def test_validation_rejects_bad_arrays_and_units(self):
        data = payload(); data['hourly']['ocean_current_velocity'].pop()
        with self.assertRaises(ValueError): marine.validate(data)
        data = payload(); data['hourly_units']['ocean_current_velocity'] = 'km/h'
        with self.assertRaises(ValueError): marine.validate(data)
        data = payload(); data['hourly']['time'][2] += 1
        with self.assertRaises(ValueError): marine.validate(data)
        data = payload(); data['hourly'].pop('sea_surface_temperature')
        self.assertTrue(all(v is None for v in marine.validate(data)['hourly']['sea_surface_temperature']))


class MarineEndpointTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.app, _, _ = self.make_app(Path(temp.name))
        self.client = self.app.test_client()
        self.url = '/api/dive-sites/1/conditions'
        self.clock = patch('pelagia.marine.time.time', return_value=NOW); self.clock.start(); self.addCleanup(self.clock.stop)
        self.signup(self.client)
        self.upstream = patch('pelagia.marine.fetch', return_value=payload()); self.fetch = self.upstream.start(); self.addCleanup(self.upstream.stop)

    def test_page_no_upstream_auth_public_gate_and_no_store(self):
        page = self.client.get('/dive-sites/1')
        self.assertIn(b'data-marine-forecast', page.data)
        self.assertIn(b'data-site-current-strength>-</span>', page.data)
        self.assertNotIn(b'data-marine-value="strength"', page.data)
        self.assertNotIn(b'<details class="marine-attribution">', page.data)
        self.assertIn(b'Current Strength (Regional Forecast)', page.data)
        self.assertIn(b'Tide Level (Regional Forecast)', page.data)
        self.fetch.assert_not_called()
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(self.url).status_code, 302)
        self.assertIn(b'Tide level', anonymous.get('/share/dive-site/1').data)
        self.fetch.assert_not_called()
        self.assertEqual(self.client.get(self.url).headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get('/api/dive-sites/999999/conditions').status_code, 404)

    def test_cache_expiry_coordinates_and_pending(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.get(self.url); self.assertEqual(self.fetch.call_count, 1)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE marine_forecast_cache SET expires_at=0, lease_until=?', (NOW + 10,)); db.commit()
        self.assertEqual(self.client.get(self.url).status_code, 202)
        with self.app.app_context():
            db = database.get_db(); db.execute('UPDATE marine_forecast_cache SET lease_until=0'); db.commit()
        self.client.get(self.url); self.assertEqual(self.fetch.call_count, 2)
        with self.app.app_context():
            db = database.get_db(); db.execute('UPDATE dive_sites SET latitude=1 WHERE id=1'); db.commit()
        self.client.get(self.url); self.assertEqual(self.fetch.call_count, 3)

    def test_logged_temperature_is_rendered_without_coordinates_in_account_units(self):
        with self.app.app_context():
            db = database.get_db()
            db.executemany("INSERT INTO dives (user_id, dive_site_id, site_name, date, water_temp_c) VALUES (1, 1, 'Alert Rock', ?, ?)",
                           [(date.today().isoformat(), temperature) for temperature in (20, 24, None)])
            db.execute('UPDATE dive_sites SET latitude=NULL WHERE id=1')
            db.commit()
        page = self.client.get('/dive-sites/1')
        self.assertIn('data-site-water-temperature>22°C</span>'.encode(), page.data)
        self.assertNotIn(b'data-marine-value="temperature"', page.data)
        self.assertIn(b'data-coordinates="false"', page.data)
        with self.app.app_context():
            db = database.get_db()
            db.execute("UPDATE users SET temperature_unit='f' WHERE id=1")
            db.commit()
        self.assertIn('data-site-water-temperature>72°F</span>'.encode(), self.client.get('/dive-sites/1').data)
        self.fetch.assert_not_called()

    def test_temperature_prefers_recent_dive_median_and_recomputes_outside_forecast_cache(self):
        self.assertEqual(self.client.get(self.url).json['current']['temperature_c'], 28.3)
        with self.app.app_context():
            db = database.get_db()
            db.executemany("INSERT INTO dives (user_id, dive_site_id, site_name, date, water_temp_c) VALUES (1, 1, 'Alert Rock', ?, ?)",
                           [(date.today().isoformat(), temperature) for temperature in (18, 22, None)])
            db.commit()
        result = self.client.get(self.url).json
        self.assertEqual(result['current']['temperature_c'], 20)
        self.assertEqual(result['recommendations']['exposure'], '5mm wetsuit')
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dives SET water_temp_c=0')
            db.commit()
        self.assertEqual(self.client.get(self.url).json['current']['temperature_c'], 0)
        self.assertEqual(self.fetch.call_count, 1)

    def test_temperature_falls_back_for_missing_old_or_deleted_measurements(self):
        for temperature, age, deleted in ((None, 0, 0), (12, 8, 0), (12, 0, 1)):
            with self.subTest(temperature=temperature, age=age, deleted=deleted):
                with self.app.app_context():
                    db = database.get_db()
                    db.execute('DELETE FROM dives')
                    db.execute("INSERT INTO dives (user_id, dive_site_id, site_name, date, water_temp_c, is_deleted) VALUES (1, 1, 'Alert Rock', ?, ?, ?)",
                               ((date.today() - timedelta(days=age)).isoformat(), temperature, deleted))
                    db.commit()
                self.assertIn(b'data-marine-value="temperature">-</span>', self.client.get('/dive-sites/1').data)
                self.assertEqual(self.client.get(self.url).json['current']['temperature_c'], 28.3)

    def test_failure_cooldown_and_missing_coordinates(self):
        self.fetch.side_effect = requests.Timeout()
        self.assertEqual(self.client.get(self.url).status_code, 503)
        self.assertEqual(self.client.get(self.url).status_code, 503)
        self.assertEqual(self.fetch.call_count, 1)
        with self.app.app_context():
            db = database.get_db(); db.execute('UPDATE dive_sites SET latitude=NULL WHERE id=1'); db.commit()
        self.assertEqual(self.client.get(self.url).json['reason'], 'coordinates')
        self.assertEqual(self.fetch.call_count, 1)

    def test_midnight_expiry_and_idempotent_schema(self):
        # 23:55 at Gordon Rocks: cache lifetime must stop at midnight.
        late = datetime(2026, 10, 26, 5, 55, tzinfo=timezone.utc).timestamp()
        with patch('pelagia.marine.time.time', return_value=late):
            self.client.get(self.url)
        with self.app.app_context():
            database.init_db()
            row = database.get_db().execute('SELECT * FROM marine_forecast_cache').fetchone()
            self.assertEqual(row['expires_at'], late + 300)

    def test_concurrent_workers_share_claim_without_holding_database_lock(self):
        entered, release = threading.Event(), threading.Event()
        def waiting_fetch(*args):
            self.assertFalse(database.get_db().in_transaction)
            entered.set()
            self.assertTrue(release.wait(5))
            return payload()
        self.fetch.side_effect = waiting_fetch
        other = self.app.test_client(); self.signup(other)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(lambda: other.get(self.url))
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.client.get(self.url).status_code, 202)
            finally:
                release.set()
            self.assertEqual(pending.result().status_code, 200)
        self.assertEqual(self.fetch.call_count, 1)

    def test_customer_request_configuration(self):
        self.upstream.stop()
        response = Mock(); response.json.return_value = payload()
        with self.app.app_context(), patch('pelagia.marine.requests.get', return_value=response) as get:
            self.app.config['OPEN_METEO_API_KEY'] = 'secret'
            marine.fetch(1, 2)
            self.assertEqual(get.call_args.args[0], 'https://customer-marine-api.open-meteo.com/v1/marine')
            self.assertEqual(get.call_args.kwargs['params']['apikey'], 'secret')
            self.assertEqual(get.call_args.kwargs['timeout'], (3, 10))
        self.upstream.start()
