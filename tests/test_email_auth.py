import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from pelagia import create_app, db as database


class EmailAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch('pelagia._load_json_config', return_value={}), patch('pelagia._ensure_reference_data'):
            self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret',
                'DATABASE': str(Path(self.tmp.name) / 'db'), 'UPLOAD_FOLDER': str(Path(self.tmp.name) / 'uploads'),
                'RESEND_API_KEY': 'test-key', 'EMAIL_FROM': 'Pelagia <login@example.com>'})
        self.client = self.app.test_client()
        from pelagia.email_auth import send_code
        self.real_send_code = send_code
        self.sender = patch('pelagia.email_auth.send_code').start()
        self.addCleanup(patch.stopall)

    def csrf(self):
        self.client.get('/auth/email/start')
        with self.client.session_transaction() as s:
            return s['google_csrf']

    def start(self, email='diver@example.com', destination='/dive/42'):
        response = self.client.post('/auth/email/start', data={'email': email, 'next': destination, 'csrf_token': self.csrf()})
        self.assertEqual(response.status_code, 302)
        return self.sender.call_args.args[1]

    def verify(self, code):
        return self.client.post('/auth/email/verify', data={'code': code, 'csrf_token': self.csrf()})

    def test_signup_and_returning_login(self):
        page = self.client.get('/login').text
        self.assertIn('Continue with email', page)
        self.assertEqual(self.client.get('/login').headers['Cache-Control'], 'no-store')
        code = self.start('Diver@Example.com')
        self.assertEqual(self.verify(code).location, '/auth/email/signup')
        response = self.client.post('/auth/email/signup', data={'username': 'diver', 'csrf_token': self.csrf()})
        self.assertEqual(response.location, '/dive/42')
        with self.client.session_transaction() as s:
            uid = s['user_id']
            self.assertTrue(s.permanent)
            s.clear()
        with self.app.app_context():
            db = database.get_db()
            self.assertEqual(db.execute('SELECT login_email FROM users WHERE id = ?', (uid,)).fetchone()[0], 'diver@example.com')
            db.execute('UPDATE email_challenges SET created = created - 61')
            db.commit()
        code = self.start()
        self.assertEqual(self.verify(code).location, '/dive/42')
        with self.client.session_transaction() as s:
            self.assertEqual(s['user_id'], uid)

    def test_attempt_limit_expiry_and_replay(self):
        code = self.start()
        wrong = '000000' if code != '000000' else '111111'
        for _ in range(5):
            self.verify(wrong)
        self.assertIn('/auth/email/start', self.verify(code).location)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE email_challenges SET attempts = 0, created = ?', (time.time() - 601,))
            db.commit()
        self.assertIn('/auth/email/start', self.verify(code).location)
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE email_challenges SET created = ?', (time.time(),))
            db.commit()
        with self.client.session_transaction() as s:
            flow = s['email_challenge']
        self.verify(code)
        with self.client.session_transaction() as s:
            s['email_challenge'] = flow
        self.assertIn('/auth/email/start', self.verify(code).location)

    def test_rate_limit_csrf_and_delivery_failure(self):
        self.assertEqual(self.client.post('/auth/email/start', data={'email': 'a@b.com'}).status_code, 400)
        self.start()
        self.assertEqual(self.client.post('/auth/email/start', data={'email': 'diver@example.com', 'csrf_token': self.csrf()}).status_code, 429)
        self.sender.side_effect = requests.Timeout()
        response = self.client.post('/auth/email/start', data={'email': 'other@example.com', 'csrf_token': self.csrf()})
        self.assertEqual(response.status_code, 503)

    def test_explicit_link_preserves_google_account(self):
        with self.app.app_context():
            db = database.get_db()
            uid = db.execute("INSERT INTO users (username, google_subject, google_email) VALUES ('original', 'google-id', 'diver@example.com')").lastrowid
            db.commit()
        self.assertEqual(self.verify(self.start()).location, '/login')
        with self.client.session_transaction() as s:
            self.assertNotIn('user_id', s)
            s['user_id'] = uid
        with self.app.app_context():
            db = database.get_db()
            db.execute('UPDATE email_challenges SET created = created - 61')
            db.commit()
        self.assertEqual(self.verify(self.start(destination='https://evil.example')).location, '/home')
        with self.app.app_context():
            row = database.get_db().execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
            self.assertEqual(row['login_email'], 'diver@example.com')
            self.assertEqual(row['google_subject'], 'google-id')

    def test_cannot_link_email_owned_by_another_account(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (username, login_email) VALUES ('owner', 'diver@example.com')")
            uid = db.execute("INSERT INTO users (username) VALUES ('other')").lastrowid
            db.commit()
        with self.client.session_transaction() as s:
            s['user_id'] = uid
        self.verify(self.start())
        with self.app.app_context():
            self.assertIsNone(database.get_db().execute('SELECT login_email FROM users WHERE id = ?', (uid,)).fetchone()[0])

    def test_resend_payload(self):
        with self.app.app_context(), patch('pelagia.email_auth.requests.post') as post:
            self.real_send_code('diver@example.com', '012345')
            args = post.call_args.kwargs
            self.assertEqual(args['json']['to'], ['diver@example.com'])
            self.assertIn('012345', args['json']['text'])
            self.assertEqual(args['timeout'], 10)

    def test_challenge_is_bound_to_browser_and_signin_context(self):
        code = self.start()
        other = self.app.test_client()
        self.assertIn('/auth/email/start', other.get('/auth/email/verify').location)
        with self.client.session_transaction() as session:
            session['user_id'] = 999
        self.assertIn('/auth/email/start', self.verify(code).location)

    def test_disabled_without_resend_configuration(self):
        self.app.config['RESEND_API_KEY'] = ''
        self.assertNotIn('Continue with email', self.client.get('/login').text)
        self.assertEqual(self.client.get('/auth/email/start').status_code, 404)
        self.assertEqual(self.client.get('/auth/email/verify').status_code, 404)
