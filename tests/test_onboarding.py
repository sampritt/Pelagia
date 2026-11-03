"""New-account setup persists optional preferences before entering Pelagia."""
import tempfile
import time
import unittest
from pathlib import Path

import test_reference_autocomplete as fixtures
from pelagia import db as database


METRIC = {'pressure_unit': 'bar', 'length_unit': 'm', 'temperature_unit': 'c', 'weight_unit': 'kg'}
IMPERIAL = {'pressure_unit': 'psi', 'length_unit': 'ft', 'temperature_unit': 'f', 'weight_unit': 'lb'}


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = fixtures.ReferenceAutocompleteTest().make_app(Path(self.directory.name))
        self.app.config.update(RESEND_API_KEY='test-key', EMAIL_FROM='test@example.com',
                               GOOGLE_CLIENT_ID='test-client', GOOGLE_CLIENT_SECRET='test-secret')
        self.client = self.app.test_client()
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (username) VALUES ('another-diver')")
            db.commit()
            self.location = db.execute("SELECT country_or_area FROM dive_sites WHERE country_or_area IS NOT NULL LIMIT 1").fetchone()[0]

    def signup(self, provider='email', destination='/home'):
        with self.client.session_transaction() as session:
            session['google_csrf'] = 'signup-token'
            session[f'{provider}_pending'] = (
                {'email': 'new@example.com', 'created': time.time(), 'next': destination}
                if provider == 'email' else
                {'sub': 'new-google-subject', 'email': 'new@example.com', 'started_at': time.time(), 'next': destination}
            )
        response = self.client.post(f'/auth/{provider}/signup', data={'username': 'new-diver', 'csrf_token': 'signup-token'})
        self.assertEqual(response.location, '/auth/setup')
        page = self.client.get(response.location)
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as session:
            self.csrf = session['google_csrf']
            self.user_id = session['user_id']
        return page

    def account(self, user_id=None):
        with self.app.app_context():
            return dict(database.get_db().execute('SELECT * FROM users WHERE id = ?', (user_id or self.user_id,)).fetchone())

    def submit(self, **values):
        return self.client.post('/auth/setup', data={'csrf_token': self.csrf, 'intent': 'save', **values})

    def test_both_providers_show_setup_before_splash_with_identical_settings_controls(self):
        for provider in ('email', 'google'):
            with self.subTest(provider=provider):
                self.client = self.app.test_client()
                with self.app.app_context():
                    db = database.get_db()
                    db.execute("DELETE FROM users WHERE username = 'new-diver'")
                    db.commit()
                page = self.signup(provider)
                self.assertEqual(page.headers['Cache-Control'], 'no-store')
                self.assertNotIn(b'data-welcome-splash', page.data)
                self.assertNotIn(b'id="globalSearch"', page.data)
                self.assertNotIn(b'aria-label="Primary mobile"', page.data)
                self.assertNotIn(b'Delete Account', page.data)
                self.assertIn(b'noindex, nofollow', page.data)
                settings = self.client.get('/you/settings').text
                for heading in ('profileUnitsTitle', 'settingsProfileTitle'):
                    selector = f'aria-labelledby="{heading}"'
                    actual = page.text.split(selector, 1)[1].split('</section>', 1)[0]
                    expected = settings.split(selector, 1)[1].split('</section>', 1)[0]
                    # The optional setup allows an empty count; Settings requires it.
                    self.assertEqual(actual, expected.replace(' required>', '>'))
                self.assertEqual(self.submit().location, '/welcome')
                self.assertIn(b'data-welcome-splash', self.client.get('/welcome').data)

    def test_save_persists_all_preferences_for_only_the_new_account(self):
        self.signup()
        response = self.submit(**IMPERIAL, display_name='  Alex Diver  ', home_location=self.location.lower(), starting_dive_count='123')
        self.assertEqual(response.location, '/welcome')
        account = self.account()
        for field, value in {**IMPERIAL, 'display_name': 'Alex Diver', 'home_location': self.location, 'starting_dive_count': 123}.items():
            self.assertEqual(account[field], value)
        other = self.account(1)
        self.assertEqual({field: other[field] for field in METRIC}, METRIC)
        self.assertIsNone(other['display_name'])
        self.assertIn('<h1>Alex Diver</h1>', self.client.get('/you').text)
        for field, unit in IMPERIAL.items():
            self.assertIn(f'name="{field}" value="{unit}" data-unit-toggle="{field.removesuffix("_unit")}" checked', self.client.get('/you/settings').text)
        with self.client.session_transaction() as session:
            self.assertNotIn('onboarding_next', session)
            self.assertTrue(session.permanent)

    def test_skip_ignores_all_edits_and_invalid_fields(self):
        self.signup()
        response = self.submit(intent='skip', **IMPERIAL, display_name='Ignored', home_location='Unknown', starting_dive_count='-9')
        self.assertEqual(response.location, '/welcome')
        account = self.account()
        self.assertEqual({field: account[field] for field in METRIC}, METRIC)
        self.assertIsNone(account['display_name'])
        self.assertIsNone(account['home_location'])
        self.assertEqual(account['starting_dive_count'], 0)

    def test_empty_optional_count_saves_other_preferences(self):
        self.signup()
        self.assertEqual(self.submit(display_name='Alex', starting_dive_count='').location, '/welcome')
        self.assertEqual(self.account()['display_name'], 'Alex')
        self.assertEqual(self.account()['starting_dive_count'], 0)

    def test_invalid_values_preserve_inputs_without_partial_writes_and_can_be_corrected(self):
        self.signup()
        for invalid in ({'home_location': 'Unknown'}, {'starting_dive_count': '-1'},
                        {'starting_dive_count': '1.5'}, {'starting_dive_count': str(2**63)},
                        {'display_name': 'x' * 121}, {'pressure_unit': 'invalid'}):
            with self.subTest(invalid=invalid):
                response = self.submit(**{**IMPERIAL, 'display_name': 'Alex', 'starting_dive_count': '25', **invalid})
                self.assertEqual(response.status_code, 400)
                self.assertIn('role="alert"', response.text)
                self.assertIn('value="25"' if 'starting_dive_count' not in invalid else f'value="{invalid["starting_dive_count"]}"', response.text)
                self.assertIsNone(self.account()['display_name'])
                self.assertEqual(self.account()['pressure_unit'], 'bar')
        self.assertEqual(self.submit(display_name='Alex', home_location=self.location, starting_dive_count='25').location, '/welcome')

    def test_csrf_is_required_for_both_save_and_skip(self):
        self.signup()
        for intent in ('save', 'skip'):
            for token in (None, 'wrong'):
                payload = {'intent': intent, 'display_name': 'Not saved'}
                if token is not None:
                    payload['csrf_token'] = token
                self.assertEqual(self.client.post('/auth/setup', data=payload).status_code, 400)
                self.assertIsNone(self.account()['display_name'])
        self.assertEqual(self.submit(intent='unknown').status_code, 400)
        self.assertEqual(self.submit(intent='skip').location, '/welcome')

    def test_shared_destinations_are_preserved_and_external_destinations_are_rejected(self):
        self.signup(destination='/dive-sites/42?tab=conditions')
        self.assertEqual(self.submit().location, '/dive-sites/42?tab=conditions')
        with self.client.session_transaction() as session:
            session['onboarding_next'] = 'https://untrusted.example/'
        self.client.get('/auth/setup')
        with self.client.session_transaction() as session:
            self.csrf = session['google_csrf']
        self.assertEqual(self.submit(intent='skip').location, '/welcome')

    def test_completed_setup_cannot_be_replayed_or_update_settings(self):
        self.signup()
        self.submit(display_name='Saved')
        self.assertEqual(self.client.get('/auth/setup').location, '/home')
        self.assertEqual(self.submit(display_name='Replayed').location, '/home')
        self.assertEqual(self.account()['display_name'], 'Saved')
        self.client.post('/logout')
        self.assertEqual(self.client.get('/auth/setup').status_code, 302)
        self.assertEqual(self.client.post('/auth/setup').status_code, 302)
