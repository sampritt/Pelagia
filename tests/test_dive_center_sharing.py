import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_reference_autocomplete as fixtures
from pelagia import db as database
from pelagia.sharing import fetch_public_dive_center


class DiveCenterSharingTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = self.make_app(Path(self.directory.name))
        self.app.config["PUBLIC_BASE_URL"] = "https://pelagia.example"
        self.client = self.app.test_client()
        self.signup(self.client, username="PRIVATE_DIVER")
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO dives (user_id, dive_center_id, date, site_name, notes, visibility_m) "
                       "VALUES (1, 1, '2026-10-23', 'PRIVATE_LOG_TITLE', 'PRIVATE_LOG_NOTES', 17)")
            db.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (1, 'PRIVATE_SPECIES')")
            db.execute("INSERT INTO dive_center_comments (dive_center_id, user_id, body) VALUES (1, 1, 'PRIVATE_CENTER_COMMENT')")
            db.execute("INSERT INTO dive_center_likes (dive_center_id, user_id) VALUES (1, 1)")
            db.commit()

    def test_public_preview_shows_center_details_and_gates_logs_and_comments(self):
        response = self.app.test_client().get("/share/dive-center/1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for visible in ("Shark Bay Dive Center", "Galapagos Ecuador", "1 Ocean Road", 'href="https://example.test"',
                        'aria-label="1 likes"', "Create your free account", "logged dives and community comments"):
            self.assertIn(visible, html)
        for private in ("PRIVATE_DIVER", "PRIVATE_LOG_TITLE", "PRIVATE_LOG_NOTES", "PRIVATE_SPECIES", "PRIVATE_CENTER_COMMENT",
                        "data-center-comment", "data-center-like", 'class="feed-list', 'class="shared-topbar"', 'href="/dive/1"'):
            self.assertNotIn(private, html)
        self.assertIn('class="dive-preview-placeholder" aria-hidden="true" inert', html)
        self.assertIn('property="og:url" content="https://pelagia.example/share/dive-center/1"', html)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn("Cookie", response.headers["Vary"])

    def test_guest_preview_does_not_load_the_feed_or_private_center_fields(self):
        with patch("pelagia.fetch_dives", side_effect=AssertionError("Guest feed loaded")), \
             patch("pelagia.fetch_dive_center", side_effect=AssertionError("Private center loaded")):
            self.assertEqual(self.app.test_client().get("/share/dive-center/1").status_code, 200)
        with self.app.app_context():
            self.assertEqual(set(fetch_public_dive_center(1)), {"id", "name", "physical_address", "location", "website", "like_count"})

    def test_full_center_has_share_beside_like_and_keeps_its_feed(self):
        html = self.client.get("/dive-centers/1").get_data(as_text=True)
        actions = html.split('<div class="profile-actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(actions.index("data-center-like"), actions.index("data-center-share"))
        self.assertIn('href="https://pelagia.example/share/dive-center/1"', actions)
        self.assertIn("PRIVATE_LOG_TITLE", html)
        self.assertIn("PRIVATE_CENTER_COMMENT", html)

    def test_signed_in_share_visitors_open_the_full_center(self):
        response = self.client.get("/share/dive-center/1")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/dive-centers/1")
        self.assertIn(b"PRIVATE_LOG_TITLE", self.client.get(response.location).data)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_account_gate_preserves_center_destination(self):
        guest = self.app.test_client()
        html = guest.get("/share/dive-center/1").get_data(as_text=True)
        self.assertIn('href="/?next=/dive-centers/1&amp;mode=signup"', html)
        self.assertIn('href="/?next=/dive-centers/1"', html)
        signup = guest.get("/?next=/dive-centers/1&mode=signup")
        self.assertEqual(urlsplit(signup.location).path, "/signup")
        self.assertEqual(parse_qs(urlsplit(signup.location).query)["next"], ["/dive-centers/1"])
        self.assertIn(b"next=/dive-centers/1", guest.get(signup.location).data)
        self.assertEqual(guest.get("/dive-centers/1").status_code, 302)
        self.assertEqual(guest.post("/api/dive-centers/1/comments", data={"body": "Guest comment"}).status_code, 302)

    def test_missing_centers_and_unlisted_details(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("UPDATE dive_centers SET physical_address = NULL, location = NULL, website = NULL WHERE id = 2")
            db.commit()
        guest = self.app.test_client()
        html = guest.get("/share/dive-center/2").get_data(as_text=True)
        self.assertIn("Kelp House", html)
        self.assertIn("Location pending", html)
        self.assertEqual(html.count("Not listed"), 3)
        self.assertIn("Create your free account", html)
        self.assertNotIn('href="None"', html)
        for client in (guest, self.client):
            self.assertEqual(client.get("/share/dive-center/99999").status_code, 404)
