import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
import requests
import test_reference_autocomplete as fixtures
from pelagia import visibility, db as database


class RulesTest(unittest.TestCase):
    def test_thresholds_and_invalid_values(self):
        for kd, score in [(None,None), (float('nan'),None),(-1,None),(True,None),(.05,5),(.0501,4),(.1,4),(.1001,3),(.2,3),(.2001,2),(.3,2),(.3001,1)]:
            self.assertEqual(visibility.rating(kd),score)

    def test_latest_twelve_valid_months_seek_past_gaps(self):
        times = [f'{2023+i//12}-{i%12+1:02d}-01T12:00:00Z' for i in range(36)]
        def upstream(dataset, query):
            if query == 'time': return [{'time':t} for t in times]
            start, _, stop = query.split('[')[1].split(']')[0].split(':')
            return [dict(time=times[i],kd_490='NaN' if i>=24 else '.1',latitude='-.39',longitude='-90.28') for i in range(int(start),int(stop)+1)]
        with patch.object(visibility,'rows',side_effect=upstream):
            result=visibility.fetch('monthly',-.3948,-90.2844)
        self.assertEqual(len(result['points']),12)
        self.assertEqual(datetime.fromtimestamp(result['points'][-1]['time'],timezone.utc).year,2024)
        self.assertEqual(result['points'][-1]['label'],'Good')

    def test_daily_skips_missing_and_never_uses_another_coordinate(self):
        def upstream(dataset,query):
            if query == 'time': return [dict(time=f'2026-10-{i:02d}T12:00:00Z') for i in range(1,29)]
            self.assertIn('[(-0.3948)][(-90.2844)]',query)
            return [dict(time=f'2026-10-{i:02d}T12:00:00Z', kd_490='.07' if i==8 else 'NaN',latitude='-.39375',longitude='-90.28125') for i in range(1,29)]
        with patch.object(visibility,'rows',side_effect=upstream):
            result=visibility.fetch('daily',-.3948,-90.2844)
        self.assertEqual(result['latest']['label'],'Good')
        self.assertEqual(datetime.fromtimestamp(result['latest']['time'],timezone.utc).day,8)

    def test_bad_csv_is_rejected(self):
        with patch.object(visibility.requests,'get') as get:
            get.return_value.text='<html>error</html>'
            with self.assertRaises(ValueError):visibility.rows('dataset','time')


class CacheTest(unittest.TestCase):
    make_app=fixtures.ReferenceAutocompleteTest.make_app
    signup=fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.app,_,_=self.make_app(Path(temp.name));self.client=self.app.test_client();self.signup(self.client)
        self.url='/api/dive-sites/1/visibility/'
        p=patch('pelagia.visibility.water_type.classify_site',return_value={'feature':'OCEAN'})
        p.start();self.addCleanup(p.stop)
        p=patch('pelagia.visibility.fetch',return_value={'status':'complete','points':[{'time':1,'value':4}]})
        self.fetch=p.start();self.addCleanup(p.stop)

    def test_persistent_cache_independent_kinds_and_coordinate_change(self):
        self.assertEqual(self.client.get(self.url+'monthly').status_code,200)
        self.assertEqual(self.client.get(self.url+'monthly').json['points'][0]['value'],4)
        self.assertEqual(self.fetch.call_count,1)
        self.client.get(self.url+'daily');self.assertEqual(self.fetch.call_count,2)
        with self.app.app_context():
            db=database.get_db();db.execute('UPDATE dive_sites SET longitude=1 WHERE id=1');db.commit()
        self.client.get(self.url+'monthly');self.assertEqual(self.fetch.call_count,3)

    def test_stale_success_survives_refresh_failure_and_cooldown(self):
        self.client.get(self.url+'monthly')
        with self.app.app_context():
            db=database.get_db();db.execute('UPDATE visibility_cache SET expires_at=0');db.commit()
        self.fetch.side_effect=requests.Timeout()
        result=self.client.get(self.url+'monthly')
        self.assertTrue(result.json['stale']);self.assertEqual(result.status_code,200)
        self.client.get(self.url+'monthly');self.assertEqual(self.fetch.call_count,2)

    def test_pending_error_auth_and_coordinates(self):
        with self.client.session_transaction() as session:session.clear()
        self.assertEqual(self.client.get(self.url+'daily').status_code,302)
        self.signup(self.client)
        self.fetch.side_effect=requests.Timeout()
        self.assertEqual(self.client.get(self.url+'daily').status_code,503)
        self.client.get(self.url+'daily');self.assertEqual(self.fetch.call_count,1)
        with self.app.app_context():
            db=database.get_db();db.execute('UPDATE visibility_cache SET retry_after=0,lease_until=?',(visibility.time.time()+100,));db.commit()
        self.assertEqual(self.client.get(self.url+'daily').status_code,202)
        with self.app.app_context():
            db=database.get_db();db.execute('UPDATE dive_sites SET latitude=NULL WHERE id=1');db.commit()
        self.assertEqual(self.client.get(self.url+'daily').json['reason'],'coordinates')
