import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from markupsafe import Markup

import test_reference_autocomplete as fixtures
from pelagia import db as database
from pelagia.dive_brief import DiveBrief


class FounderWelcomeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        helper = fixtures.ReferenceAutocompleteTest()
        self.app, _, _ = helper.make_app(Path(temporary.name))
        self.client = self.app.test_client()
        helper.signup(self.client, 'new.diver')
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (username, profile_photo) VALUES ('davyjones', 'profiles/founder.jpg')")
            db.execute("INSERT INTO users (username) VALUES ('buddy')")
            db.commit()

    def execute(self, sql):
        with self.app.app_context():
            db = database.get_db()
            db.execute(sql)
            db.commit()

    def test_new_diver_sees_personal_message_above_brief_on_all_home_routes(self):
        brief = DiveBrief('The Dive Brief', date(2026, 11, 2), 'Ocean news.', Markup('<p>News.</p>'), 1)
        with patch('pelagia.dive_brief.load_brief', return_value=brief):
            for path in ('/home', '/feed', '/welcome'):
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    html = response.get_data(as_text=True)
                    self.assertLess(html.index('class="founder-welcome"'), html.index('class="brief-card"'))
                    self.assertIn('Hi new.diver ', html)
                    self.assertIn('👋', html)
                    self.assertIn('Welcome to Pelagia! My name is Sam and I built this app.', html)
                    self.assertIn('You can log dives, follow friends, check the conditions, plan your next trip, and much more.', html)
                    self.assertIn('Happy diving!', html)
                    self.assertIn('src="/uploads/profiles/founder.jpg"', html)
                    self.assertIn('action="/users/2/follow"', html)
                    self.assertIn('js/user-follow.js', html)

    def test_logged_dives_exclude_diver_even_when_deleted(self):
        for deleted in (0, 1):
            with self.subTest(deleted=deleted):
                self.execute('DELETE FROM dives')
                self.execute(f"INSERT INTO dives (user_id, site_name, date, is_deleted) VALUES (1, 'Reef', '2026-11-02', {deleted})")
                self.assertNotIn(b'class="founder-welcome"', self.client.get('/home').data)

    def test_following_any_user_excludes_diver(self):
        for target in (2, 3):
            with self.subTest(target=target):
                self.execute('DELETE FROM user_follows')
                self.execute(f'INSERT INTO user_follows (follower_id, followed_id) VALUES (1, {target})')
                self.assertNotIn(b'class="founder-welcome"', self.client.get('/feed').data)

    def test_site_follows_incoming_followers_and_starting_count_do_not_exclude_diver(self):
        self.execute('INSERT INTO dive_site_favorites (user_id, dive_site_id) VALUES (1, 1)')
        self.execute('INSERT INTO user_follows (follower_id, followed_id) VALUES (3, 1)')
        self.execute('UPDATE users SET starting_dive_count = 100 WHERE id = 1')
        self.assertIn(b'class="founder-welcome"', self.client.get('/home').data)

    def test_following_founder_uses_existing_control_and_hides_card_on_next_visit(self):
        self.client.get('/home')
        with self.client.session_transaction() as session:
            csrf = session['google_csrf']
        response = self.client.post('/users/2/follow', data={'following': 'true', 'csrf_token': csrf},
                                    headers={'X-Requested-With': 'fetch'})
        self.assertEqual(response.get_json(), {'following': True})
        self.assertNotIn(b'class="founder-welcome"', self.client.get('/home').data)
        self.assertIn(b'data-user-follow-label>Following</span>', self.client.get('/users/2').data)

    def test_founder_lookup_is_case_insensitive_and_handles_missing_photo(self):
        self.execute("UPDATE users SET username='DavyJones', profile_photo=NULL WHERE id=2")
        html = self.client.get('/home').get_data(as_text=True)
        self.assertIn('class="founder-welcome"', html)
        self.assertIn('@DavyJones', html)
        self.assertIn('<span>D</span>', html)
        self.assertNotIn('/uploads/None', html)

    def test_missing_founder_and_founders_own_feed_do_not_offer_self_follow(self):
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertNotIn(b'class="founder-welcome"', self.client.get('/home').data)
        with self.client.session_transaction() as session:
            session['user_id'] = 1
        self.execute('DELETE FROM users WHERE id=2')
        self.assertEqual(self.client.get('/home').status_code, 200)
        self.assertNotIn(b'class="founder-welcome"', self.client.get('/home').data)

    def test_username_is_escaped(self):
        self.execute("UPDATE users SET username='<script>alert(1)</script>' WHERE id=1")
        html = self.client.get('/home').get_data(as_text=True)
        self.assertIn('Hi &lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
