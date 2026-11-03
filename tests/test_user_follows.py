import tempfile
import unittest
from pathlib import Path

import test_reference_autocomplete as fixtures
from pelagia import db as database


class UserFollowsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        helper = fixtures.ReferenceAutocompleteTest()
        self.app, _, _ = helper.make_app(Path(self.tmp.name))
        self.client = self.app.test_client()
        helper.signup(self.client, 'viewer')
        for name in ('reef-diver', 'kelp-diver'):
            helper.signup(self.app.test_client(), name)
        with self.app.app_context():
            db = database.get_db()
            for user, site in ((1, 'My dive'), (2, 'Reef dive'), (3, 'Kelp dive')):
                db.execute("INSERT INTO dives (user_id, site_name, date, depth_m, duration_min) VALUES (?, ?, '2026-11-02', 20, 45)", (user, site))
            db.commit()
        self.client.get('/users/2')
        with self.client.session_transaction() as session:
            self.csrf = session['google_csrf']

    def follow(self, user=2, following='true'):
        return self.client.post(f'/users/{user}/follow', data={'following': following, 'csrf_token': self.csrf},
                                headers={'X-Requested-With': 'fetch'})

    def test_follow_persists_both_directions_and_is_idempotent(self):
        self.assertEqual(self.follow().get_json(), {'following': True})
        self.assertEqual(self.follow().status_code, 200)
        with self.app.app_context():
            database.init_db()
            db = database.get_db()
            self.assertEqual([r[0] for r in db.execute('SELECT followed_id FROM user_follows WHERE follower_id=1')], [2])
            self.assertEqual([r[0] for r in db.execute('SELECT follower_id FROM user_follows WHERE followed_id=2')], [1])
        profile = self.client.get('/users/2').get_data(as_text=True)
        self.assertIn('data-user-follow-label>Following</span>', profile)
        self.assertNotIn('data-user-follow', self.client.get('/you').get_data(as_text=True))
        self.assertEqual(self.follow(following='false').get_json(), {'following': False})
        self.assertEqual(self.follow(following='false').status_code, 200)
        self.assertIn('data-user-follow-label>Follow</span>', self.client.get('/users/2').get_data(as_text=True))

    def test_home_filters_before_limit_and_unfollow_removes_dives(self):
        for path in ('/home', '/feed'):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('My dive', html)
            self.assertNotIn('Reef dive', html)
            self.assertNotIn('Kelp dive', html)
        self.follow()
        home = self.client.get('/home').get_data(as_text=True)
        self.assertIn('My dive', home)
        self.assertIn('Reef dive', home)
        self.assertNotIn('Kelp dive', home)
        # Following does not restrict other divers' profile histories.
        self.assertIn('Kelp dive', self.client.get('/users/3').get_data(as_text=True))
        # It is a directed relationship, not a reciprocal friend request.
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertNotIn('My dive', self.client.get('/home').get_data(as_text=True))
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        self.follow(following='false')
        self.assertNotIn('Reef dive', self.client.get('/home').get_data(as_text=True))

    def test_feed_excludes_deleted_dives_and_filters_before_limit(self):
        from pelagia import fetch_dives
        self.follow()
        with self.app.test_request_context():
            db = database.get_db()
            # An unrelated dive sorting ahead of followed divers cannot consume the limit.
            db.execute("UPDATE dives SET date='2099-01-01', created_at='2000-01-01' WHERE user_id=3")
            db.execute("UPDATE dives SET is_deleted=1 WHERE user_id=2")
            db.commit()
            dives = fetch_dives(scope='following', user_id=1, limit=1)
            self.assertEqual([d['site_name'] for d in dives], ['My dive'])

    def test_auth_csrf_self_and_unknown_users(self):
        self.assertEqual(self.app.test_client().post('/users/2/follow').status_code, 302)
        self.assertEqual(self.client.post('/users/2/follow', data={'following': 'true'}).status_code, 400)
        self.assertEqual(self.follow(user=1).status_code, 400)
        self.assertEqual(self.follow(user=999).status_code, 404)
        self.assertEqual(self.follow(following='invalid').status_code, 400)
        self.assertEqual(self.client.get('/users/2/follow').status_code, 405)

    def test_deleted_accounts_remove_both_follow_lists(self):
        self.follow()
        with self.app.app_context():
            db = database.get_db()
            db.execute('INSERT INTO user_follows (follower_id, followed_id) VALUES (3, 1)')
            db.execute('DELETE FROM users WHERE id=1')
            db.commit()
            self.assertEqual(db.execute('SELECT count(*) FROM user_follows').fetchone()[0], 0)

    def test_form_fallback_redirects_back_to_profile(self):
        response = self.client.post('/users/2/follow', data={'following': 'true', 'csrf_token': self.csrf})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/users/2'))
