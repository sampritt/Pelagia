import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pelagia import create_app, fetch_dives
from pelagia import db as database


class FeedChronologyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            self.app = create_app({
                "TESTING": True,
                "SECRET_KEY": "feed-tests",
                "DATABASE": str(Path(temporary.name) / "test.sqlite3"),
                "UPLOAD_FOLDER": str(Path(temporary.name) / "uploads"),
            })
        self.enterContext(self.app.app_context())
        self.db = database.get_db()
        self.db.execute("INSERT INTO users (username) VALUES ('diver')")
        self.db.execute("INSERT INTO users (username) VALUES ('buddy')")
        self.db.execute("INSERT INTO dive_centers (name) VALUES ('Dive center')")
        self.db.execute("INSERT INTO dive_sites (name) VALUES ('Dive site')")
        self.older_dive_day = self.db.execute("SELECT date('now', '-14 days')").fetchone()[0]

    def add_dive(self, day, uploaded, *, user_id=1, deleted=0):
        dive_id = self.db.execute(
            """INSERT INTO dives
               (user_id, date, site_name, created_at, dive_site_id, dive_center_id, is_deleted)
               VALUES (?, ?, 'Dive site', datetime('now', ?), 1, 1, ?)""",
            (user_id, day, uploaded, deleted),
        ).lastrowid
        self.db.commit()
        return dive_id

    def feed_ids(self, **kwargs):
        return [dive["id"] for dive in fetch_dives(scope="all", user_id=1, **kwargs)]

    def test_recent_backdated_uploads_sort_by_upload_time_across_divers(self):
        older_upload = self.add_dive(self.older_dive_day, "-14 days")
        recent_upload = self.add_dive("2025-01-01", "-2 days")
        newest_upload = self.add_dive("2024-01-01", "-1 day", user_id=2)
        self.assertEqual(self.feed_ids(), [newest_upload, recent_upload, older_upload])
        # Promotion must happen before the feed limit is applied.
        self.assertEqual(self.feed_ids(limit=1), [newest_upload])

        client = self.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = 1
        response = client.get("/home")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [int(value) for value in re.findall(rb'data-dive-card data-dive-id="(\d+)"', response.data)],
            [newest_upload, recent_upload, older_upload],
        )

    def test_seven_day_window_uses_upload_time_and_expires(self):
        newer_dive = self.add_dive(self.older_dive_day, "-14 days")
        just_inside = self.add_dive("2023-01-01", "-10079 minutes")
        just_outside = self.add_dive("2024-01-01", "-10081 minutes")
        self.assertEqual(self.feed_ids(), [just_inside, newer_dive, just_outside])
        self.db.execute(
            "UPDATE dives SET created_at = datetime('now', '-7 days', '-1 minute') WHERE id = ?",
            (just_inside,),
        )
        self.db.commit()
        self.assertEqual(self.feed_ids(), [newer_dive, just_outside, just_inside])

    def test_older_dives_keep_dive_date_order_and_same_day_upload_tie_breaker(self):
        older_dive = self.add_dive("2024-01-01", "-8 days")
        first_same_day = self.add_dive("2025-01-01", "-10 days")
        second_same_day = self.add_dive("2025-01-01", "-9 days")
        self.assertEqual(self.feed_ids(), [second_same_day, first_same_day, older_dive])

    def test_simultaneous_uploads_keep_dive_date_tie_breaker(self):
        older_dive = self.add_dive("2024-01-01", "-1 day")
        newer_dive = self.add_dive("2025-01-01", "-1 day")
        # Give both records exactly the same timestamp, even across a clock tick.
        self.db.execute(
            "UPDATE dives SET created_at = (SELECT created_at FROM dives WHERE id = ?) WHERE id = ?",
            (older_dive, newer_dive),
        )
        self.db.commit()
        self.assertEqual(self.feed_ids(), [newer_dive, older_dive])

    def test_other_lists_keep_dive_date_order(self):
        newer_dive = self.add_dive("2025-01-01", "-14 days")
        recent_backdated = self.add_dive("2024-01-01", "-1 day")
        for scope, filters in (("mine", {}), ("site", {"site_id": 1}), ("center", {"center_id": 1})):
            with self.subTest(scope=scope):
                self.assertEqual(
                    [dive["id"] for dive in fetch_dives(scope=scope, user_id=1, **filters)],
                    [newer_dive, recent_backdated],
                )

    def test_deleted_recent_uploads_stay_hidden(self):
        visible = self.add_dive("2025-01-01", "-14 days")
        self.add_dive("2024-01-01", "-1 day", deleted=1)
        self.assertEqual(self.feed_ids(), [visible])
