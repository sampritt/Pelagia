import base64
import json
import os
import subprocess
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import pandas as pd
from pelagia import visibility, marine

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp()


class VisibilityTest(unittest.TestCase):
    def test_inclusive_thresholds(self):
        for value, label in ((.05, 'excellent'), (.050001, 'good'), (.1, 'good'),
                             (.100001, 'fair'), (.2, 'fair'), (.200001, 'poor'),
                             (.3, 'poor'), (.300001, 'very poor')):
            self.assertEqual(visibility.clarity(value), label)
        for value in (None, 0, -1, float('nan'), float('inf')):
            self.assertIsNone(visibility.clarity(value))

    def test_encoded_service_credentials_pass_directly(self):
        encoded = base64.b64encode(b'[credentials]\nusername=test-user\npassword=fake%pass\n').decode()
        with patch.dict(os.environ, COPERNICUS_MARINE_CREDS=encoded):
            self.assertEqual(visibility.credentials(), {'username': 'test-user', 'password': 'fake%pass'})
        with patch.dict(os.environ, COPERNICUS_MARINE_CREDS='invalid-secret'):
            with self.assertRaisesRegex(ValueError, '^Invalid COPERNICUS_MARINE_CREDS format$'):
                visibility.credentials()

    def test_nearest_valid_daily_pixel_source_preference_gaps_and_utc_dates(self):
        def frame(rows):
            return pd.DataFrame(rows, columns=['time','latitude','longitude','KD490'])
        my = frame([('2026-10-02', 0, .01, .07), ('2026-10-02', 0, .02, .06),
                    ('2026-10-03', 0, .01, float('nan')), ('2026-10-04', 0, 1, .08)])
        nrt = frame([('2026-10-02', 0, .01, .05), ('2026-10-29', 0, .01, .045)])
        with patch('copernicusmarine.read_dataframe', side_effect=lambda **kw: my if kw['dataset_id'] == visibility.DATASETS[0] else nrt) as read, patch.dict(os.environ, COPERNICUS_MARINE_CREDS=''):
            result = visibility.collect(0, 0, NOW)
        self.assertEqual(len(result['points']), 30)
        self.assertEqual(result['points'][0]['value'], .07)
        self.assertEqual(result['points'][0]['dataset_id'], visibility.DATASETS[0])
        self.assertEqual(result['points'][1]['status'], 'no_valid_pixel')
        self.assertEqual(result['points'][2]['status'], 'no_valid_pixel')
        self.assertIsNone(result['points'][-1]['value'])
        self.assertEqual(result['points'][-3]['value'], .045)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(datetime.fromtimestamp(result['points'][0]['time'], timezone.utc).day, 2)

    def test_sources_overlap_and_one_failure_preserves_the_other_source(self):
        barrier = threading.Barrier(2, timeout=3)
        entered = set()
        lock = threading.Lock()
        frame = pd.DataFrame([('2026-10-29', 0, .01, .045)],
                             columns=['time', 'latitude', 'longitude', 'KD490'])
        def read(**kwargs):
            source = kwargs['dataset_id']
            with lock:
                entered.add(source)
            barrier.wait()  # A sequential implementation cannot reach both sides.
            if source == visibility.DATASETS[0]:
                raise RuntimeError('Simulated source outage')
            return frame
        with patch('copernicusmarine.read_dataframe', side_effect=read), patch.dict(os.environ, COPERNICUS_MARINE_CREDS=''):
            result = visibility.collect(0, 0, NOW)
        self.assertEqual(entered, set(visibility.DATASETS))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['points'][-3]['value'], .045)
        self.assertEqual(result['points'][-3]['dataset_id'], visibility.DATASETS[1])

    def test_timeout_does_not_take_down_marine_weather(self):
        with patch('pelagia.visibility.subprocess.run', side_effect=subprocess.TimeoutExpired('worker',24)):
            self.assertEqual(visibility.fetch(0,0,NOW)['status'], 'unavailable')
        with patch('pelagia.marine.fetch_weather', return_value={'timezone':'UTC'}), patch('pelagia.marine.visibility.fetch', return_value={'points': [], 'status': 'unavailable'}):
            self.assertEqual(marine.fetch(0,0,NOW)['timezone'], 'UTC')

    def test_antimeridian_reads_both_sides(self):
        frame = pd.DataFrame([('2026-10-29', 0, -179.99, .04)], columns=['time','latitude','longitude','KD490'])
        with patch('copernicusmarine.read_dataframe', return_value=frame) as read, patch.dict(os.environ, COPERNICUS_MARINE_CREDS=''):
            result=visibility.collect(0,179.99,NOW)
        self.assertEqual(read.call_count,4)
        self.assertEqual(result['points'][-3]['value'],.04)

    def test_normalized_chart_and_report_receive_original_values(self):
        import tempfile
        from pathlib import Path
        import test_reference_autocomplete as fixtures
        from test_marine import payload, NOW as FIXTURE_NOW
        from pelagia import db as database, site_reports
        data=payload()
        points=[{'time': FIXTURE_NOW-86400, 'value': .048765, 'clarity':'excellent', 'distance_km':1.5}]
        data['visibility']={'points':points, 'status':'complete'}
        normalized=marine.normalize(data,FIXTURE_NOW,FIXTURE_NOW)
        self.assertEqual(normalized['charts']['visibility_daily'],points)
        with tempfile.TemporaryDirectory() as tmp:
            app,_,_=fixtures.ReferenceAutocompleteTest().make_app(Path(tmp))
            with app.app_context():
                db=database.get_db()
                db.execute('INSERT INTO marine_forecast_cache (site_id, latitude, longitude, payload, fetched_at, expires_at) VALUES (1,54.1,-132.9,?,?,?)',(json.dumps(data),FIXTURE_NOW,FIXTURE_NOW+900))
                db.execute("INSERT INTO dive_site_descriptions (dive_site_id, description, model) VALUES (1, 'Rocky reef', 'test')")
                db.commit()
                site=db.execute('SELECT * FROM dive_sites WHERE id=1').fetchone()
                inputs=site_reports.report_input(site,FIXTURE_NOW)
                self.assertEqual(inputs['conditions']['charts']['visibility_daily'],points)
                self.assertEqual(inputs['retrieved_data']['visibility']['points'],points)
