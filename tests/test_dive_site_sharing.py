import tempfile
import unittest
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_reference_autocomplete as fixtures
from pelagia import db as database
from pelagia.sharing import fetch_public_dive_site


class LocationInputsParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name") in (
            "site_name", "dive_site_id", "country_or_area", "latitude", "longitude"
        ):
            self.values[attrs["name"]] = attrs.get("value", "")


class DiveSiteSharingTest(unittest.TestCase):
    make_app = fixtures.ReferenceAutocompleteTest.make_app
    signup = fixtures.ReferenceAutocompleteTest.signup

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app, _, _ = self.make_app(Path(self.directory.name))
        self.app.config.update(PUBLIC_BASE_URL="https://pelagia.example")
        self.client = self.app.test_client()
        self.signup(self.client, username="PRIVATE_DIVER")
        with self.app.app_context():
            db = database.get_db()
            db.execute("INSERT INTO dive_site_descriptions (dive_site_id, description, citations_json, model) VALUES (1, ?, '[]', 'test')",
                       ("A rocky reef reached by boat, with kelp and harbor seals.",))
            for deleted in (0, 0, 1):
                cursor = db.execute(
                    "INSERT INTO dives (user_id, dive_site_id, date, site_name, depth_m, duration_min, notes, visibility_m, current_strength, water_temp_c, is_deleted) "
                    "VALUES (1, 1, ?, 'PRIVATE_LOG_TITLE', 37, 63, 'PRIVATE_LOG_NOTES', 17, 'strong', 13, ?)",
                    (date.today().isoformat(), deleted),
                )
                db.execute("INSERT INTO dive_species (dive_id, common_name) VALUES (?, ?)",
                           (cursor.lastrowid, "DELETED_SPECIES" if deleted else "Harbor Seal"))
            db.execute("INSERT INTO dive_site_comments (dive_site_id, user_id, body) VALUES (1, 1, 'PRIVATE_SITE_COMMENT')")
            db.execute("INSERT INTO dive_site_likes (dive_site_id, user_id) VALUES (1, 1)")
            db.commit()

    def test_public_preview_shows_headline_description_and_aggregated_sightings(self):
        response = self.app.test_client().get("/share/dive-site/1")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for visible in ("Alert Rock", "Alaska", "54.10000, -132.90000", "A rocky reef reached by boat", "Harbor Seal", "<strong>2</strong>", "Create your free account"):
            self.assertIn(visible, html)
        for private in ("PRIVATE_DIVER", "PRIVATE_LOG_TITLE", "PRIVATE_LOG_NOTES", "PRIVATE_SITE_COMMENT", "DELETED_SPECIES",
                        "data-site-comment", 'class="feed-list', 'class="site-line-chart"', 'class="site-bar-chart"', "data-site-like", "data-description-url"):
            self.assertNotIn(private, html)
        self.assertIn('class="dive-preview-placeholder" aria-hidden="true" inert', html)
        self.assertIn("live dive site conditions and the dive log", html)
        self.assertIn('property="og:url" content="https://pelagia.example/share/dive-site/1"', html)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn("Cookie", response.headers["Vary"])

    def test_public_preview_never_fetches_conditions_dive_logs_or_private_site_fields(self):
        with patch("pelagia.fetch_dives", side_effect=AssertionError("Private dive log loaded")), \
             patch("pelagia.fetch_dive_site", side_effect=AssertionError("Private site loaded")), \
             patch("pelagia.dive_site_recent_conditions", side_effect=AssertionError("Conditions loaded")), \
             patch("pelagia.dive_site_condition_series", side_effect=AssertionError("Conditions loaded")):
            self.assertEqual(self.app.test_client().get("/share/dive-site/1").status_code, 200)
        with self.app.app_context():
            self.assertEqual(set(fetch_public_dive_site(1)), {"id", "name", "country_or_area", "latitude", "longitude", "like_count"})

    def test_share_is_next_to_like_beneath_description_on_full_site(self):
        html = self.client.get("/dive-sites/1").get_data(as_text=True)
        actions = html.split('<div class="profile-actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(actions.index("data-site-like"), actions.index("data-site-share"))
        self.assertIn('href="https://pelagia.example/share/dive-site/1"', actions)
        self.assertIn('class="primary-button compact" href="/dive/new?dive_site_id=1"', actions)
        self.assertLess(actions.index("data-site-share"), actions.index("/dive/new?dive_site_id=1"))
        self.assertLess(html.index('class="site-description"'), html.index('class="profile-actions"'))
        self.assertIn("PRIVATE_LOG_TITLE", html)
        self.assertIn("PRIVATE_SITE_COMMENT", html)
        self.assertIn('data-marine-chart="tide"', html)

    def test_log_dive_prefills_and_saves_the_selected_site(self):
        response = self.client.get("/dive/new?dive_site_id=1")
        self.assertEqual(response.status_code, 200)
        location = LocationInputsParser(response.get_data(as_text=True)).values
        self.assertEqual(location, {
            "site_name": "Alert Rock", "dive_site_id": "1", "country_or_area": "Alaska",
            "latitude": "54.1", "longitude": "-132.9",
        })
        saved = self.client.post("/dive/new?dive_site_id=1", data={
            **location, "date": date.today().isoformat(), "depth_m": "12", "duration_min": "45",
        })
        self.assertEqual(saved.status_code, 302)
        dive_id = int(saved.location.rsplit("/", 1)[1])
        dive = self.client.get(f"/api/dives/{dive_id}").get_json()
        self.assertEqual(dive["site_name"], "Alert Rock")
        with self.app.app_context():
            row = database.get_db().execute("SELECT dive_site_id FROM dives WHERE id = ?", (dive_id,)).fetchone()
            self.assertEqual(row["dive_site_id"], 1)
        edit = self.client.get(f"/dive/{dive_id}/edit?dive_site_id=3")
        self.assertEqual(LocationInputsParser(edit.get_data(as_text=True)).values, location)

    def test_log_dive_without_a_valid_site_keeps_location_empty(self):
        for query in ("", "?dive_site_id=invalid", "?dive_site_id=99999"):
            with self.subTest(query=query):
                response = self.client.get("/dive/new" + query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(LocationInputsParser(response.get_data(as_text=True)).values, {
                    "site_name": "", "dive_site_id": "", "country_or_area": "", "latitude": "", "longitude": "",
                })

    def test_signed_in_share_visitors_open_the_full_site(self):
        response = self.client.get("/share/dive-site/1")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/dive-sites/1")
        self.assertIn(b"PRIVATE_LOG_TITLE", self.client.get(response.location).data)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_public_ctas_keep_the_site_destination_through_auth_entry(self):
        html = self.app.test_client().get("/share/dive-site/1").get_data(as_text=True)
        self.assertIn('href="/?next=/dive-sites/1&amp;mode=signup"', html)
        self.assertIn('href="/?next=/dive-sites/1"', html)
        guest = self.app.test_client()
        signup = guest.get("/?next=/dive-sites/1&mode=signup")
        self.assertEqual(urlsplit(signup.location).path, "/signup")
        self.assertEqual(parse_qs(urlsplit(signup.location).query)["next"], ["/dive-sites/1"])
        self.assertIn(b"next=/dive-sites/1", guest.get(signup.location).data)
        self.assertEqual(guest.get("/dive-sites/1").status_code, 302)
        self.assertEqual(guest.post("/api/dive-sites/1/description").status_code, 302)

    def test_uncached_or_empty_sites_do_not_generate_descriptions_for_guests(self):
        with self.app.app_context():
            db = database.get_db()
            db.execute("UPDATE dive_sites SET latitude = NULL, longitude = NULL, country_or_area = '' WHERE id = 2")
            db.commit()
        with patch("pelagia.site_descriptions.generate_description", side_effect=AssertionError("Guest generated description")):
            html = self.app.test_client().get("/share/dive-site/2").get_data(as_text=True)
        self.assertIn("Kelp Garden", html)
        self.assertIn("Location pending", html)
        self.assertIn("Coordinates pending", html)
        self.assertIn("No marine species observations yet.", html)
        self.assertNotIn("data-description-url", html)
        for client in (self.client, self.app.test_client()):
            self.assertEqual(client.get("/share/dive-site/99999").status_code, 404)
