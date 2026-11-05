"""Optional place reviews save with a dive and remain independent per profile."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pelagia import db as database
import test_reference_autocomplete as fixtures


class DiveReviewsTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        fixture = fixtures.ReferenceAutocompleteTest()
        self.app, self.db_path, _ = fixture.make_app(Path(directory.name))
        self.client = self.app.test_client()
        fixture.signup(self.client)
        self.client.get('/dive/new')
        with self.client.session_transaction() as session:
            token = session['google_csrf']
        self.form = {'date': '2026-01-01', 'site_name': 'Alert Rock', 'dive_site_id': '1',
                     'dive_center_name': 'Shark Bay Dive Center', 'dive_center_id': '1', 'csrf_token': token}

    def rows(self, table):
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(f'SELECT * FROM {table}')]

    def save(self, **changes):
        return self.client.post('/dive/new', data={**self.form, **changes})

    def test_both_reviews_publish_with_optional_text_and_profile_aggregates(self):
        response = self.save(center_review_rating='5', site_review_rating='4', site_review_body='  Beautiful reef.  ')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.rows('dives')), 1)
        self.assertEqual(self.rows('dive_center_reviews')[0]['body'], '')
        self.assertEqual(self.rows('dive_site_reviews')[0]['body'], 'Beautiful reef.')
        center = self.client.get('/dive-centers/1').get_data(as_text=True)
        site = self.client.get('/dive-sites/1').get_data(as_text=True)
        self.assertIn('5.0', center)
        self.assertIn('4.0', site)
        self.assertIn('Beautiful reef.', site)
        self.assertNotIn('Beautiful reef.', center)

    def test_no_stars_means_no_review_even_with_text(self):
        self.assertEqual(self.save(center_review_body='Unselected draft', site_review_body='Another draft').status_code, 302)
        self.assertEqual(self.rows('dive_center_reviews'), [])
        self.assertEqual(self.rows('dive_site_reviews'), [])

    def test_review_requires_valid_rating_text_length_csrf_and_resolved_place(self):
        for changes in ({'center_review_rating': '6'}, {'site_review_rating': '2.5'},
                        {'site_review_rating': '4', 'site_review_body': 'x'*2001},
                        {'center_review_rating': '4', 'csrf_token': 'invalid'},
                        {'site_review_rating': '4', 'dive_site_id': '', 'site_name': 'Unknown place'},
                        {'site_review_rating': '4', 'center_review_rating': '5', 'dive_center_id': '', 'dive_center_name': 'Unknown center'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.save(**changes).status_code, 400)
                self.assertEqual(self.rows('dives'), [])
                self.assertEqual(self.rows('dive_center_reviews'), [])
                self.assertEqual(self.rows('dive_site_reviews'), [])

    def test_reviews_resolve_exact_place_names_and_are_upserted(self):
        self.assertEqual(self.save(dive_center_id='', dive_site_id='', center_review_rating='3', site_review_rating='2').status_code, 302)
        self.assertEqual(self.save(center_review_rating='5', site_review_rating='4', site_review_body='Updated').status_code, 302)
        self.assertEqual(len(self.rows('dive_center_reviews')), 1)
        self.assertEqual(self.rows('dive_center_reviews')[0]['rating'], 5)
        self.assertEqual(len(self.rows('dive_site_reviews')), 1)
        self.assertEqual(self.rows('dive_site_reviews')[0]['rating'], 4)

    def test_edit_prefills_and_explicit_clear_removes_only_own_review(self):
        response = self.save(center_review_rating='4', site_review_rating='5')
        url = response.location + '/edit'
        html = self.client.get(url).get_data(as_text=True)
        self.assertIn('name="center_review_rating" value="4" aria-label="4 stars" checked', html)
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT INTO users(id,username) VALUES(2,'other.diver')")
            db.execute("INSERT INTO dive_center_reviews(dive_center_id,user_id,rating,body) VALUES(1,2,3,'')")
        response = self.client.post(url, data={**self.form, 'center_review_action': 'delete'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual([row['user_id'] for row in self.rows('dive_center_reviews')], [2])
        self.assertEqual(self.rows('dive_site_reviews')[0]['rating'], 5)
        self.assertEqual(len(self.rows('dives')), 1)

    def test_failed_dive_does_not_publish_reviews(self):
        self.assertEqual(self.save(center_review_rating='4', site_review_rating='5', date='invalid').status_code, 400)
        self.assertEqual(self.rows('dives'), [])
        self.assertEqual(self.rows('dive_center_reviews'), [])
        self.assertEqual(self.rows('dive_site_reviews'), [])

    def test_profile_reviews_accept_blank_or_omitted_body_for_both_kinds(self):
        for kind in ('center', 'site'):
            for body in (None, '', '  '):
                data = {'csrf_token': self.form['csrf_token'], 'rating': '4'}
                if body is not None:
                    data['body'] = body
                self.assertEqual(self.client.post(f'/dive-{kind}s/1/reviews', data=data).status_code, 302)
            self.assertEqual(self.rows(f'dive_{kind}_reviews')[0]['body'], '')

    def test_legacy_constraint_migration_preserves_data_indexes_and_foreign_keys(self):
        with self.app.app_context():
            db = database.get_db()
            for kind in ('center', 'site'):
                table = f'dive_{kind}_reviews'
                sql = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
                db.execute(f'DROP TABLE {table}')
                db.execute(sql.replace('BETWEEN 0 AND 2000', 'BETWEEN 1 AND 2000'))
                db.execute(f"INSERT INTO {table}(id,dive_{kind}_id,user_id,rating,body,created_at,updated_at) VALUES(7,1,1,5,'Existing review','2025-01-01','2025-01-02')")
            db.commit()
            database.init_db()
            database.init_db()
            for kind in ('center', 'site'):
                table = f'dive_{kind}_reviews'
                row = db.execute(f'SELECT * FROM {table}').fetchone()
                self.assertEqual((row['id'], row['body'], row['created_at'], row['updated_at']), (7, 'Existing review', '2025-01-01', '2025-01-02'))
                db.execute(f"UPDATE {table} SET body='' WHERE id=7")
                self.assertIn(f'idx_{kind}_reviews_{kind}', [r['name'] for r in db.execute(f'PRAGMA index_list({table})')])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            db.execute('DELETE FROM users WHERE id=1')
            for kind in ('center', 'site'):
                self.assertEqual(db.execute(f'SELECT COUNT(*) FROM dive_{kind}_reviews').fetchone()[0], 0)
