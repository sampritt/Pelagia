import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pelagia import create_app
from pelagia import db as database


class DiveLimitsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with patch('pelagia._load_json_config', return_value={}), patch('pelagia._ensure_reference_data'):
            self.app = create_app({
                'TESTING': True, 'SECRET_KEY': 'limits',
                'DATABASE': str(Path(tmp.name) / 'test.sqlite3'),
                'UPLOAD_FOLDER': str(Path(tmp.name) / 'uploads'),
            })
        self.client = self.app.test_client()
        with self.app.app_context():
            db = database.get_db()
            db.executemany('INSERT INTO users (username) VALUES (?)', [('one',), ('two',)])
            db.commit()
        with self.client.session_transaction() as session:
            session['user_id'] = 1

    def seed(self, count, dive_date='2026-01-01', created_at=None, deleted=0):
        with self.app.app_context():
            db = database.get_db()
            for i in range(count):
                db.execute(
                    'INSERT INTO dives (user_id, date, site_name, created_at, is_deleted) '
                    "VALUES (1, ?, 'Test', COALESCE(?, CURRENT_TIMESTAMP), ?)",
                    (dive_date or f'2026-01-{i + 1:02}', created_at, deleted),
                )
            db.commit()

    def post(self, dive_date='2026-01-01', path='/dive/new'):
        return self.client.post(path, data={'date': dive_date, 'site_name': 'Test'})

    def test_fifth_allowed_sixth_blocked_without_body(self):
        self.seed(4)
        self.assertEqual(self.post().status_code, 302)
        response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data, b'')
        self.assertEqual(self.post('2026-02-01').status_code, 302)

    def test_twentieth_allowed_then_blocked_even_after_deletion(self):
        self.seed(19, dive_date=None, deleted=1)
        self.assertEqual(self.post('2026-02-01').status_code, 302)
        self.assertEqual(self.post('2026-02-02').status_code, 429)
        with self.client.session_transaction() as session:
            session['user_id'] = 2
        self.assertEqual(self.post().status_code, 302)

    def test_previous_days_do_not_consume_daily_quota(self):
        self.seed(20, dive_date=None, created_at='2000-01-01 00:00:00')
        self.assertEqual(self.post('2026-02-01').status_code, 302)

    def test_edit_cannot_move_sixth_dive_to_full_date(self):
        self.seed(5)
        self.seed(1, dive_date='2026-02-01')
        self.assertEqual(self.post(path='/dive/6/edit').status_code, 429)
        self.assertEqual(self.post(path='/dive/1/edit').status_code, 302)

    def test_invalid_date_rejected_and_compact_date_normalized(self):
        self.assertEqual(self.post('invalid').status_code, 400)
        self.seed(5)
        self.assertEqual(self.post('20260101').status_code, 429)
