import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image
from werkzeug.security import generate_password_hash

from pelagia import create_app
from pelagia import db as database
from pelagia.sharing import fetch_public_dive


class DiveSharingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch("pelagia._load_json_config", return_value={}), patch("pelagia._ensure_reference_data"):
            self.app = create_app({
                "TESTING": True, "SECRET_KEY": "sharing-tests",
                "DATABASE": str(Path(self.tmp.name) / "test.sqlite3"),
                "UPLOAD_FOLDER": str(Path(self.tmp.name) / "uploads"),
                "GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": "",
                "PUBLIC_BASE_URL": "https://pelagia.example",
            })
        self.client = self.app.test_client()
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO users (username, password_hash, google_email, profile_photo) VALUES (?, ?, ?, ?)",
                       ("maya", generate_password_hash("password"), "private@example.com", "profiles/maya.jpg"))
            db.execute("INSERT INTO users (username, password_hash) VALUES ('private-buddy', '')")
            db.execute("""INSERT INTO dives (user_id, buddy_user_id, date, site_name, country_or_area,
                       latitude, longitude, depth_m, duration_min, notes, exposure, weight_kg)
                       VALUES (1, 2, '2026-10-01', 'Blue Corner', 'Palau', 7.134, 134.22, 24, 52,
                       'PRIVATE DIVE NOTES', 'dry suit', 7.5)""")
            db.execute("INSERT INTO comments (dive_id, user_id, body) VALUES (1, 2, 'PRIVATE COMMENT')")
            db.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (1, 'PRIVATE SPECIES')")
            db.commit()

    def login_session(self, user_id=1):
        with self.client.session_transaction() as session:
            session["user_id"] = user_id

    def test_guest_preview_allowlist_and_metadata(self):
        response = self.client.get("/share/dive/1")
        self.assertEqual(response.status_code, 200)
        for visible in (b"Blue Corner", b"Palau", b"maya", b"profiles/maya.jpg", b"data-map-lat", b"See the whole dive."):
            self.assertIn(visible, response.data)
        for secret in (b"PRIVATE DIVE NOTES", b"PRIVATE COMMENT", b"PRIVATE SPECIES", b"private-buddy", b"private@example.com", b"dry suit", b"7.5"):
            self.assertNotIn(secret, response.data)
        self.assertIn(b'content="maya logged a dive', response.data)
        self.assertIn(b'https://pelagia.example/share/dive/1/preview.jpg', response.data)
        self.assertIn("no-store", response.headers["Cache-Control"])
        with self.app.app_context():
            dive = fetch_public_dive(1)
            self.assertNotIn("notes", dive)
            self.assertNotIn("user_id", dive)

    def test_signed_in_visitor_redirects_to_normal_dive(self):
        self.login_session(2)
        response = self.client.get("/share/dive/1")
        self.assertEqual(response.location, "/dive/1")
        self.assertIn(b"PRIVATE DIVE NOTES", self.client.get(response.location).data)

    def test_owner_has_share_on_detail_feed_and_profile(self):
        self.login_session()
        for url in ("/dive/1", "/home", "/you"):
            self.assertIn(b"data-share-dive", self.client.get(url).data)
        self.login_session(2)
        self.assertNotIn(b"data-share-dive", self.client.get("/dive/1").data)

    def test_full_dive_api_remains_authenticated(self):
        for url in ("/api/dives/1", "/dive/1"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertNotIn(b"PRIVATE DIVE NOTES", response.data)

    def test_password_auth_returns_to_dive_and_retains_failures(self):
        failed = self.client.post("/login", data={"username": "maya", "password": "wrong", "next": "/dive/1"})
        self.assertEqual(parse_qs(urlsplit(failed.location).query)["next"], ["/dive/1"])
        auth = self.client.get(failed.location)
        self.assertIn(b'name="next" value="/dive/1"', auth.data)
        response = self.client.post("/login", data={"username": "maya", "password": "password", "next": "/dive/1"})
        self.assertEqual(response.location, "/dive/1")

    def test_signup_returns_to_dive_and_initial_mode_is_signup(self):
        self.assertIn(b'data-auth-mode="signup"', self.client.get("/?next=/dive/1&mode=signup").data)
        response = self.client.post("/signup", data={"username": "new-diver", "password": "password", "next": "/dive/1"})
        self.assertEqual(response.location, "/dive/1")

    def test_external_and_backslash_auth_redirects_are_rejected(self):
        for next_url in ("https://evil.example", "//evil.example", "/\\evil.example", "https://localhost@evil.example", "http://localhost//evil.example"):
            with self.subTest(next_url=next_url):
                client = self.app.test_client()
                response = client.post("/login", data={"username": "maya", "password": "password", "next": next_url})
                self.assertEqual(response.location, "/home")

    def test_preview_image_is_public_jpeg_with_and_without_photos(self):
        for with_photo in (False, True):
            if with_photo:
                with self.app.app_context():
                    filename = Path(self.app.config["UPLOAD_FOLDER"], "dives/photo.jpg")
                    Image.new("RGB", (200, 300), "#17adad").save(filename)
                    database.get_db().execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'dives/photo.jpg')")
                    database.get_db().commit()
            response = self.client.get("/share/dive/1/preview.jpg")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/jpeg")
            with Image.open(io.BytesIO(response.data)) as image:
                self.assertEqual(image.size, (1200, 630))
            if with_photo:
                self.assertIn(b"dives/photo.jpg", self.client.get("/share/dive/1").data)

    def test_save_downloads_a_named_jpeg_attachment(self):
        response = self.client.get("/share/dive/1/preview.jpg?download=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("pelagia-Blue_Corner.jpg", response.headers["Content-Disposition"])
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))

    def test_deleted_and_missing_dives_have_no_public_page_or_image(self):
        self.login_session()
        self.client.post("/dive/1/delete")
        for client in (self.client, self.app.test_client()):
            for dive_id in (1, 999):
                for suffix in ("", "/preview.jpg"):
                    self.assertEqual(client.get(f"/share/dive/{dive_id}{suffix}").status_code, 404)

    def test_no_coordinates_and_long_escaped_titles(self):
        with self.app.app_context():
            database.get_db().execute("UPDATE dives SET latitude = NULL, longitude = NULL, site_name = ?", ("<script>alert(1)</script> " + "Long dive site " * 15,))
            database.get_db().commit()
        response = self.client.get("/share/dive/1")
        self.assertIn(b"Coordinates pending", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)
        self.assertEqual(self.client.get("/share/dive/1/preview.jpg").status_code, 200)


if __name__ == "__main__":
    unittest.main()
