import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw
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

    def test_preview_image_without_photos_is_public_jpeg(self):
        response = self.client.get("/share/dive/1/preview.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))

    def upload_photos(self):
        photos = []
        for name, color in (("primary.jpg", "#17adad"), ("second.jpg", "#ff6633")):
            stream = io.BytesIO()
            Image.new("RGB", (200, 300), color).save(stream, "JPEG")
            stream.seek(0)
            photos.append((stream, name))
        self.login_session()
        response = self.client.post("/dive/1/edit", data={
            "site_name": "Blue Corner", "country_or_area": "Palau",
            "date": "2026-10-01",
            "depth_m": "24", "duration_min": "52", "photos": photos,
        })
        self.assertEqual(response.status_code, 302)

    def assert_preview_photo_color(self, color):
        # Check the actual public JPEG, beyond the gradient and text panel.
        guest = self.app.test_client()
        response = guest.get("/share/dive/1/preview.jpg")
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.data)) as image:
            self.assertEqual(image.size, (1200, 630))
            pixel = image.getpixel((1100, 300))
            for actual, expected in zip(pixel, color):
                self.assertLessEqual(abs(actual - expected), 3)
        download = guest.get("/share/dive/1/preview.jpg?download=1")
        self.assertEqual(download.data, response.data)

    def test_uploaded_primary_photo_appears_in_public_and_saved_thumbnail(self):
        self.upload_photos()
        self.assert_preview_photo_color((23, 173, 173))

    def test_unavailable_primary_photo_uses_next_photo_then_ocean_fallback(self):
        fallback = self.app.test_client().get("/share/dive/1/preview.jpg").data
        self.upload_photos()
        with self.app.app_context():
            photos = database.get_db().execute("SELECT filename FROM photos ORDER BY id").fetchall()
            paths = [Path(self.app.config["UPLOAD_FOLDER"], photo["filename"].removeprefix("uploads/")) for photo in photos]
        paths[0].unlink()
        self.assert_preview_photo_color((255, 102, 51))
        paths[0].write_bytes(b"unreadable photo")
        self.assert_preview_photo_color((255, 102, 51))
        paths[1].write_bytes(b"unreadable photo")
        self.assertEqual(self.app.test_client().get("/share/dive/1/preview.jpg").data, fallback)

    def test_thumbnail_cannot_load_a_photo_outside_upload_folder(self):
        fallback = self.client.get("/share/dive/1/preview.jpg").data
        Image.new("RGB", (200, 300), "#ff6633").save(Path(self.tmp.name, "outside.jpg"))
        with self.app.app_context():
            database.get_db().execute("INSERT INTO photos (dive_id, filename) VALUES (1, 'uploads/../outside.jpg')")
            database.get_db().commit()
        self.assertEqual(self.client.get("/share/dive/1/preview.jpg").data, fallback)

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

    def test_complete_titles_are_drawn_inside_the_headline_area(self):
        original_text = ImageDraw.ImageDraw.text
        for title in (
            "Blue Corner",
            "Kicker Rock (Leon Dormido)",
            "NorthwesternSanctuary Entrance",
            "Great Blue Hole and Lighthouse Reef National Marine Reserve",
            "Very long dive site name " * 15,
            "AReallyLongUnbrokenDiveSiteName" * 4,
        ):
            with self.subTest(title=title):
                drawn = []

                def record_text(draw, xy, text, *args, **kwargs):
                    if xy[0] == 54 and kwargs.get("fill") == "white":
                        drawn.append((text, draw.textbbox(xy, text, font=kwargs["font"], anchor=kwargs["anchor"])))
                    return original_text(draw, xy, text, *args, **kwargs)

                with self.app.app_context():
                    database.get_db().execute("UPDATE dives SET site_name = ? WHERE id = 1", (title,))
                    database.get_db().commit()
                with patch.object(ImageDraw.ImageDraw, "text", new=record_text):
                    response = self.client.get("/share/dive/1/preview.jpg")
                self.assertEqual(response.status_code, 200)
                self.assertEqual("".join(text for text, _ in drawn).replace(" ", ""), title.replace(" ", ""))
                for text, (left, top, right, bottom) in drawn:
                    self.assertNotIn("…", text)
                    self.assertGreaterEqual(left, 50)
                    self.assertLessEqual(right, 604)
                    self.assertGreaterEqual(top, 150)
                    self.assertLessEqual(bottom, 320)
                if title == "NorthwesternSanctuary Entrance":
                    self.assertIn("NorthwesternSanctuary", [text for text, _ in drawn])


if __name__ == "__main__":
    unittest.main()
