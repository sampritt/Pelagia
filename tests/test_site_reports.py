import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import test_reference_autocomplete as fixtures
from test_marine import payload, NOW
from pelagia import db as database, site_reports as reports


PROSE = 'Warm water and moderate currents are expected today. Winds peak near 12 knots through the afternoon.'


class SiteReportTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app, _, _ = self.make_app(Path(self.tmp.name))
        self.app.config['OPENAI_API_KEY'] = 'test-secret'
        self.client = self.app.test_client()
        self.clock = patch.object(reports.time, 'time', return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.signup(self.client)

    def post(self, client=None):
        return (client or self.client).post('/api/dive-sites/1/report', headers={'X-Requested-With': 'fetch'})

    def populate(self, data=None, description=True):
        with self.app.app_context():
            db = database.get_db()
            db.execute('''INSERT OR REPLACE INTO marine_forecast_cache
                (site_id, latitude, longitude, payload, fetched_at, expires_at)
                VALUES (1, 54.1, -132.9, ?, ?, ?)''', (json.dumps(data or payload()), NOW, NOW + 900))
            db.execute('INSERT OR REPLACE INTO site_visibility_cache (site_id,cache_date,latitude,longitude,payload) VALUES (1,?,?,?,?)', ('2026-10-25',54.1,-132.9,json.dumps({'status':'no_data'})))
            if description:
                db.execute("INSERT OR REPLACE INTO dive_site_descriptions (dive_site_id, description, model) VALUES (1, 'A rocky boat dive with exposed currents.', 'test')")
            db.commit()

    def test_waits_for_each_cache_without_upstream_work_or_daily_claim(self):
        with patch.object(reports, 'generate') as generate, patch.object(reports.marine, 'fetch') as fetch:
            self.assertEqual(self.post().status_code, 202)
            self.populate(description=False)
            self.assertEqual(self.post().get_json()['reason'], 'dependencies')
            with self.app.app_context():
                self.assertEqual(database.get_db().execute('SELECT COUNT(*) FROM dive_site_reports').fetchone()[0], 0)
            generate.assert_not_called()
            fetch.assert_not_called()
            self.populate()
            generate.return_value = PROSE
            self.assertEqual(self.post().get_json()['report'], PROSE)
            generate.assert_called_once()

    def test_payload_includes_all_sources_and_excludes_personal_exposure_advice(self):
        self.populate()
        with patch.object(reports, 'generate', return_value=PROSE) as generate:
            result = self.post()
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers['Cache-Control'], 'private, no-store')
            data = generate.call_args.args[0]
            self.assertEqual(data['site']['name'], 'Alert Rock')
            self.assertIn('exposed currents', data['description'])
            self.assertNotIn('exposure_recommendation', data)
            self.assertNotIn('recommendations', data['conditions'])
            self.assertEqual(data['date'], '2026-10-25')
            self.assertEqual(data['retrieved_data'], dict(payload(), visibility={'status':'no_data'}))
            self.assertEqual(data['conditions']['current']['moon_phase'], 'Full')
            self.assertIn('season', data)
            self.assertNotIn('user_id', data)
            self.assertNotIn('weight', data)

    def test_warm_cache_shared_across_users_and_survives_dependency_expiry(self):
        self.populate()
        with patch.object(reports, 'generate', return_value=PROSE) as generate:
            self.post()
            other = self.app.test_client()
            self.signup(other, 'another-diver')
            with patch.object(reports.time, 'time', return_value=NOW + 3600):
                self.assertEqual(self.post(other).get_json()['report'], PROSE)
            generate.assert_called_once()

    def test_local_date_rollover_replaces_only_row_after_new_dependencies(self):
        self.populate()
        midnight = datetime(2026, 10, 26, tzinfo=ZoneInfo('Pacific/Galapagos')).timestamp()
        with patch.object(reports, 'generate', return_value=PROSE) as generate:
            self.post()
            # Already the next UTC date, but still the same site-local date.
            with patch.object(reports.time, 'time', return_value=midnight - 1):
                self.assertEqual(self.post().get_json()['date'], '2026-10-25')
            with patch.object(reports.time, 'time', return_value=midnight):
                self.assertEqual(self.post().status_code, 202)
                generate.assert_called_once()
                with self.app.app_context():
                    db = database.get_db()
                    data = payload()
                    for source in (data['hourly'], data['weather']['hourly'], data['weather']['daily']):
                        source['time'] = [t + 86400 for t in source['time']]
                    db.execute('UPDATE marine_forecast_cache SET payload=?, expires_at=?', (json.dumps(data), midnight + 900))
                    db.execute("UPDATE site_visibility_cache SET cache_date='2026-10-26'")
                    db.commit()
                self.assertEqual(self.post().get_json()['date'], '2026-10-26')
            self.assertEqual(generate.call_count, 2)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute('SELECT COUNT(*) FROM dive_site_reports').fetchone()[0], 1)

    def test_missing_fields_expired_cache_and_coordinate_changes_block_generation(self):
        for field in ('wind_speed_10m', 'ocean_current_velocity', 'rainfall_monthly', 'moon_phase'):
            data = payload()
            if field == 'wind_speed_10m':
                data['weather']['hourly'][field] = [None] * len(data['hourly']['time'])
            elif field == 'ocean_current_velocity':
                data['hourly'][field] = [None] * len(data['hourly']['time'])
                data['current'][field] = None
            elif field == 'moon_phase':
                data['weather']['daily'][field] = [None] * len(data['weather']['daily']['time'])
            else:
                data[field] = []
            self.populate(data)
            with patch.object(reports, 'generate') as generate:
                self.assertEqual(self.post().status_code, 202)
                generate.assert_not_called()
        self.populate()
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE marine_forecast_cache SET latitude=0')
            db.commit()
        self.assertEqual(self.post().status_code, 202)
        self.populate()
        with patch.object(reports.time, 'time', return_value=NOW + 901):
            self.assertEqual(self.post().status_code, 202)

    def test_verified_no_description_is_completed_and_unknown_season_is_allowed(self):
        self.populate()
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_site_descriptions SET description=NULL')
            db.commit()
        with patch.object(reports, 'generate', return_value=PROSE) as generate:
            self.assertEqual(self.post().status_code, 200)
            self.assertIsNone(generate.call_args.args[0]['description'])
            self.assertIsNone(generate.call_args.args[0]['season'])

    def test_concurrent_requests_make_one_call_and_release_database_lock(self):
        self.populate()
        entered, release = threading.Event(), threading.Event()
        def generate(_data):
            entered.set()
            self.assertTrue(release.wait(5))
            return PROSE
        with patch.object(reports, 'generate', side_effect=generate) as generate_mock:
            with ThreadPoolExecutor(max_workers=1) as pool:
                job = pool.submit(self.post, self.client)
                try:
                    self.assertTrue(entered.wait(5))
                    other = self.app.test_client()
                    self.signup(other, 'concurrent')
                    self.assertEqual(self.post(other).status_code, 202)
                finally:
                    release.set()
                self.assertEqual(job.result().get_json()['report'], PROSE)
            generate_mock.assert_called_once()

    def test_failure_or_uncertain_attempt_never_retries_same_day(self):
        self.populate()
        with patch.object(reports, 'generate', side_effect=requests.Timeout) as generate:
            self.assertEqual(self.post().get_json()['status'], 'unavailable')
            self.assertEqual(self.post().get_json()['status'], 'unavailable')
            generate.assert_called_once()
        with self.app.app_context():
            db = database.get_db()
            db.execute("UPDATE dive_site_reports SET status='pending', started_at=?", (NOW - 100,))
            db.commit()
        with patch.object(reports, 'generate') as generate:
            self.assertEqual(self.post().get_json()['status'], 'unavailable')
            generate.assert_not_called()

    def test_missing_key_does_not_consume_daily_attempt(self):
        self.populate()
        self.app.config['OPENAI_API_KEY'] = ''
        self.assertEqual(self.post().get_json()['reason'], 'configuration')
        self.app.config['OPENAI_API_KEY'] = 'restored'
        with patch.object(reports, 'generate', return_value=PROSE) as generate:
            self.assertEqual(self.post().get_json()['report'], PROSE)
            generate.assert_called_once()

    def test_security_and_section_order(self):
        self.assertEqual(self.app.test_client().post('/api/dive-sites/1/report').status_code, 302)
        self.assertEqual(self.client.post('/api/dive-sites/1/report').status_code, 403)
        self.assertEqual(self.client.get('/api/dive-sites/1/report').status_code, 405)
        self.assertEqual(self.client.post('/api/dive-sites/999/report', headers={'X-Requested-With': 'fetch'}).status_code, 404)
        html = self.client.get('/dive-sites/1').get_data(as_text=True)
        self.assertIn('id="daily-report" class="site-report"', html)
        self.assertLess(html.index('site-profile-header'), html.index('data-site-report'))
        self.assertLess(html.index('data-site-report'), html.index('data-marine-forecast'))
        self.assertNotIn('test-secret', html)
        self.assertNotIn('data-site-report', self.app.test_client().get('/share/dive-site/1').get_data(as_text=True))

    def test_api_uses_requested_model_no_tools_and_rejects_long_output(self):
        self.populate()
        response = Mock()
        response.json.return_value = {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': PROSE}]}]}
        with patch.object(reports.requests, 'post', return_value=response) as post:
            self.assertEqual(self.post().get_json()['report'], PROSE)
            body = post.call_args.kwargs['json']
            self.assertEqual(body['model'], 'gpt-5.6-luna')
            self.assertNotIn('tools', body)
            self.assertFalse(body['store'])
            self.assertIn('ONLY the supplied', body['instructions'])
            self.assertIn('Do not include wetsuit or exposure recommendations', body['instructions'])
            self.assertIn('ALWAYS write this as a MORNING REPORT', body['instructions'])
            self.assertIn('supplied local_time or request time is later in the day',
                          body['instructions'].replace('\n', ' '))
            self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-secret')
            response.close.assert_called_once()
        with self.app.app_context():
            for text in ('First sentence. Second sentence. Third sentence.', 'First. second. third.',
                         ' '.join(['word'] * 101), '', 'First.\nSecond.'):
                response.json.return_value['output'][0]['content'][0]['text'] = text
                with patch.object(reports.requests, 'post', return_value=response), self.assertRaises(ValueError):
                    reports.generate({})
