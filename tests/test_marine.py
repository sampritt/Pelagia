from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
import test_reference_autocomplete as fixtures
from pelagia import marine, db as database

NOW = datetime(2026, 10, 25, 15, 15, tzinfo=timezone.utc).timestamp()


def payload(zone='Pacific/Galapagos'):
    start = NOW - 15 * 60 - 36 * 3600
    times = [start + i * 3600 for i in range(216)]
    marine_data = dict(timezone=zone, current=dict(time=NOW - 900, ocean_current_velocity=.5,
                sea_level_height_msl=.2, sea_surface_temperature=28.3),
                current_units=dict(zip(marine.FIELDS, ('kn', 'm', '°C'))),
                hourly_units=dict(zip(marine.FIELDS, ('kn', 'm', '°C'))),
                hourly=dict(time=times, ocean_current_velocity=[.4] * len(times),
                            sea_level_height_msl=[(i % 12 if i % 12 <= 6 else 12 - i % 12) / 10 for i in range(len(times))],
                            sea_surface_temperature=[28.1] * len(times)))
    daily_times = [datetime.combine(datetime.fromtimestamp(NOW, ZoneInfo(zone)).date() + timedelta(days=i),
                                    datetime.min.time(), ZoneInfo(zone)).timestamp() for i in range(-1, 7)]
    marine_data['weather'] = dict(timezone=zone,
        hourly_units={'wind_speed_10m': 'kn', 'wind_direction_10m': '°'},
        hourly={'time': times, 'wind_speed_10m': [12.3] * len(times),
                'wind_direction_10m': [225] * len(times)},
        daily_units={'moon_phase': 'fraction'},
        daily={'time': daily_times, 'moon_phase': [.4 + i / 100 for i in range(len(daily_times))]})
    month = datetime(2025, 10, 1, tzinfo=ZoneInfo(zone))
    marine_data['rainfall_monthly'] = [
        {'time': datetime((month.year * 12 + month.month - 1 + i) // 12,
                          (month.month - 1 + i) % 12 + 1, 1, tzinfo=ZoneInfo(zone)).timestamp(),
         'value': 20 + i * 3}
        for i in range(12)
    ]
    return marine_data


def rainfall_payload(zone='Pacific/Galapagos', now=NOW):
    start, end = marine.trailing_month_range(now, ZoneInfo(zone))
    days, values, day = [], [], start
    while day <= end:
        days.append(day.isoformat())
        values.append(1.0)
        day += timedelta(days=1)
    return {'timezone': zone, 'daily_units': {'rain_sum': 'mm'},
            'daily': {'time': days, 'rain_sum': values}}


class MarineRulesTest(unittest.TestCase):
    def test_strength_boundaries(self):
        for value, expected in [(0, 'Light'), (.4999, 'Light'), (.5, 'Moderate'), (.999, 'Moderate'),
                                (1, 'Strong'), (1.999, 'Strong'), (2, 'Very Strong'), (5, 'Very Strong'),
                                (None, '-'), (-1, '-'), (float('nan'), '-'), (True, '-')]:
            self.assertEqual(marine.strength(value), expected)

    def test_moon_phase_nearest_quarter(self):
        for value, expected in [(0, 'New'), (1, 'New'), (.99, 'New'), (.25, 'First Quarter'),
                                (.5, 'Full'), (.75, 'Last Quarter'), (.62, 'Full'), (.63, 'Last Quarter')]:
            self.assertEqual(marine.moon_phase(value), expected)
        for value in (None, -1, 1.1, float('nan'), True):
            self.assertIsNone(marine.moon_phase(value))

    def test_week_has_one_moon_marker_on_closest_day_with_earliest_tie(self):
        for phases, expected_index, expected_phase in [
            ([.46, .49, .50, .53, .57, .61, .65], 2, 'Full'),
            ([.95, .99, .01, .04, .08, .12, .15], 1, 'New'),
            ([.50, .55, .60, .65, .70, .75, .80], 0, 'Full'),
            ([.10, .14, .36, .39, .61, .64, .86], 0, 'New'),
            ([None] * 7, None, None),
        ]:
            with self.subTest(phases=phases):
                data = payload()
                data['weather']['daily']['moon_phase'] = [None, *phases]
                moon = marine.normalize(data, NOW, NOW)['charts']['moon_phase_daily']
                marked = [(i, point['phase']) for i, point in enumerate(moon) if point['phase']]
                self.assertEqual(marked, [] if expected_index is None else [(expected_index, expected_phase)])

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
        marine.validate_weather(data['weather'])
        result = marine.normalize(data, NOW, NOW)
        self.assertEqual(result['current']['strength'], 'Moderate')
        self.assertEqual(result['current']['wind_speed_kn'], 12.3)
        self.assertEqual([len(result['charts'][k]) for k in ('current_daily', 'current_hourly', 'tide_hourly')], [7, 24, 24])
        self.assertEqual(len(result['charts']['wind_hourly']), 24)
        self.assertEqual(result['charts']['wind_hourly'][0], {'time': NOW - 900, 'speed_kn': 12.3, 'direction_deg': 225})
        self.assertEqual(len(result['charts']['moon_phase_daily']), 7)
        self.assertEqual(len(result['charts']['rainfall_monthly']), 12)
        self.assertEqual(result['current']['moon_phase'], 'Full')
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

    def test_weather_validation_rejects_bad_arrays_units_and_ranges(self):
        data = payload()['weather']; data['hourly']['wind_speed_10m'].pop()
        with self.assertRaises(ValueError): marine.validate_weather(data)
        data = payload()['weather']; data['daily_units']['moon_phase'] = '%'
        with self.assertRaises(ValueError): marine.validate_weather(data)
        data = payload()['weather']; data['hourly']['wind_direction_10m'][0] = 361
        self.assertIsNone(marine.validate_weather(data)['hourly']['wind_direction_10m'][0])

    def test_trailing_month_range_and_monthly_rainfall_totals(self):
        zone = ZoneInfo('America/New_York')
        november = datetime(2026, 11, 15, 12, tzinfo=zone).timestamp()
        start, end = marine.trailing_month_range(november, zone)
        self.assertEqual((start.isoformat(), end.isoformat()), ('2025-11-01', '2026-10-31'))
        points = marine.validate_rainfall(rainfall_payload('America/New_York', november), start, end, zone)
        self.assertEqual(len(points), 12)
        self.assertEqual(points[0]['value'], 30)
        self.assertEqual(points[-1]['value'], 31)
        self.assertEqual(datetime.fromtimestamp(points[0]['time'], zone).date(), start)

    def test_rainfall_validation_rejects_gaps_negative_values_and_wrong_units(self):
        zone = ZoneInfo('Pacific/Galapagos')
        start, end = marine.trailing_month_range(NOW, zone)
        data = rainfall_payload()
        data['daily']['time'].pop(); data['daily']['rain_sum'].pop()
        with self.assertRaises(ValueError): marine.validate_rainfall(data, start, end, zone)
        data = rainfall_payload(); data['daily']['rain_sum'][0] = -1
        with self.assertRaises(ValueError): marine.validate_rainfall(data, start, end, zone)
        data = rainfall_payload(); data['daily_units']['rain_sum'] = 'inch'
        with self.assertRaises(ValueError): marine.validate_rainfall(data, start, end, zone)

    def test_daily_wind_maximum_uses_direction_at_peak_and_site_local_days(self):
        data = payload('Asia/Kathmandu')
        weather = data['weather']['hourly']
        zone = ZoneInfo(data['timezone'])
        today = datetime.fromtimestamp(NOW, zone).date()
        indexes = [i for i, t in enumerate(weather['time']) if datetime.fromtimestamp(t, zone).date() == today]
        weather['wind_speed_10m'][indexes[0]] = 25
        weather['wind_direction_10m'][indexes[0]] = 359
        result = marine.normalize(data, NOW, NOW)
        self.assertEqual(result['charts']['wind_daily'][0], {
            'time': datetime.combine(today, datetime.min.time(), zone).timestamp(), 'value': 25, 'direction_deg': 359})
        self.assertEqual(len(result['charts']['wind_daily']), 7)
        data.pop('weather')
        result = marine.normalize(data, NOW, NOW)
        self.assertTrue(all(p['value'] is None for p in result['charts']['wind_daily']))
        self.assertIsNone(result['current']['moon_phase'])

    def test_current_wind_uses_this_hour_preserving_zero_and_missing_data(self):
        data = payload()
        weather = data['weather']['hourly']
        hour = NOW - 900
        index = weather['time'].index(hour)
        weather['wind_speed_10m'][index] = 0
        weather['wind_speed_10m'][index + 1] = 30
        result = marine.normalize(data, NOW, NOW)
        self.assertEqual(result['current']['wind_speed_kn'], 0)
        self.assertEqual(result['current']['timestamps']['wind_speed_10m'], hour)
        weather['wind_speed_10m'][index] = None
        self.assertIsNone(marine.normalize(data, NOW, NOW)['current']['wind_speed_kn'])
        data.pop('weather')
        self.assertIsNone(marine.normalize(data, NOW, NOW)['current']['wind_speed_kn'])

    def test_moon_dates_remain_aligned_when_api_fixed_offset_crosses_dst(self):
        data = payload('America/New_York')
        now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc).timestamp()
        start = datetime(2026, 10, 30, 4, tzinfo=timezone.utc).timestamp()
        phases = [.65, .68, .71, .74, .77, .80, .83, .86]
        data['weather']['utc_offset_seconds'] = -4 * 3600
        data['weather']['daily'] = {'time': [start + i * 86400 for i in range(8)], 'moon_phase': phases}
        result = marine.normalize(data, now, now)
        moon = result['charts']['moon_phase_daily']
        self.assertEqual([point['value'] for point in moon], phases[1:])
        self.assertEqual(moon[2]['time'] - moon[1]['time'], 25 * 3600)


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
        self.classifier = patch('pelagia.marine.water_type.classify_site', return_value={'feature': 'OCEAN', 'water_type': 'salt'})
        self.classify = self.classifier.start(); self.addCleanup(self.classifier.stop)
        self.upstream = patch('pelagia.marine.fetch', return_value=payload()); self.fetch = self.upstream.start(); self.addCleanup(self.upstream.stop)

    def test_page_no_upstream_auth_public_gate_and_no_store(self):
        page = self.client.get('/dive-sites/1')
        self.assertIn(b'data-marine-forecast', page.data)
        self.assertNotIn(b'data-site-current-strength', page.data)
        self.assertNotIn(b'<small>VISIBILITY</small>', page.data)
        self.assertNotIn(b'data-marine-value="strength"', page.data)
        self.assertNotIn(b'<details class="marine-attribution">', page.data)
        chart_titles = [b'<h2>Current</h2>', b'<h2>Tide</h2>', b'<h2>Visibility</h2>', b'<h2>Rain</h2>', b'<h2>Wind</h2>']
        self.assertTrue(all(title in page.data for title in chart_titles))
        self.assertEqual([page.data.index(title) for title in chart_titles], sorted(page.data.index(title) for title in chart_titles))
        self.assertEqual(page.data.count(b'>7 days</button>'), 2)
        self.assertEqual(page.data.count(b'>24h</button>'), 2)
        self.assertIn(b'data-visibility-value', page.data)
        self.assertNotIn(b'<small>Moon phase</small>', page.data)
        self.assertIn(b'data-marine-value="wind"', page.data)
        self.assertNotIn(b'swell', page.data.lower())
        self.assertNotIn(b'(Regional Forecast)', page.data)
        self.assertEqual(page.data.count(b'class="marine-chart-note"'), 3)
        self.fetch.assert_not_called()
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get(self.url).status_code, 302)
        preview = anonymous.get('/share/dive-site/1').data
        self.assertIn(b'Tide level', preview)
        self.assertNotIn(b'<small>Visibility</small>', preview)
        self.assertNotIn(b'<small>Current</small>', preview)
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

    def test_non_ocean_site_skips_open_meteo(self):
        for feature in ('LAND', 'LAKE', 'RIVER', 'UNKNOWN'):
            with self.subTest(feature=feature):
                self.classify.return_value = {'feature': feature, 'water_type': 'fresh'}
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {'status': 'not_ocean', 'feature': feature})
        self.fetch.assert_not_called()

    def test_classification_failure_skips_open_meteo(self):
        self.classify.side_effect = requests.Timeout('offline')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {'status': 'unavailable', 'reason': 'classification'})
        self.fetch.assert_not_called()

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
        marine_response = Mock(); marine_response.json.return_value = payload()
        weather_response = Mock(); weather_response.json.return_value = payload()['weather']
        rainfall_response = Mock(); rainfall_response.json.return_value = rainfall_payload()
        def response_for(url, **kwargs):
            return rainfall_response if 'archive-api' in url else marine_response if 'marine-api' in url else weather_response
        with self.app.app_context(), patch('pelagia.marine.requests.get', side_effect=response_for) as get:
            self.app.config['OPEN_METEO_API_KEY'] = 'secret'
            result = marine.fetch(1, 2, NOW)
            calls = {call.args[0]: call.kwargs for call in get.call_args_list}
            self.assertEqual(set(calls), {'https://customer-marine-api.open-meteo.com/v1/marine',
                                          'https://customer-api.open-meteo.com/v1/forecast',
                                          'https://customer-archive-api.open-meteo.com/v1/archive'})
            self.assertTrue(all(call['params']['apikey'] == 'secret' for call in calls.values()))
            self.assertTrue(all(call['timeout'] == (3, 10) for call in calls.values()))
            self.assertEqual(calls['https://customer-api.open-meteo.com/v1/forecast']['params']['daily'], 'moon_phase')
            archive = calls['https://customer-archive-api.open-meteo.com/v1/archive']['params']
            self.assertEqual((archive['start_date'], archive['end_date']), ('2025-10-01', '2026-09-30'))
            self.assertEqual(archive['daily'], 'rain_sum')
            params = calls['https://customer-marine-api.open-meteo.com/v1/marine']['params']
            self.assertEqual(params['hourly'], 'ocean_current_velocity,sea_level_height_msl,sea_surface_temperature')
            self.assertEqual(params['current'], params['hourly'])
            self.assertIn('weather', result)
        self.upstream.start()

    def test_marine_and_weather_requests_start_concurrently(self):
        self.upstream.stop()
        rendezvous = threading.Barrier(2)
        def response_for(url, **kwargs):
            response = Mock()
            if 'archive-api' in url:
                response.json.return_value = rainfall_payload()
            else:
                rendezvous.wait(timeout=2)
                response.json.return_value = payload() if 'marine-api' in url else payload()['weather']
            return response
        with self.app.app_context(), patch('pelagia.marine.requests.get', side_effect=response_for) as get:
            result = marine.fetch(1, 2, NOW)
        self.assertEqual(get.call_count, 3)
        self.assertIn('weather', result)
        self.assertEqual(len(result['rainfall_monthly']), 12)
        self.upstream.start()
