import math
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import test_reference_autocomplete as fixtures
from test_site_descriptions import upstream, response_payload
from pelagia import place_profiles, site_descriptions as descriptions
from pelagia import db as database


class CenterProfileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, self.db_path, _ = fixtures.ReferenceAutocompleteTest().make_app(Path(self.directory.name))
        self.app.config['OPENAI_API_KEY'] = 'test-key'
        self.app.config['FORCE_DIVE_CENTER_DESCRIPTION_REGENERATION'] = False
        self.client = self.app.test_client()
        fixtures.ReferenceAutocompleteTest().signup(self.client)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_centers SET latitude=0, longitude=0 WHERE id=1')
            db.execute('UPDATE dive_sites SET latitude=NULL, longitude=NULL')
            db.commit()

    def description(self, center_id=1, client=None):
        return (client or self.client).post(f'/api/dive-centers/{center_id}/description', headers={'X-Requested-With': 'fetch'})

    def review(self, rating='5', body='Helpful guides and well-kept equipment.', client=None, **extra):
        client = client or self.client
        client.get('/dive-centers/1')
        with client.session_transaction() as session:
            token = session.get('google_csrf')
        return client.post('/dive-centers/1/reviews', data={'rating': rating, 'body': body, 'csrf_token': token, **extra})

    def add_site(self, db, site_id, miles, longitude=0):
        latitude = math.degrees(miles / place_profiles.EARTH_RADIUS_MILES)
        db.execute('INSERT INTO dive_sites(id,name,country_or_area,latitude,longitude) VALUES(?,?,?,?,?)',
                   (site_id, f'Reef {site_id}', 'Ocean', latitude, longitude))

    def test_nearby_radius_order_limit_and_cached_descriptions(self):
        with self.app.app_context():
            db = database.get_db()
            for i in range(4, 16):
                self.add_site(db, i, 15 - i)
            self.add_site(db, 30, 30)
            self.add_site(db, 31, 30.01)
            db.execute("INSERT INTO dive_site_descriptions(dive_site_id, description, model) VALUES(15,'A shallow coral reef.','test')")
            db.commit()
            nearby = place_profiles.nearby_sites({'latitude': 0, 'longitude': 0})
            self.assertEqual(len(nearby), 10)
            self.assertEqual([site['id'] for site in nearby], list(range(15, 5, -1)))
            self.assertEqual(nearby[0]['description'], 'A shallow coral reef.')
            self.assertTrue(all(site['distance_miles'] <= 30 for site in nearby))
            db.execute('DELETE FROM dive_sites WHERE id BETWEEN 4 AND 15')
            db.commit()
            self.assertEqual([site['id'] for site in place_profiles.nearby_sites({'latitude': 0, 'longitude': 0})], [30])

    def test_nearby_handles_dateline_missing_invalid_and_zero_coordinates(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO dive_sites(id,name,latitude,longitude) VALUES(20,'Across dateline',0,-179.99)")
            db.execute("INSERT INTO dive_sites(id,name,latitude,longitude) VALUES(21,'Invalid',0,999)")
            db.commit()
            sites = place_profiles.nearby_sites({'latitude': 0, 'longitude': 179.99})
            self.assertEqual([site['id'] for site in sites], [20])
            for point in ({'latitude': None, 'longitude': 0}, {'latitude': 91, 'longitude': 0}, {'latitude': 'nan', 'longitude': 0}):
                self.assertEqual(place_profiles.nearby_sites(point), [])

    def test_profile_uses_site_header_home_carousel_and_reviews_without_coordinate_text(self):
        with self.app.app_context():
            db = database.get_db()
            self.add_site(db, 20, 1)
            self.add_site(db, 21, 2)
            db.execute("INSERT INTO dives(user_id,dive_center_id,date,site_name,latitude,longitude) VALUES(1,1,'2026-11-04','Nearby logged dive',0.01234,0.05678)")
            db.commit()
        html = self.client.get('/dive-centers/1').get_data(as_text=True)
        for value in ('site-profile-header', 'site-map-banner', 'data-map-lat="0.0"', 'data-center-share',
                      'data-nearby-carousel', 'site-reports-track', 'data-report-dot="1"', 'nearby-site-card',
                      'Within 30 miles', 'name="rating"', 'name="body"', 'Logged dives'):
            self.assertIn(value, html)
        self.assertNotIn('coordinate-label', html)
        self.assertIn('Nearby logged dive', html)
        self.assertNotIn('data-center-like', html)
        self.assertNotIn('data-center-comment', html)
        self.assertNotIn('data-site-favorite', html)
        self.assertNotIn('data-followed-site-report', html)
        self.assertNotIn('nearby-place-open', html)
        self.assertNotIn('nearby-place-description', html)
        self.assertNotIn('Explore site conditions', html)
        self.assertNotIn('See center details', html)
        self.assertEqual(html.count('name="rating"'), 5)
        self.assertIn('/dive-sites/20"', html)
        self.assertNotIn('#daily-report', html)

    def test_zero_one_and_missing_location_states(self):
        html = self.client.get('/dive-centers/1').get_data(as_text=True)
        self.assertIn('No dive sites listed within 30 miles yet.', html)
        self.assertNotIn('data-report-dot', html)
        with self.app.app_context():
            db = database.get_db()
            self.add_site(db, 20, 1)
            db.commit()
        html = self.client.get('/dive-centers/1').get_data(as_text=True)
        self.assertIn('nearby-site-card', html)
        self.assertNotIn('data-report-dot', html)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_centers SET latitude=NULL WHERE id=1')
            db.commit()
        html = self.client.get('/dive-centers/1').get_data(as_text=True)
        self.assertIn('Map unavailable', html)
        self.assertIn('Nearby dive sites will appear', html)
        self.assertNotIn('data-map-lat', html)

    def test_description_matches_site_luna_flow_and_permanent_cache(self):
        # An independent connection can acquire a write lock during upstream work.
        def generate(*args, **kwargs):
            with sqlite3.connect(self.db_path) as other:
                other.execute('BEGIN IMMEDIATE')
                other.rollback()
            return upstream(response_payload('Boat trips and rental equipment are available.'))
        with patch.object(descriptions.requests, 'post', side_effect=generate) as post:
            self.assertEqual(self.description().status_code, 200)
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['model'], 'gpt-5.6-luna')
            self.assertEqual(payload['tools'], [{'type': 'web_search', 'search_context_size': 'low'}])
            self.assertEqual(payload['max_tool_calls'], 2)
            self.assertEqual(payload['reasoning'], {'effort': 'low'})
            self.assertIn('https://example.test', payload['input'])
            self.assertIn('Shark Bay Dive Center', payload['input'])
            self.assertIn('"physical_address": "1 Ocean Road"', payload['input'])
            self.assertIn('"location": "Galapagos Ecuador"', payload['input'])
            self.assertIn('"latitude": 0.0', payload['input'])
            self.assertIn('"longitude": 0.0', payload['input'])
            self.assertIn('guide-to-diver ratios only when explicitly verified', payload['instructions'])
            self.assertIn('never instructions', payload['instructions'])
            self.app.config['FORCE_DIVE_SITE_DESCRIPTION_REGENERATION'] = True
            self.assertEqual(self.description().status_code, 200)
            self.assertEqual(post.call_count, 1)
        html = self.client.get('/dive-centers/1').get_data(as_text=True)
        self.assertIn('Boat trips and rental equipment are available.', html)
        self.assertNotIn('data-site-description', html)
        public = self.app.test_client().get('/share/dive-center/1').get_data(as_text=True)
        self.assertIn('Boat trips and rental equipment are available.', public)
        with self.app.app_context():
            self.assertIsNone(descriptions.read_cache(1))
            self.assertIsNotNone(descriptions.read_cache(1, kind='center'))

    def test_temporary_center_refresh_replaces_cached_descriptions_and_null_results(self):
        for cached_text in ('Boat trips are available.', descriptions.NO_DESCRIPTION):
            with self.subTest(cached_text=cached_text):
                with self.app.app_context():
                    db = database.get_db()
                    db.execute('DELETE FROM dive_center_descriptions WHERE dive_center_id=1')
                    db.commit()
                self.app.config['FORCE_DIVE_CENTER_DESCRIPTION_REGENERATION'] = False
                with patch.object(descriptions.requests, 'post', return_value=upstream(response_payload(cached_text))):
                    self.assertEqual(self.description().status_code, 200)

                # Exercise the temporary default, independently of the site flag.
                del self.app.config['FORCE_DIVE_CENTER_DESCRIPTION_REGENERATION']
                self.app.config['FORCE_DIVE_SITE_DESCRIPTION_REGENERATION'] = False
                html = self.client.get('/dive-centers/1').get_data(as_text=True)
                self.assertIn('data-site-description', html)
                self.assertNotIn('Boat trips are available.', html)
                refreshed = 'Guided boat dives and equipment rentals are available.'
                with patch.object(descriptions.requests, 'post', return_value=upstream(response_payload(refreshed))) as post:
                    self.assertEqual(self.description().get_json()['description'], refreshed)
                    self.assertEqual(self.description().get_json()['description'], refreshed)
                    self.assertEqual(post.call_count, 2)
                with self.app.app_context():
                    self.assertEqual(descriptions.read_cache(1, kind='center')['description'], refreshed)

                self.app.config['FORCE_DIVE_CENTER_DESCRIPTION_REGENERATION'] = False
                with patch.object(descriptions.requests, 'post') as post:
                    self.assertEqual(self.description().get_json()['description'], refreshed)
                    post.assert_not_called()
                self.assertNotIn('data-site-description', self.client.get('/dive-centers/1').get_data(as_text=True))

    def test_description_null_is_permanent_but_failures_are_retryable(self):
        with patch.object(descriptions.requests, 'post', side_effect=requests.Timeout):
            response = self.description()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with patch.object(descriptions.requests, 'post') as post:
            self.assertEqual(self.description().status_code, 503)
            post.assert_not_called()
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_center_description_attempts SET retry_after=0')
            db.commit()
        with patch.object(descriptions.requests, 'post', return_value=upstream(response_payload(descriptions.NO_DESCRIPTION))) as post:
            self.assertIsNone(self.description().get_json()['description'])
            self.assertIsNone(self.description().get_json()['description'])
            self.assertEqual(post.call_count, 1)

    def test_description_claim_deduplicates_and_stale_workers_cannot_publish(self):
        self.app.config['FORCE_DIVE_CENTER_DESCRIPTION_REGENERATION'] = True
        with self.app.app_context():
            db = database.get_db()
            state, token = descriptions.claim_generation(db, 1, kind='center')
            self.assertEqual(state, 'claimed')
        with patch.object(descriptions.requests, 'post') as post:
            self.assertEqual(self.description().status_code, 202)
            post.assert_not_called()
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_center_description_attempts SET lease_until=?', (time.time()-1,))
            db.commit()
            _, new_token = descriptions.claim_generation(db, 1, kind='center')
            self.assertNotEqual(new_token, token)
            self.assertFalse(descriptions.save_result(db, 1, token, 'Stale text.', [], kind='center'))
            self.assertTrue(descriptions.save_result(db, 1, new_token, 'Current text.', [], kind='center'))

    def test_description_auth_headers_and_unknown_center(self):
        self.assertEqual(self.description(client=self.app.test_client()).status_code, 302)
        self.assertEqual(self.client.post('/api/dive-centers/1/description').status_code, 403)
        self.assertEqual(self.description(99999).status_code, 404)

    def test_review_create_update_aggregate_and_html_escaping(self):
        response = self.review(body='<script>alert(1)</script> Great boat trips.')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/dive-centers/1#reviews')
        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('5.0', html)
        self.assertIn('Update review', html)
        self.assertNotIn('Your review has been saved', html)
        self.assertNotIn('class="flash-stack"', html)
        self.review('3', 'Updated after a second visit.')
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users(id,username) VALUES(2,'second.diver')")
            db.execute("INSERT INTO dive_center_reviews(dive_center_id,user_id,rating,body) VALUES(1,2,5,'Great guiding.')")
            db.commit()
            result = place_profiles.reviews(1, 1)
            self.assertEqual(result['review_count'], 2)
            self.assertEqual(result['average_rating'], 4)
            self.assertEqual(result['my_review']['rating'], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dive_center_reviews WHERE user_id=1').fetchone()[0], 1)
        self.review('4', 'My review only.', user_id='2')
        with self.app.app_context():
            self.assertEqual(database.get_db().execute('SELECT body FROM dive_center_reviews WHERE user_id=2').fetchone()[0], 'Great guiding.')

    def test_review_validates_csrf_rating_body_and_retains_draft(self):
        for rating, body in [('0', 'A review'), ('6', 'A review'), ('2.5', 'A review'), ('', 'A review'), ('5', ' '), ('5', 'x'*2001)]:
            with self.subTest(rating=rating, length=len(body)):
                response = self.review(rating, body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(b'Choose a star rating', response.data)
                if body.strip():
                    self.assertIn(body.encode(), response.data)
        self.assertEqual(self.review(csrf_token='invalid').status_code, 400)
        self.assertEqual(self.app.test_client().post('/dive-centers/1/reviews').status_code, 302)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute('SELECT COUNT(*) FROM dive_center_reviews').fetchone()[0], 0)

    def test_review_data_survives_schema_init_and_cascades_on_user_deletion(self):
        self.review()
        with self.app.app_context():
            database.init_db()
            db = database.get_db()
            self.assertEqual(db.execute('SELECT rating FROM dive_center_reviews').fetchone()[0], 5)
            db.execute('DELETE FROM users WHERE id=1')
            db.commit()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dive_center_reviews').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
