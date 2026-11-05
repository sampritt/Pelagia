import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database, place_profiles


class SiteProfileTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = fixtures.ReferenceAutocompleteTest().make_app(Path(self.directory.name))
        self.client = self.app.test_client()
        fixtures.ReferenceAutocompleteTest().signup(self.client)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_sites SET latitude=0,longitude=0 WHERE id=1')
            db.execute('UPDATE dive_centers SET latitude=NULL,longitude=NULL')
            db.commit()

    def add_center(self, db, center_id, miles, *, longitude=0):
        lat = math.degrees(miles / place_profiles.EARTH_RADIUS_MILES)
        db.execute('INSERT INTO dive_centers(id,name,location,latitude,longitude) VALUES(?,?,?,?,?)',
                   (center_id, f'Center {center_id}', 'Ocean coast', lat, longitude))

    def review(self, rating='5', body='Easy boat access and a beautiful rocky reef.', *, client=None, **extra):
        client = client or self.client
        client.get('/dive-sites/1')
        with client.session_transaction() as session:
            token = session.get('google_csrf')
        return client.post('/dive-sites/1/reviews', data={'rating': rating, 'body': body, 'csrf_token': token, **extra})

    def test_nearby_centers_radius_nearest_ten_and_cached_center_descriptions(self):
        with self.app.app_context():
            db = database.get_db()
            for i in range(4, 16):
                self.add_center(db, i, 15-i)
            self.add_center(db, 30, 10)
            self.add_center(db, 31, 10.01)
            db.execute("INSERT INTO dive_center_descriptions(dive_center_id,description,model) VALUES(15,'Guided reef trips and rental equipment.','fixture')")
            db.commit()
            with patch('pelagia.site_descriptions.generate_description', side_effect=AssertionError('Unexpected generation')):
                centers = place_profiles.nearby_centers({'latitude': 0, 'longitude': 0})
            self.assertEqual(len(centers), 10)
            self.assertEqual([center['id'] for center in centers], list(range(15, 5, -1)))
            self.assertEqual(centers[0]['description'], 'Guided reef trips and rental equipment.')
            db.execute('DELETE FROM dive_centers WHERE id BETWEEN 4 AND 15')
            db.commit()
            self.assertEqual([center['id'] for center in place_profiles.nearby_centers({'latitude': 0, 'longitude': 0})], [30])

    def test_nearby_centers_handles_dateline_zero_missing_and_invalid_coordinates(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO dive_centers(id,name,latitude,longitude) VALUES(20,'Across dateline',0,-179.99)")
            db.execute("INSERT INTO dive_centers(id,name,latitude,longitude) VALUES(21,'Invalid',0,999)")
            db.commit()
            centers = place_profiles.nearby_centers({'latitude': 0, 'longitude': 179.99})
            self.assertEqual([center['id'] for center in centers], [20])
            for point in ({'latitude': None, 'longitude': 0}, {'latitude': 91, 'longitude': 0}, {'latitude': 'nan', 'longitude': 0}):
                self.assertEqual(place_profiles.nearby_centers(point), [])

    def test_page_places_shared_center_carousel_below_sightings_and_above_reviews_and_logs(self):
        with self.app.app_context():
            db = database.get_db()
            self.add_center(db, 20, 1)
            self.add_center(db, 21, 2)
            db.execute("INSERT INTO dive_site_comments(dive_site_id,user_id,body) VALUES(1,1,'Historical comment')")
            db.execute("INSERT INTO dives(user_id,dive_site_id,date,site_name) VALUES(1,1,'2026-11-04','Logged reef dive')")
            db.commit()
        html = self.client.get('/dive-sites/1').get_data(as_text=True)
        markers = ['site-sightings-panel', 'id="nearbyCentersTitle"', 'id="reviews"', 'id="siteDivesTitle"']
        self.assertEqual([html.index(marker) for marker in markers], sorted(html.index(marker) for marker in markers))
        for value in ('data-nearby-carousel', 'data-nearby-label="Dive center"', 'nearby-center-card',
                      'site-reports-track', 'data-report-dot="1"', 'Within 10 miles', 'miles from site',
                      'href="/dive-centers/20"', 'name="rating"', 'Logged reef dive',
                      'js/place-profile.js', 'data-site-share', 'data-site-favorite', 'Log dive'):
            self.assertIn(value, html)
        self.assertNotIn('Historical comment', html)
        self.assertNotIn('data-site-comment', html)
        self.assertEqual(html.count('name="rating"'), 5)
        self.assertNotIn('data-followed-site-report', html)
        self.assertNotIn('/api/dive-centers/20/description', html)
        self.assertEqual(self.client.post('/api/dive-sites/1/comments', data={'body': 'Retired'}).status_code, 404)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute('SELECT body FROM dive_site_comments').fetchone()[0], 'Historical comment')

    def test_zero_single_and_missing_coordinate_states(self):
        html = self.client.get('/dive-sites/1').get_data(as_text=True)
        self.assertIn('No dive centers listed within 10 miles yet.', html)
        self.assertNotIn('data-report-dot', html)
        with self.app.app_context():
            db = database.get_db()
            self.add_center(db, 20, 1)
            db.commit()
        html = self.client.get('/dive-sites/1').get_data(as_text=True)
        self.assertIn('nearby-center-card', html)
        self.assertNotIn('data-report-dot', html)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE dive_sites SET latitude=NULL WHERE id=1')
            db.commit()
        html = self.client.get('/dive-sites/1').get_data(as_text=True)
        self.assertIn('Nearby dive centers will appear when this site’s location is available.', html)
        self.assertNotIn('nearby-center-card', html)

    def test_review_create_update_average_escaping_and_no_confirmation_banners(self):
        response = self.review(body='<script>alert(1)</script> A sheltered reef.')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/dive-sites/1#reviews')
        html = self.client.get(response.location).get_data(as_text=True)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('Update review', html)
        self.assertNotIn('class="flash-stack"', html)
        self.review('3', 'Updated after a second dive.')
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users(id,username) VALUES(2,'second.diver')")
            db.execute("INSERT INTO dive_site_reviews(dive_site_id,user_id,rating,body) VALUES(1,2,5,'Interesting topography.')")
            db.commit()
            data = place_profiles.reviews(1, 1, kind='site')
            self.assertEqual(data['review_count'], 2)
            self.assertEqual(data['average_rating'], 4)
            self.assertEqual(data['my_review']['rating'], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dive_site_reviews WHERE user_id=1').fetchone()[0], 1)
        self.review('4', 'Only my own review changes.', user_id='2')
        with self.app.app_context():
            self.assertEqual(database.get_db().execute('SELECT body FROM dive_site_reviews WHERE user_id=2').fetchone()[0], 'Interesting topography.')

    def test_site_and_center_reviews_are_independent_and_share_the_form(self):
        self.review('4', 'The site review.')
        with self.app.app_context():
            place_profiles.save_review(1, 1, 2, 'The center review.', kind='center')
            self.assertEqual(place_profiles.reviews(1, 1, kind='site')['average_rating'], 4)
            self.assertEqual(place_profiles.reviews(1, 1, kind='center')['average_rating'], 2)
        site_html = self.client.get('/dive-sites/1').get_data(as_text=True)
        center_html = self.client.get('/dive-centers/1').get_data(as_text=True)
        self.assertIn('The site review.', site_html)
        self.assertNotIn('The center review.', site_html)
        self.assertIn('The center review.', center_html)
        self.assertNotIn('The site review.', center_html)
        for html in (site_html, center_html):
            self.assertIn('class="place-review-form"', html)
            self.assertIn('class="review-stars"', html)
            self.assertIn('js/place-profile.js', html)

    def test_invalid_reviews_retain_draft_and_complete_profile_sections(self):
        for rating, body in [('0', 'A draft'), ('6', 'A draft'), ('2.5', 'A draft'), ('', 'A draft'), ('4', ' '), ('5', 'x'*2001)]:
            with self.subTest(rating=rating, length=len(body)):
                response = self.review(rating, body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(b'Choose a star rating', response.data)
                self.assertIn(b'nearbyCentersTitle', response.data)
                self.assertIn(b'data-marine-forecast', response.data)
                if body.strip():
                    self.assertIn(body.encode(), response.data)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute('SELECT COUNT(*) FROM dive_site_reviews').fetchone()[0], 0)

    def test_review_auth_csrf_and_unknown_site(self):
        self.assertEqual(self.review(csrf_token='invalid').status_code, 400)
        self.assertEqual(self.app.test_client().post('/dive-sites/1/reviews').status_code, 302)
        with self.client.session_transaction() as session:
            token = session.get('google_csrf')
        self.assertEqual(self.client.post('/dive-sites/99999/reviews', data={'csrf_token': token,'rating':'5','body':'A review'}).status_code, 404)

    def test_reviews_survive_schema_init_and_cascade_on_account_and_site_deletion(self):
        self.review()
        with self.app.app_context():
            database.init_db()
            db = database.get_db()
            self.assertEqual(db.execute('SELECT rating FROM dive_site_reviews').fetchone()[0], 5)
            db.execute('DELETE FROM dive_sites WHERE id=1')
            db.commit()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dive_site_reviews').fetchone()[0], 0)
            place_profiles.save_review(2, 1, 4, 'Another site.', kind='site')
            db.execute('DELETE FROM users WHERE id=1')
            db.commit()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM dive_site_reviews').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_public_preview_keeps_reviews_and_nearby_center_discovery_gated(self):
        self.review(body='Private community review text.')
        html = self.app.test_client().get('/share/dive-site/1').get_data(as_text=True)
        self.assertNotIn('Private community review text.', html)
        self.assertNotIn('name="rating"', html)
        self.assertNotIn('nearby-center-card', html)
