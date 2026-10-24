import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_reference_autocomplete as fixtures
from pelagia import db as database


DELETE_URL = "/you/settings/delete-account"


class AccountDeletionTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.app, self.db_path, _ = self.make_app(self.root)
        self.client = self.app.test_client()
        self.other = self.app.test_client()
        self.signup(self.client, "owner")
        self.signup(self.other, "other")

    def csrf(self, client=None):
        response = (client or self.client).get(DELETE_URL)
        return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def seed_account_data(self):
        self.files = ["profiles/owner.jpg", "dives/active.jpg", "dives/deleted.jpg", "profiles/other.jpg", "dives/other.jpg"]
        for filename in self.files:
            (self.root / "uploads" / filename).write_bytes(b"photo")
        with self.app.app_context():
            db = database.get_db()
            db.execute("""UPDATE users SET login_email = 'owner@example.test', google_email = 'google@example.test',
                          profile_photo = 'uploads/profiles/owner.jpg', bio = 'Private bio',
                          length_unit = 'ft', starting_dive_count = 99, certification_id = 1 WHERE id = 1""")
            db.execute("UPDATE users SET profile_photo = 'uploads/profiles/other.jpg' WHERE id = 2")
            for user_id, deleted, photo in ((1, 0, "active"), (1, 1, "deleted"), (2, 0, "other")):
                dive_id = db.execute(
                    """INSERT INTO dives (user_id, buddy_user_id, dive_site_id, date, site_name, is_deleted, notes)
                       VALUES (?, ?, 1, '2026-10-01', 'Alert Rock', ?, 'Dive notes')""",
                    (user_id, 2 if user_id == 1 else 1, deleted),
                ).lastrowid
                db.execute("INSERT INTO photos (dive_id, filename) VALUES (?, ?)", (dive_id, f"uploads/dives/{photo}.jpg"))
                db.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (?, 'Coral')", (dive_id,))
                for commenter in (1, 2):
                    db.execute("INSERT INTO likes (dive_id, user_id) VALUES (?, ?)", (dive_id, commenter))
                    db.execute("INSERT INTO comments (dive_id, user_id, body) VALUES (?, ?, 'A comment')", (dive_id, commenter))
            for prefix, entity in (("dive_site", "dive_site_id"), ("dive_center", "dive_center_id")):
                for user_id in (1, 2):
                    db.execute(f"INSERT INTO {prefix}_likes ({entity}, user_id) VALUES (1, ?)", (user_id,))
                    db.execute(f"INSERT INTO {prefix}_comments ({entity}, user_id, body) VALUES (1, ?, 'Comment')", (user_id,))
            for index, (email, link_user) in enumerate((
                ("OWNER@example.test", None), ("google@example.test", None),
                ("old@example.test", 1), ("other@example.test", 2),
            )):
                db.execute(
                    "INSERT INTO email_challenges (id, email, code_hash, created, ip, link_user) VALUES (?, ?, 'hash', ?, 'ip', ?)",
                    (str(index), email, time.time(), link_user),
                )
            db.commit()

    def test_confirmation_and_keep_account_do_not_delete_anything(self):
        settings = self.client.get("/you/settings").text
        account = settings.split('aria-labelledby="settingsAccountTitle"', 1)[1]
        self.assertLess(account.index(">Log out</button>"), account.index(">Delete Account</a>"))
        self.assertIn(f'href="{DELETE_URL}"', account)
        response = self.client.get(DELETE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("Are you sure you want to delete your account? This action cannot be undone.", response.text)
        self.assertIn('class="primary-button account-delete-button" type="submit">Delete account</button>', response.text)
        self.assertIn('class="ghost-button" href="/you/settings">Keep my account</a>', response.text)
        self.assertEqual(self.client.get("/you/settings").status_code, 200)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)

    def test_deletion_erases_owned_data_uploads_and_authentication_and_preserves_other_users(self):
        self.seed_account_data()
        token = self.csrf()
        stale = self.app.test_client()
        stale.set_cookie("session", self.client.get_cookie("session").value)
        response = self.client.post(DELETE_URL, data={"csrf_token": token, "user_id": "2", "next": "/home"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.client.session_transaction() as session:
            self.assertEqual(dict(session), {})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(stale.get("/you").status_code, 302)
        self.assertEqual(self.other.get("/you/settings").status_code, 200)
        for filename in self.files:
            expected = "other" in filename
            self.assertEqual((self.root / "uploads" / filename).exists(), expected, filename)
            upload = self.client.get(f"/uploads/{filename}")
            self.assertEqual(upload.status_code, 200 if expected else 404)
            upload.close()
        for dive_id in (1, 2):
            for suffix in ("", "/preview.jpg", "/transparent.png"):
                self.assertEqual(self.client.get(f"/share/dive/{dive_id}{suffix}").status_code, 404)
            self.assertEqual(self.other.get(f"/dive/{dive_id}").status_code, 404)
        self.assertEqual(self.other.get("/users/1").status_code, 404)
        self.assertEqual(self.other.get("/api/users?q=owner").json, [])
        with self.app.app_context():
            db = database.get_db()
            self.assertEqual([row[0] for row in db.execute("SELECT username FROM users")], ["other"])
            self.assertEqual([tuple(row) for row in db.execute("SELECT id, user_id, buddy_user_id FROM dives")], [(3, 2, None)])
            for table in ("photos", "dive_species", "likes", "comments"):
                self.assertEqual([row[0] for row in db.execute(f"SELECT dive_id FROM {table}")], [3], table)
            for table in ("likes", "comments", "dive_site_likes", "dive_site_comments", "dive_center_likes", "dive_center_comments"):
                self.assertEqual([row[0] for row in db.execute(f"SELECT user_id FROM {table}")], [2], table)
            self.assertEqual([row[0] for row in db.execute("SELECT email FROM email_challenges")], ["other@example.test"])
            self.assertEqual(db.execute("SELECT logged_dive_count FROM dive_sites WHERE id = 1").fetchone()[0], 1)
            for table in ("dive_sites", "dive_centers", "species", "site_species", "certifications"):
                self.assertGreater(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            # Account identities and usernames are freed for a fresh signup.
            replacement_id = db.execute("""INSERT INTO users (username, google_subject, google_email, login_email)
                                         VALUES ('owner', 'test-owner', 'google@example.test', 'owner@example.test')""").lastrowid
            self.assertGreater(replacement_id, 2)
            db.commit()
        self.assertEqual(stale.get("/you").status_code, 302)

    def test_deletion_requires_login_and_a_csrf_token_from_the_current_session(self):
        guest = self.app.test_client()
        for method in (guest.get, guest.post):
            self.assertEqual(method(DELETE_URL).status_code, 302)
        for token in (None, "invalid", self.csrf(self.other)):
            payload = {} if token is None else {"csrf_token": token}
            self.assertEqual(self.client.post(DELETE_URL, data=payload).status_code, 400)
        self.assertEqual(self.client.get("/you/settings").status_code, 200)

    def test_missing_photos_and_accounts_without_dives_can_be_deleted(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("UPDATE users SET profile_photo = 'uploads/profiles/missing.jpg' WHERE id = 1")
            db.commit()
        self.assertEqual(self.client.post(DELETE_URL, data={"csrf_token": self.csrf()}).location, "/")

    def test_database_failure_rolls_back_and_does_not_remove_uploads(self):
        self.seed_account_data()
        with self.app.app_context():
            db = database.get_db()
            db.executescript("CREATE TRIGGER reject_account_deletion BEFORE DELETE ON users BEGIN SELECT RAISE(ABORT, 'test failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post(DELETE_URL, data={"csrf_token": self.csrf()})
        with self.app.app_context():
            db = database.get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM email_challenges").fetchone()[0], 4)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dives").fetchone()[0], 3)
        for filename in self.files:
            self.assertTrue((self.root / "uploads" / filename).exists())

    def test_upload_failure_does_not_report_success_or_delete_account_records(self):
        self.seed_account_data()
        token = self.csrf()
        with patch("pelagia._delete_uploaded_file", side_effect=PermissionError), self.assertLogs(self.app.logger, level="ERROR"):
            response = self.client.post(DELETE_URL, data={"csrf_token": token})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Please try again.", response.text)
        self.assertEqual(self.client.get("/you/settings").status_code, 200)
        with self.app.app_context():
            db = database.get_db()
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dives").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
