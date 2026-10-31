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
        for value, label in ((.04, 'excellent'), (.040001, 'very good'), (.07, 'very good'),
                             (.070001, 'good'), (.095, 'good'), (.095001, 'fair'),
                             (.19, 'fair'), (.190001, 'poor'), (.29, 'poor'), (.290001, 'very poor')):
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

    def test_latest_valid_pixel_within_week_and_source_priority(self):
        frame = pd.DataFrame([('2026-10-24',0,.01,.03), ('2026-10-29',0,.01,.05),
                              ('2026-10-29',0,.02,.06)], columns=['time','latitude','longitude','KD490'])
        with patch('copernicusmarine.read_dataframe', return_value=frame), patch.dict(os.environ,COPERNICUS_MARINE_CREDS=''):
            result=visibility.collect(0,0,NOW)
        self.assertEqual(result['date'],'2026-10-29')
        self.assertEqual(result['value'],.05)
        self.assertEqual(result['clarity'],'very good')
        self.assertEqual(result['dataset_id'],visibility.DATASETS[0])

    def test_no_data_when_measurements_are_too_old(self):
        frame=pd.DataFrame([('2026-10-24',0,0,.04)], columns=['time','latitude','longitude','KD490'])
        with patch('copernicusmarine.read_dataframe',return_value=frame), patch.dict(os.environ,COPERNICUS_MARINE_CREDS=''):
            self.assertEqual(visibility.collect(0,0,NOW)['status'],'no_data')

    def test_daily_cache_and_report_wait_for_visibility(self):
        import tempfile
        from pathlib import Path
        import test_reference_autocomplete as fixtures
        from test_marine import payload, NOW as T
        from pelagia import db as database, site_reports
        helper=fixtures.ReferenceAutocompleteTest()
        with tempfile.TemporaryDirectory() as tmp:
            app,_,_=helper.make_app(Path(tmp))
            with app.app_context():
                db=database.get_db()
                db.execute('INSERT INTO marine_forecast_cache (site_id,latitude,longitude,payload,fetched_at,expires_at) VALUES (1,54.1,-132.9,?,?,?)',(json.dumps(payload()),T,T+900))
                db.execute("INSERT INTO dive_site_descriptions (dive_site_id,description,model) VALUES (1,'Rocky reef','test')")
                db.commit();site=db.execute('SELECT * FROM dive_sites WHERE id=1').fetchone()
                self.assertIsNone(site_reports.report_input(site,T))
                with patch('pelagia.visibility.fetch',return_value={'status':'complete','date':'2026-10-24','value':.05,'clarity':'very good'}) as fetch:
                    with patch('time.time',return_value=T):
                        result,status=visibility.load(site,T,'Pacific/Galapagos')
                        self.assertEqual(status,200)
                        self.assertEqual(visibility.load(site,T+60,'Pacific/Galapagos')[0],result)
                        self.assertEqual(fetch.call_count,1)
                        self.assertEqual(site_reports.report_input(site,T)['retrieved_data']['visibility'],result)
                        visibility.load(site,T+86400,'Pacific/Galapagos')
                        self.assertEqual(fetch.call_count,2)

    def test_cached_measurement_ages_out_even_before_local_midnight(self):
        import tempfile
        from pathlib import Path
        import test_reference_autocomplete as fixtures
        from pelagia import db as database
        with tempfile.TemporaryDirectory() as tmp:
            app,_,_=fixtures.ReferenceAutocompleteTest().make_app(Path(tmp))
            with app.app_context():
                db=database.get_db();site=db.execute('SELECT * FROM dive_sites WHERE id=1').fetchone()
                data={'status':'complete','date':'2026-10-24','value':.05,'clarity':'very good'}
                db.execute('INSERT INTO site_visibility_cache (site_id,cache_date,latitude,longitude,payload) VALUES (1,?,?,?,?)',('2026-10-30',54.1,-132.9,json.dumps(data)));db.commit()
                now=datetime(2026,10,31,2,tzinfo=timezone.utc).timestamp()
                self.assertEqual(visibility.read_cache(site,now,'Pacific/Galapagos'),{'status':'no_data'})
